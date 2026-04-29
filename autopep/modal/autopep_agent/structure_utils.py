from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence


THREE_TO_ONE: dict[str, str] = {
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
}


def extract_pdb_sequences(pdb_text: str) -> dict[str, str]:
    residues_by_chain: dict[str, dict[tuple[int, str], str]] = {}

    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue

        padded = line.ljust(27)
        chain_id = padded[21].strip() or " "
        residue_number_text = padded[22:26].strip()
        insertion_code = padded[26].strip()
        residue_name = padded[17:20].strip().upper()

        if not residue_number_text.lstrip("-").isdigit():
            continue

        residue_key = (int(residue_number_text), insertion_code)
        chain_residues = residues_by_chain.setdefault(chain_id, {})
        chain_residues.setdefault(residue_key, residue_name)

    return {
        chain_id: "".join(
            THREE_TO_ONE.get(residue_name, "X")
            for _, residue_name in sorted(
                residues.items(),
                key=lambda item: item[0],
            )
        )
        for chain_id, residues in residues_by_chain.items()
    }


def build_fasta(candidates: Sequence[Mapping[str, object]]) -> str:
    fasta_parts: list[str] = []
    for candidate in candidates:
        candidate_id = str(candidate["id"]).strip()
        sequence = str(candidate["sequence"]).strip().upper()
        fasta_parts.append(f">protein|name={candidate_id}\n{sequence}\n")
    return "".join(fasta_parts)


def encode_structure_base64(structure_text: str) -> str:
    return base64.b64encode(structure_text.encode("utf-8")).decode("ascii")
