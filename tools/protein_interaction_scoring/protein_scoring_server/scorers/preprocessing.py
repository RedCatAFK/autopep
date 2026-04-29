from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .schemas import ScoreItem
from .utils import (
    PROTEIN_RESIDUES_3,
    normalize_sequence,
    safe_item_token,
    write_structure_file,
)


RESIDUE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "U",
    "ASX": "B",
    "GLX": "Z",
    "MSE": "M",
    "SEP": "S",
    "TPO": "T",
    "PTR": "Y",
    "HYP": "P",
    "CSO": "C",
}


@dataclass
class StructurePreprocessResult:
    raw_path: Path
    scoring_path: Path
    scoring_format: str
    chain_a: str | None
    chain_b: str | None
    sequences_by_chain: dict[str, str] = field(default_factory=dict)
    protein_chains: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ProteinOnlySelect:
    def __init__(self, selected_chains: set[str] | None) -> None:
        from Bio.PDB.PDBIO import Select

        class _Select(Select):
            def accept_model(self, model):
                return model.id == 0

            def accept_chain(self, chain):
                return selected_chains is None or chain.id in selected_chains

            def accept_residue(self, residue):
                return residue.get_resname().upper() in RESIDUE_TO_ONE

            def accept_atom(self, atom):
                altloc = atom.get_altloc()
                return altloc in {" ", "A", "1"}

        self.value = _Select()


def preprocess_structure(
    item: ScoreItem,
    work_dir: Path,
    *,
    item_index: int,
) -> StructurePreprocessResult:
    if item.structure is None:
        raise ValueError("item has no structure")

    raw_path = write_structure_file(
        work_dir,
        item_index=item_index,
        item_id=item.id,
        format_name=item.structure.format,
        content_base64=item.structure.content_base64,
    )

    warnings: list[str] = []
    errors: list[str] = []
    sequences_by_chain, protein_chains, parse_warnings = extract_chain_sequences(
        raw_path,
        item.structure.format,
    )
    warnings.extend(parse_warnings)

    chain_a, chain_b = resolve_chain_pair(
        protein_chains,
        requested_chain_a=item.structure.chain_a,
        requested_chain_b=item.structure.chain_b,
        warnings=warnings,
        errors=errors,
    )

    selected_chains = {chain for chain in (chain_a, chain_b) if chain}
    scoring_path, scoring_format, sanitize_warnings = sanitize_structure_for_scoring(
        raw_path,
        item.structure.format,
        work_dir,
        item_index=item_index,
        item_id=item.id,
        selected_chains=selected_chains or None,
    )
    warnings.extend(sanitize_warnings)

    return StructurePreprocessResult(
        raw_path=raw_path,
        scoring_path=scoring_path,
        scoring_format=scoring_format,
        chain_a=chain_a,
        chain_b=chain_b,
        sequences_by_chain=sequences_by_chain,
        protein_chains=protein_chains,
        warnings=warnings,
        errors=errors,
    )


def extract_chain_sequences(
    path: Path,
    format_name: str,
) -> tuple[dict[str, str], list[str], list[str]]:
    warnings: list[str] = []
    sequences_by_chain: dict[str, str] = {}

    parsed_with_biopython = False
    try:
        sequences_by_chain = _extract_sequences_with_biopython(path, format_name)
        parsed_with_biopython = True
    except Exception as exc:
        warnings.append(f"Biopython structure parsing failed: {exc}")

    if not sequences_by_chain and format_name.lower() == "pdb":
        sequences_by_chain = _extract_sequences_from_pdb_text(path)
        if sequences_by_chain:
            warnings.append("Used lightweight PDB text parser for chain preprocessing")

    if not sequences_by_chain and not parsed_with_biopython:
        warnings.append(
            "Could not extract protein chains from structure; PRODIGY will still receive the uploaded file"
        )

    protein_chains = list(sequences_by_chain)
    return sequences_by_chain, protein_chains, warnings


def _extract_sequences_with_biopython(path: Path, format_name: str) -> dict[str, str]:
    if format_name.lower() == "pdb":
        from Bio.PDB import PDBParser

        parser = PDBParser(PERMISSIVE=True, QUIET=True)
    else:
        from Bio.PDB import MMCIFParser

        parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("complex", str(path))

    sequences: dict[str, str] = {}
    for model in structure:
        if model.id != 0:
            continue
        for chain in model:
            sequence_parts: list[str] = []
            seen_residues: set[tuple] = set()
            for residue in chain:
                residue_name = residue.get_resname().upper()
                one_letter = residue_to_one(residue_name)
                if one_letter is None:
                    continue
                residue_key = residue.id
                if residue_key in seen_residues:
                    continue
                seen_residues.add(residue_key)
                sequence_parts.append(one_letter)
            if sequence_parts:
                normalized, _warnings = normalize_sequence("".join(sequence_parts))
                sequences[chain.id] = normalized
        break
    return sequences


def _extract_sequences_from_pdb_text(path: Path) -> dict[str, str]:
    residues_by_chain: dict[str, list[str]] = {}
    seen_residues: set[tuple[str, str, str, str]] = set()
    in_first_model = False
    saw_model = False

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            record = line[:6]
            if record.startswith("MODEL"):
                saw_model = True
                if in_first_model:
                    break
                in_first_model = True
                continue
            if record.startswith("ENDMDL") and saw_model:
                break
            if saw_model and not in_first_model:
                continue
            if not record.startswith(("ATOM  ", "HETATM")) or len(line) < 27:
                continue

            altloc = line[16].strip()
            if altloc not in {"", "A", "1"}:
                continue

            residue_name = line[17:20].strip().upper()
            one_letter = residue_to_one(residue_name)
            if one_letter is None:
                continue
            chain_id = line[21].strip() or "_"
            residue_key = (
                chain_id,
                line[22:26].strip(),
                line[26].strip(),
                residue_name,
            )
            if residue_key in seen_residues:
                continue
            seen_residues.add(residue_key)
            residues_by_chain.setdefault(chain_id, []).append(one_letter)

    sequences: dict[str, str] = {}
    for chain_id, residues in residues_by_chain.items():
        normalized, _warnings = normalize_sequence("".join(residues))
        sequences[chain_id] = normalized
    return sequences


def resolve_chain_pair(
    protein_chains: list[str],
    *,
    requested_chain_a: str | None,
    requested_chain_b: str | None,
    warnings: list[str],
    errors: list[str],
) -> tuple[str | None, str | None]:
    if requested_chain_a and requested_chain_b:
        missing = [
            chain
            for chain in (requested_chain_a, requested_chain_b)
            if protein_chains and chain not in protein_chains
        ]
        if missing:
            warnings.append(
                "Provided chain identifiers were not detected during preprocessing: "
                + ", ".join(missing)
            )
        return requested_chain_a, requested_chain_b

    if len(protein_chains) < 2:
        if protein_chains:
            errors.append(
                "structure preprocessing found fewer than two protein chains"
            )
        return requested_chain_a, requested_chain_b

    if requested_chain_a and not requested_chain_b:
        inferred = first_chain_not_in(protein_chains, {requested_chain_a})
        warnings.append(f"structure.chain_b was missing; inferred {inferred}")
        return requested_chain_a, inferred

    if requested_chain_b and not requested_chain_a:
        inferred = first_chain_not_in(protein_chains, {requested_chain_b})
        warnings.append(f"structure.chain_a was missing; inferred {inferred}")
        return inferred, requested_chain_b

    warnings.append(
        f"structure.chain_a and structure.chain_b were missing; inferred {protein_chains[0]} and {protein_chains[1]}"
    )
    return protein_chains[0], protein_chains[1]


def sanitize_structure_for_scoring(
    raw_path: Path,
    format_name: str,
    work_dir: Path,
    *,
    item_index: int,
    item_id: str,
    selected_chains: set[str] | None,
) -> tuple[Path, str, list[str]]:
    warnings: list[str] = []
    sanitized_path = (
        work_dir / f"{item_index:03d}_{safe_item_token(item_id)}_preprocessed.pdb"
    )

    if format_name.lower() == "pdb":
        try:
            wrote = _write_sanitized_pdb_from_text(
                raw_path,
                sanitized_path,
                selected_chains=selected_chains,
            )
            if wrote:
                warnings.append(
                    "Prepared protein-only first-model PDB for PRODIGY scoring"
                )
                return sanitized_path, "pdb", warnings
        except Exception as exc:
            warnings.append(f"PDB text sanitization failed: {exc}")

    try:
        from Bio.PDB import MMCIFParser, PDBIO, PDBParser

        parser = (
            PDBParser(PERMISSIVE=True, QUIET=True)
            if format_name.lower() == "pdb"
            else MMCIFParser(QUIET=True)
        )
        structure = parser.get_structure("complex", str(raw_path))
        io = PDBIO()
        io.set_structure(structure)
        selector = ProteinOnlySelect(selected_chains).value
        io.save(str(sanitized_path), selector)
        if sanitized_path.exists() and sanitized_path.stat().st_size > 0:
            warnings.append(
                "Converted structure to protein-only first-model PDB for PRODIGY scoring"
            )
            return sanitized_path, "pdb", warnings
    except Exception as exc:
        warnings.append(f"Biopython structure sanitization failed: {exc}")

    warnings.append("Using uploaded structure directly for PRODIGY scoring")
    return raw_path, format_name, warnings


def _write_sanitized_pdb_from_text(
    raw_path: Path,
    sanitized_path: Path,
    *,
    selected_chains: set[str] | None,
) -> bool:
    lines: list[str] = []
    atom_serial = 1
    last_chain: str | None = None
    in_first_model = False
    saw_model = False

    with raw_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            record = line[:6]
            if record.startswith("MODEL"):
                saw_model = True
                if in_first_model:
                    break
                in_first_model = True
                continue
            if record.startswith("ENDMDL") and saw_model:
                break
            if saw_model and not in_first_model:
                continue
            if not record.startswith(("ATOM  ", "HETATM")) or len(line) < 54:
                continue

            altloc = line[16].strip()
            if altloc not in {"", "A", "1"}:
                continue

            residue_name = line[17:20].strip().upper()
            if residue_to_one(residue_name) is None:
                continue

            chain_id = line[21].strip() or "_"
            if selected_chains is not None and chain_id not in selected_chains:
                continue

            if last_chain is not None and chain_id != last_chain:
                lines.append("TER\n")
            last_chain = chain_id

            normalized = (
                "ATOM  "
                + f"{atom_serial:5d}"
                + line[11:16]
                + " "
                + line[17:54]
                + line[54:].rstrip("\n")
                + "\n"
            )
            lines.append(normalized)
            atom_serial += 1
            if atom_serial > 99999:
                raise ValueError("sanitized PDB would exceed 99999 atoms")

    if not lines:
        return False
    lines.append("TER\n")
    lines.append("END\n")
    sanitized_path.write_text("".join(lines), encoding="utf-8")
    return True


def residue_to_one(residue_name: str) -> str | None:
    residue_name = residue_name.upper()
    if residue_name in RESIDUE_TO_ONE:
        return RESIDUE_TO_ONE[residue_name]
    if residue_name in PROTEIN_RESIDUES_3:
        return RESIDUE_TO_ONE.get(residue_name, "X")
    return None


def first_chain_not_in(chains: Iterable[str], excluded: set[str]) -> str | None:
    return next((chain for chain in chains if chain not in excluded), None)
