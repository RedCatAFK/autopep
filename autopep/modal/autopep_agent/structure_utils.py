from __future__ import annotations

import base64
import re
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


def extract_pdb_residue_numbers(pdb_text: str) -> dict[str, list[int]]:
    residues_by_chain: dict[str, set[int]] = {}

    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue

        padded = line.ljust(27)
        chain_id = padded[21].strip() or " "
        residue_number_text = padded[22:26].strip()
        residue_name = padded[17:20].strip().upper()

        if residue_name not in THREE_TO_ONE or not residue_number_text.lstrip("-").isdigit():
            continue

        residues_by_chain.setdefault(chain_id, set()).add(int(residue_number_text))

    return {
        chain_id: sorted(numbers)
        for chain_id, numbers in residues_by_chain.items()
        if numbers
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
    for row in iter_cif_atom_site_rows(cif_text):
        chain_id = _clean_cif_value(row.get("auth_asym_id")) or _clean_cif_value(
            row.get("label_asym_id")
        )
        if chain_id and chain_id not in chain_order:
            chain_order.append(chain_id)
    return chain_order


def extract_cif_residue_numbers(cif_text: str) -> dict[str, list[int]]:
    residues_by_chain: dict[str, set[int]] = {}
    for row in iter_cif_atom_site_rows(cif_text):
        residue_name = (
            _clean_cif_value(row.get("auth_comp_id"))
            or _clean_cif_value(row.get("label_comp_id"))
        ).upper()
        residue_number = (
            _clean_cif_value(row.get("auth_seq_id"))
            or _clean_cif_value(row.get("label_seq_id"))
        )
        chain_id = _clean_cif_value(row.get("auth_asym_id")) or _clean_cif_value(
            row.get("label_asym_id")
        )
        if residue_name not in THREE_TO_ONE or not residue_number or not chain_id:
            continue
        try:
            residues_by_chain.setdefault(chain_id, set()).add(int(float(residue_number)))
        except ValueError:
            continue

    return {
        chain_id: sorted(numbers)
        for chain_id, numbers in residues_by_chain.items()
        if numbers
    }


def iter_cif_atom_site_rows(cif_text: str):
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
            yield row


def extract_structure_chain_order(
    structure_text: str,
    *,
    filename: str | None = None,
) -> tuple[str, list[str]]:
    structure_format = infer_structure_format(filename, structure_text)
    if structure_format == "cif":
        return structure_format, extract_cif_chain_order(structure_text)
    return structure_format, extract_pdb_chain_order(structure_text)


def extract_structure_residue_numbers(
    structure_text: str,
    *,
    filename: str | None = None,
) -> tuple[str, dict[str, list[int]]]:
    structure_format = infer_structure_format(filename, structure_text)
    if structure_format == "cif":
        return structure_format, extract_cif_residue_numbers(structure_text)
    return structure_format, extract_pdb_residue_numbers(structure_text)


def infer_target_input_from_structure(
    structure_text: str,
    *,
    filename: str | None = None,
    chains: Sequence[str] | None = None,
) -> str | None:
    _, residues_by_chain = extract_structure_residue_numbers(
        structure_text,
        filename=filename,
    )
    if not residues_by_chain:
        return None
    selected_chains = [
        chain for chain in (chains or residues_by_chain.keys()) if chain in residues_by_chain
    ]
    parts: list[str] = []
    for chain_id in selected_chains:
        parts.extend(_format_chain_ranges(chain_id, residues_by_chain[chain_id]))
    return ",".join(parts) or None


def normalize_target_input_for_structure(
    target_input: str | None,
    structure_text: str,
    *,
    filename: str | None = None,
    default_first_chain_only: bool = False,
) -> tuple[str | None, dict[str, object]]:
    _, residues_by_chain = extract_structure_residue_numbers(
        structure_text,
        filename=filename,
    )
    if not residues_by_chain:
        return target_input, {
            "status": "unvalidated",
            "reason": "no protein residues found",
            "available_ranges": {},
        }

    available_ranges = _available_ranges(residues_by_chain)
    requested = (target_input or "").strip()
    if not requested:
        chains = [next(iter(residues_by_chain))] if default_first_chain_only else None
        inferred = infer_target_input_from_structure(
            structure_text,
            filename=filename,
            chains=chains,
        )
        return inferred, {
            "status": "inferred",
            "available_ranges": available_ranges,
            "target_input": inferred,
        }

    selectors = _parse_target_input(requested)
    corrected_parts: list[str] = []
    missing: dict[str, list[int]] = {}
    needs_correction = False
    for chain_id, start, end in selectors:
        available_numbers = residues_by_chain.get(chain_id)
        if not available_numbers:
            raise ValueError(
                f"target_input {requested!r} uses chain {chain_id!r}, but available "
                f"target residue ranges are {available_ranges}."
            )
        available_set = set(available_numbers)
        selected_numbers = [number for number in available_numbers if start <= number <= end]
        missing_numbers = [
            number for number in range(start, end + 1) if number not in available_set
        ]
        if missing_numbers:
            needs_correction = True
            missing.setdefault(chain_id, []).extend(missing_numbers[:12])
        if not selected_numbers:
            raise ValueError(
                f"target_input {requested!r} selects no available residues for chain "
                f"{chain_id!r}. Available target residue ranges are {available_ranges}."
            )
        corrected_parts.extend(_format_chain_ranges(chain_id, selected_numbers))

    normalized = ",".join(corrected_parts) if needs_correction else ",".join(
        _format_selector(chain_id, start, end) for chain_id, start, end in selectors
    )
    return normalized, {
        "status": "corrected" if needs_correction else "valid",
        "requested": requested,
        "target_input": normalized,
        "missing_residues": missing,
        "available_ranges": available_ranges,
    }


def validate_hotspot_residues_for_structure(
    hotspot_residues: Sequence[str],
    structure_text: str,
    *,
    filename: str | None = None,
) -> list[str]:
    _, residues_by_chain = extract_structure_residue_numbers(
        structure_text,
        filename=filename,
    )
    normalized = normalize_hotspot_residues(hotspot_residues)
    if not residues_by_chain:
        return normalized

    available_ranges = _available_ranges(residues_by_chain)
    for hotspot in normalized:
        chain_id, number = _parse_hotspot(hotspot)
        if number not in set(residues_by_chain.get(chain_id, [])):
            raise ValueError(
                f"hotspot_residue {hotspot!r} is not present in the target. "
                f"Available target residue ranges are {available_ranges}."
            )
    return normalized


def normalize_hotspot_residues(hotspot_residues: Sequence[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in hotspot_residues or []:
        value = str(raw).strip()
        if not value:
            continue
        direct = re.fullmatch(r"([A-Za-z])(\d+)", value)
        if direct:
            normalized.append(f"{direct.group(1).upper()}{direct.group(2)}")
            continue
        named = re.fullmatch(r"([A-Za-z]):?[A-Za-z]{3}(\d+)", value)
        if named:
            normalized.append(f"{named.group(1).upper()}{named.group(2)}")
            continue
        colon_number = re.fullmatch(r"([A-Za-z]):(\d+)", value)
        if colon_number:
            normalized.append(f"{colon_number.group(1).upper()}{colon_number.group(2)}")
            continue
        raise ValueError(
            "hotspot_residues must use Proteina format: chain ID immediately "
            "followed by residue number, e.g. 'A41' or 'A145'."
        )
    return normalized


def _clean_cif_value(value: str | None) -> str:
    text = (value or "").strip()
    return "" if text in {"", ".", "?"} else text


def _available_ranges(residues_by_chain: Mapping[str, Sequence[int]]) -> dict[str, str]:
    return {
        chain_id: ",".join(
            part[len(chain_id):]
            for part in _format_chain_ranges(chain_id, numbers)
        )
        for chain_id, numbers in residues_by_chain.items()
    }


def _format_chain_ranges(chain_id: str, numbers: Sequence[int]) -> list[str]:
    unique_numbers = sorted(set(numbers))
    if not unique_numbers:
        return []
    ranges: list[str] = []
    start = previous = unique_numbers[0]
    for number in unique_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(_format_selector(chain_id, start, previous))
        start = previous = number
    ranges.append(_format_selector(chain_id, start, previous))
    return ranges


def _format_selector(chain_id: str, start: int, end: int) -> str:
    return f"{chain_id}{start}-{end}"


def _parse_target_input(target_input: str) -> list[tuple[str, int, int]]:
    selectors: list[tuple[str, int, int]] = []
    for raw_part in target_input.split(","):
        part = raw_part.strip()
        match = re.fullmatch(r"([A-Za-z])(-?\d+)(?:-(-?\d+))?", part)
        if not match:
            raise ValueError(
                f"target_input {target_input!r} is not supported. Use comma-separated "
                "ranges like 'A1-109,A111-306'."
            )
        chain_id = match.group(1).upper()
        start = int(match.group(2))
        end = int(match.group(3) or match.group(2))
        if end < start:
            raise ValueError(f"target_input range {part!r} has end before start.")
        selectors.append((chain_id, start, end))
    if not selectors:
        raise ValueError("target_input must select at least one residue.")
    return selectors


def _parse_hotspot(hotspot: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Za-z])(\d+)", hotspot)
    if not match:
        raise ValueError(f"hotspot_residue {hotspot!r} is not valid.")
    return match.group(1).upper(), int(match.group(2))


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
