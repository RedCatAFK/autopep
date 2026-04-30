from __future__ import annotations

import base64
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path


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


def extract_pdb_chain_order(pdb_text: str) -> list[str]:
    chain_order: list[str] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        chain_id = line.ljust(22)[21].strip()
        if chain_id and chain_id not in chain_order:
            chain_order.append(chain_id)
    return chain_order


def infer_structure_format(filename: str | None, structure_text: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".cif", ".mmcif"}:
        return "cif"
    if suffix == ".pdb":
        return "pdb"
    for line in structure_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data_") or stripped == "loop_" or stripped.startswith("_atom_site."):
            return "cif"
        if line.startswith(("ATOM", "HETATM", "HEADER")):
            return "pdb"
    return "cif"


def extract_cif_chain_order(cif_text: str) -> list[str]:
    chain_order: list[str] = []
    lines = cif_text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue

        index += 1
        headers: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("_"):
            headers.append(lines[index].strip())
            index += 1
        if not headers or not all(header.startswith("_atom_site.") for header in headers):
            continue

        fields = [header.split(".", 1)[1] for header in headers]
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped == "#":
                index += 1
                break
            if stripped == "loop_" or stripped.startswith(("data_", "_")):
                break
            try:
                values = shlex.split(stripped, posix=True)
            except ValueError:
                index += 1
                continue
            index += 1
            if len(values) < len(fields):
                continue
            row = dict(zip(fields, values, strict=False))
            group = _clean_cif_value(row.get("group_PDB")).upper() or "ATOM"
            if group not in {"ATOM", "HETATM"}:
                continue
            chain_id = _clean_cif_value(row.get("auth_asym_id")) or _clean_cif_value(
                row.get("label_asym_id")
            )
            if chain_id and chain_id not in chain_order:
                chain_order.append(chain_id)
    return chain_order


def extract_structure_chain_order(
    structure_text: str,
    *,
    filename: str | None = None,
) -> tuple[str, list[str]]:
    structure_format = infer_structure_format(filename, structure_text)
    if structure_format == "cif":
        return structure_format, extract_cif_chain_order(structure_text)
    return structure_format, extract_pdb_chain_order(structure_text)


def _clean_cif_value(value: str | None) -> str:
    text = (value or "").strip()
    return "" if text in {"", ".", "?"} else text


def build_fasta(candidates: Sequence[Mapping[str, object]]) -> str:
    fasta_parts: list[str] = []
    for candidate in candidates:
        candidate_id = str(candidate["id"]).strip()
        sequence = str(candidate["sequence"]).strip().upper()
        fasta_parts.append(_fasta_record(candidate_id, sequence))
    return "".join(fasta_parts)


def build_complex_fasta(
    *,
    target_id: str,
    target_sequence: str,
    binder_id: str,
    binder_sequence: str,
) -> str:
    return (
        _fasta_record(str(target_id).strip(), str(target_sequence).strip().upper())
        + _fasta_record(str(binder_id).strip(), str(binder_sequence).strip().upper())
    )


def _fasta_record(name: str, sequence: str) -> str:
    return f">protein|name={name}\n{sequence}\n"


def encode_structure_base64(structure_text: str) -> str:
    return base64.b64encode(structure_text.encode("utf-8")).decode("ascii")
