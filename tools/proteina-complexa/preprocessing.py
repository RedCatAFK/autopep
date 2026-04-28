from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


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
    # Common PDB substitutions that are normally interpreted as canonical AAs.
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
class PDBPreprocessResult:
    pdb_id: str
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
            "pdb_id": self.pdb_id,
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


def preprocess_pdb_text(
    pdb_text: str,
    *,
    pdb_id: str = "input",
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
) -> PDBPreprocessResult:
    chain_filter = parse_chain_filter(chains)
    residues_by_key: dict[tuple[str, int, str], dict] = {}
    residue_order: list[tuple[str, int, str]] = []

    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 54:
            continue
        chain_id = line[21].strip() or "_"
        if chain_filter is not None and chain_id not in chain_filter:
            continue
        residue_name = line[17:20].strip().upper()
        amino_acid = AMINO_ACID_3_TO_1.get(residue_name, "X")
        try:
            residue_number = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        insertion_code = line[26].strip()
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
        if line[12:16].strip() == "CA":
            residues_by_key[key]["ca_coord_angstrom"] = (x, y, z)

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
        raise ValueError("No protein residues were found in the PDB ATOM records.")

    chain_sequences: dict[str, list[str]] = {}
    for residue in residues:
        chain_sequences.setdefault(residue.chain_id, []).append(residue.amino_acid)

    result_chain_sequences = {chain_id: "".join(seq) for chain_id, seq in chain_sequences.items()}
    sequence = ":".join(result_chain_sequences[chain_id] for chain_id in result_chain_sequences)
    effective_target_input = target_input or infer_target_input(residues)
    return PDBPreprocessResult(
        pdb_id=pdb_id,
        sequence=sequence,
        chain_sequences=result_chain_sequences,
        target_input=effective_target_input,
        residues=residues,
    )


def preprocess_pdb_file(
    pdb_path: Path | str,
    *,
    chains: str | Iterable[str] | None = None,
    target_input: str | None = None,
) -> PDBPreprocessResult:
    path = Path(pdb_path)
    return preprocess_pdb_text(
        path.read_text(),
        pdb_id=path.stem,
        chains=chains,
        target_input=target_input,
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
                "Cannot infer target_input for PDB insertion codes. "
                "Pass target_input explicitly, for example 'A1-150'."
            )
        ranges.append(f"{chain_id}{chain_residues[0].residue_number}-{chain_residues[-1].residue_number}")
    return ",".join(ranges)


def write_preprocessed_outputs(result: PDBPreprocessResult, output_dir: Path | str) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = sanitize_name(result.pdb_id)
    json_path = output_path / f"{stem}.preprocess.json"
    fasta_path = output_path / f"{stem}.fasta"
    json_path.write_text(json.dumps(result.to_json_dict(), indent=2) + "\n")
    fasta_lines = [f">{result.pdb_id}|{chain_id}\n{sequence}\n" for chain_id, sequence in result.chain_sequences.items()]
    fasta_path.write_text("".join(fasta_lines))
    return {"json": str(json_path), "fasta": str(fasta_path)}


def sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        raise ValueError("Name must contain at least one alphanumeric character.")
    if sanitized[0].isdigit():
        sanitized = f"target_{sanitized}"
    return sanitized
