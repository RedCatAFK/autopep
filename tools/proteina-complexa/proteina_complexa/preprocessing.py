from __future__ import annotations

import json
import gzip
import re
from dataclasses import asdict, dataclass
from pathlib import Path
import shlex
from typing import Iterable, Literal, Sequence


AMINO_ACID_3_TO_1 = {
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
    # Common structure-file substitutions that are normally interpreted as canonical AAs.
    "MSE": "M",
    "SEC": "U",
    "PYL": "O",
}

AMINO_ACID_ORDER = "ARNDCQEGHILKMFPSTWYV"
AMINO_ACID_TO_INDEX = {aa: idx for idx, aa in enumerate(AMINO_ACID_ORDER)}


@dataclass(frozen=True)
class ResidueRecord:
    chain_id: str
    residue_number: int
    insertion_code: str
    residue_name: str
    amino_acid: str
    amino_acid_index: int
    ca_coord_angstrom: tuple[float, float, float] | None


@dataclass(frozen=True)
class StructurePreprocessResult:
    structure_id: str
    sequence: str
    chain_sequences: dict[str, str]
    target_input: str
    residues: list[ResidueRecord]

    @property
    def length(self) -> int:
        return len(self.residues)

    def model_feature_dict(self) -> dict:
        residue_type = [residue.amino_acid_index for residue in self.residues]
        one_hot = [
            [1 if residue.amino_acid_index == idx else 0 for idx in range(len(AMINO_ACID_ORDER))]
            for residue in self.residues
        ]
        ca_coords_angstrom = [
            list(residue.ca_coord_angstrom) if residue.ca_coord_angstrom is not None else [0.0, 0.0, 0.0]
            for residue in self.residues
        ]
        ca_coords_nm = [[coord / 10.0 for coord in coords] for coords in ca_coords_angstrom]
        coord_mask = [residue.ca_coord_angstrom is not None for residue in self.residues]
        residue_mask = [residue.amino_acid_index >= 0 for residue in self.residues]
        return {
            "structure_id": self.structure_id,
            "sequence": self.sequence,
            "chain_sequences": self.chain_sequences,
            "target_input": self.target_input,
            "amino_acid_order": AMINO_ACID_ORDER,
            "residue_type": residue_type,
            "sequence_one_hot": one_hot,
            "ca_coords_angstrom": ca_coords_angstrom,
            "ca_coords_nm": ca_coords_nm,
            "coord_mask": coord_mask,
            "residue_mask": residue_mask,
            "residue_ids": [
                {
                    "chain_id": residue.chain_id,
                    "residue_number": residue.residue_number,
                    "insertion_code": residue.insertion_code,
                    "residue_name": residue.residue_name,
                }
                for residue in self.residues
            ],
        }

    def to_json_dict(self) -> dict:
        return {
            **asdict(self),
            "length": self.length,
            "features": self.model_feature_dict(),
        }


def parse_chain_filter(chains: str | Iterable[str] | None) -> set[str] | None:
    if chains is None:
        return None
    if isinstance(chains, str):
        values = [item.strip() for item in chains.split(",") if item.strip()]
    else:
        values = [str(item).strip() for item in chains if str(item).strip()]
    return set(values) if values else None


def preprocess_structure_text(
    structure_text: str,
    *,
    structure_id: str = "input",
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
    file_format: Literal["cif", "pdb"] | None = None,
) -> StructurePreprocessResult:
    effective_format = file_format or infer_structure_format(structure_text)
    if effective_format == "cif":
        return preprocess_cif_text(
            structure_text,
            structure_id=structure_id,
            chains=chains,
            target_input=target_input,
        )
    if effective_format == "pdb":
        return preprocess_pdb_text(
            structure_text,
            structure_id=structure_id,
            chains=chains,
            target_input=target_input,
        )
    raise ValueError(f"Unsupported structure format: {effective_format}")


def preprocess_cif_text(
    cif_text: str,
    *,
    structure_id: str = "input",
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
) -> StructurePreprocessResult:
    records = list(iter_cif_atom_site_records(cif_text))
    if not records:
        raise ValueError("No _atom_site records were found in the CIF file.")
    return records_to_preprocess_result(
        records,
        structure_id=structure_id,
        chains=chains,
        target_input=target_input,
    )


def preprocess_pdb_text(
    pdb_text: str,
    *,
    structure_id: str = "input",
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
) -> StructurePreprocessResult:
    records = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 54:
            continue
        try:
            records.append(
                {
                    "chain_id": line[21].strip() or "_",
                    "residue_name": line[17:20].strip().upper(),
                    "residue_number": int(line[22:26]),
                    "insertion_code": line[26].strip(),
                    "atom_name": line[12:16].strip(),
                    "x": float(line[30:38]),
                    "y": float(line[38:46]),
                    "z": float(line[46:54]),
                }
            )
        except ValueError:
            continue
    if not records:
        raise ValueError("No protein residues were found in the PDB ATOM records.")
    return records_to_preprocess_result(
        records,
        structure_id=structure_id,
        chains=chains,
        target_input=target_input,
    )


def records_to_preprocess_result(
    records: Iterable[dict],
    *,
    structure_id: str,
    chains: str | Iterable[str] | None,
    target_input: str | None,
) -> StructurePreprocessResult:
    chain_filter = parse_chain_filter(chains)
    residues_by_key: dict[tuple[str, int, str], dict] = {}
    residue_order: list[tuple[str, int, str]] = []

    for atom in records:
        chain_id = str(atom["chain_id"]).strip() or "_"
        if chain_filter is not None and chain_id not in chain_filter:
            continue
        residue_name = str(atom["residue_name"]).strip().upper()
        amino_acid = AMINO_ACID_3_TO_1.get(residue_name, "X")
        residue_number = int(atom["residue_number"])
        insertion_code = clean_cif_missing_value(str(atom.get("insertion_code", "")))
        key = (chain_id, residue_number, insertion_code)
        if key not in residues_by_key:
            residues_by_key[key] = {
                "chain_id": chain_id,
                "residue_number": residue_number,
                "insertion_code": insertion_code,
                "residue_name": residue_name,
                "amino_acid": amino_acid,
                "ca_coord_angstrom": None,
            }
            residue_order.append(key)
        if str(atom["atom_name"]).strip().upper() == "CA":
            residues_by_key[key]["ca_coord_angstrom"] = (float(atom["x"]), float(atom["y"]), float(atom["z"]))

    residues = [
        ResidueRecord(
            chain_id=record["chain_id"],
            residue_number=record["residue_number"],
            insertion_code=record["insertion_code"],
            residue_name=record["residue_name"],
            amino_acid=record["amino_acid"],
            amino_acid_index=AMINO_ACID_TO_INDEX.get(record["amino_acid"], -1),
            ca_coord_angstrom=record["ca_coord_angstrom"],
        )
        for record in (residues_by_key[key] for key in residue_order)
    ]
    if not residues:
        raise ValueError("No protein residues matched the requested chains.")

    chain_sequences: dict[str, list[str]] = {}
    for residue in residues:
        chain_sequences.setdefault(residue.chain_id, []).append(residue.amino_acid)

    result_chain_sequences = {chain_id: "".join(seq) for chain_id, seq in chain_sequences.items()}
    sequence = ":".join(result_chain_sequences[chain_id] for chain_id in result_chain_sequences)
    effective_target_input = target_input or infer_target_input(residues)
    return StructurePreprocessResult(
        structure_id=structure_id,
        sequence=sequence,
        chain_sequences=result_chain_sequences,
        target_input=effective_target_input,
        residues=residues,
    )


def preprocess_structure_file(
    structure_path: Path | str,
    *,
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
) -> StructurePreprocessResult:
    path = Path(structure_path)
    suffixes = [suffix.lower() for suffix in path.suffixes]
    structure_suffix = suffixes[-2] if suffixes and suffixes[-1] == ".gz" and len(suffixes) > 1 else path.suffix.lower()
    file_format = "cif" if structure_suffix in {".cif", ".mmcif"} else "pdb"
    structure_text = gzip.open(path, "rt").read() if path.suffix.lower() == ".gz" else path.read_text()
    structure_id = path.name
    if structure_id.endswith(".gz"):
        structure_id = structure_id[:-3]
    structure_id = Path(structure_id).stem
    return preprocess_structure_text(
        structure_text,
        structure_id=structure_id,
        chains=chains,
        target_input=target_input,
        file_format=file_format,
    )


def infer_target_input(residues: Sequence[ResidueRecord]) -> str:
    ranges: list[str] = []
    seen_chains: list[str] = []
    by_chain: dict[str, list[ResidueRecord]] = {}
    for residue in residues:
        if residue.chain_id not in by_chain:
            seen_chains.append(residue.chain_id)
            by_chain[residue.chain_id] = []
        by_chain[residue.chain_id].append(residue)

    for chain_id in seen_chains:
        chain_residues = by_chain[chain_id]
        if any(residue.insertion_code for residue in chain_residues):
            raise ValueError(
                "Cannot infer target_input for insertion codes. "
                "Pass target_input explicitly, for example 'A1-150'."
            )
        ranges.append(f"{chain_id}{chain_residues[0].residue_number}-{chain_residues[-1].residue_number}")
    return ",".join(ranges)


def write_preprocessed_outputs(result: StructurePreprocessResult, output_dir: Path | str) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = sanitize_name(result.structure_id)
    json_path = output_path / f"{stem}.preprocess.json"
    fasta_path = output_path / f"{stem}.fasta"
    json_path.write_text(json.dumps(result.to_json_dict(), indent=2) + "\n")
    fasta_lines = [
        f">{result.structure_id}|{chain_id}\n{sequence}\n" for chain_id, sequence in result.chain_sequences.items()
    ]
    fasta_path.write_text("".join(fasta_lines))
    return {"json": str(json_path), "fasta": str(fasta_path)}


def infer_structure_format(structure_text: str) -> Literal["cif", "pdb"]:
    for line in structure_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data_") or stripped.startswith("_atom_site.") or stripped == "loop_":
            return "cif"
        if line.startswith("ATOM") or line.startswith("HEADER"):
            return "pdb"
    return "cif"


def iter_cif_atom_site_records(cif_text: str) -> Iterable[dict]:
    lines = cif_text.splitlines()
    idx = 0
    while idx < len(lines):
        if lines[idx].strip() != "loop_":
            idx += 1
            continue
        idx += 1
        headers: list[str] = []
        while idx < len(lines) and lines[idx].strip().startswith("_"):
            headers.append(lines[idx].strip())
            idx += 1
        if not headers or not all(header.startswith("_atom_site.") for header in headers):
            continue
        fields = [header.split(".", 1)[1] for header in headers]
        while idx < len(lines):
            stripped = lines[idx].strip()
            if not stripped or stripped == "#":
                idx += 1
                break
            if stripped == "loop_" or stripped.startswith("data_") or stripped.startswith("_"):
                break
            values = tokenize_cif_line(stripped)
            idx += 1
            if len(values) < len(fields):
                continue
            row = dict(zip(fields, values, strict=False))
            group = row.get("group_PDB", "ATOM").upper()
            if group != "ATOM":
                continue
            atom_name = first_present(row, "auth_atom_id", "label_atom_id")
            residue_name = first_present(row, "auth_comp_id", "label_comp_id")
            residue_number = first_present(row, "auth_seq_id", "label_seq_id")
            chain_id = first_present(row, "auth_asym_id", "label_asym_id")
            if not atom_name or not residue_name or not residue_number or not chain_id:
                continue
            try:
                yield {
                    "chain_id": chain_id,
                    "residue_name": residue_name,
                    "residue_number": int(float(residue_number)),
                    "insertion_code": clean_cif_missing_value(row.get("pdbx_PDB_ins_code", "")),
                    "atom_name": atom_name,
                    "x": float(row["Cartn_x"]),
                    "y": float(row["Cartn_y"]),
                    "z": float(row["Cartn_z"]),
                }
            except (KeyError, ValueError):
                continue


def tokenize_cif_line(line: str) -> list[str]:
    return shlex.split(line, posix=True)


def first_present(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = clean_cif_missing_value(row.get(key, ""))
        if value:
            return value
    return ""


def clean_cif_missing_value(value: str) -> str:
    return "" if value in {"", ".", "?"} else value


def sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        raise ValueError("Name must contain at least one alphanumeric character.")
    if sanitized[0].isdigit():
        sanitized = f"target_{sanitized}"
    return sanitized


PDBPreprocessResult = StructurePreprocessResult
preprocess_pdb_file = preprocess_structure_file
