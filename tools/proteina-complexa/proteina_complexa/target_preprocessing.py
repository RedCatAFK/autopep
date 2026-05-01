from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .config import DEFAULT_BINDER_LENGTH, PREPROCESS_DIR, PYTHON_BIN, TARGET_DATA_DIR
from .preprocessing import (
    AMINO_ACID_3_TO_1,
    clean_cif_missing_value,
    format_target_input_ranges,
    infer_structure_format,
    iter_cif_atom_site_records,
    parse_chain_filter,
    preprocess_structure_text,
    sanitize_name,
    write_preprocessed_outputs,
)
from .runtime import run_command


def structure_suffix(filename: str, structure_text: str) -> str:
    suffixes = [suffix.lower() for suffix in Path(filename).suffixes]
    if suffixes and suffixes[-1] == ".gz":
        suffixes = suffixes[:-1]
    suffix = suffixes[-1] if suffixes else ""
    if suffix in {".pdb", ".cif", ".mmcif"}:
        return suffix
    return ".pdb" if infer_structure_format(structure_text) == "pdb" else ".cif"


def target_overrides(
    *,
    target_name: str,
    target_path: Path,
    target_input: str,
    hotspot_residues: list[str],
    binder_length: list[int],
    pdb_id: str,
) -> list[str]:
    hotspots = "[" + ",".join(json.dumps(value) for value in hotspot_residues) + "]"
    length_range = "[" + ",".join(str(value) for value in binder_length) + "]"
    target_input_value = json.dumps(target_input) if "," in target_input else target_input
    return [
        f"++generation.task_name={target_name}",
        f"++generation.target_dict_cfg.{target_name}.source=preprocessed_targets",
        f"++generation.target_dict_cfg.{target_name}.target_filename={target_name}",
        f"++generation.target_dict_cfg.{target_name}.target_path={target_path}",
        f"++generation.target_dict_cfg.{target_name}.target_input={target_input_value}",
        f"++generation.target_dict_cfg.{target_name}.hotspot_residues={hotspots}",
        f"++generation.target_dict_cfg.{target_name}.binder_length={length_range}",
        f"++generation.target_dict_cfg.{target_name}.pdb_id={pdb_id}",
    ]


def target_config_path(target_name: str, preprocess_dir: Path | None = None) -> Path:
    return (preprocess_dir or PREPROCESS_DIR) / f"{target_name}.target.json"


def write_target_config(
    *,
    target_name: str,
    target_path: Path,
    target_input: str,
    hotspot_residues: list[str],
    binder_length: list[int],
    pdb_id: str,
    overrides: list[str],
) -> str:
    path = target_config_path(target_name)
    payload = {
        "target_name": target_name,
        "source": "preprocessed_targets",
        "target_filename": target_name,
        "target_path": str(target_path),
        "target_input": target_input,
        "hotspot_residues": hotspot_residues,
        "binder_length": binder_length,
        "pdb_id": pdb_id,
        "hydra_overrides": overrides,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return str(path)


def write_target_pdb(
    *,
    structure_text: str,
    structure_filename: str,
    pdb_path: Path,
    chains: str | Iterable[str] | None = None,
) -> dict:
    """Write a clean Complexa target PDB preserving request-visible chain IDs.

    Complexa's target loader accepts PDB, but autopep2 usually sends RCSB
    mmCIF and target selectors based on auth chain IDs. Converting through
    atomworks/biotite can write label asym IDs instead, so a selector like
    ``E1-300`` may point at water/ligand records in the generated PDB. This
    writer keeps auth chain IDs from our parser and drops HETATM records.
    """

    records = list(
        _iter_target_atom_records(
            structure_text=structure_text,
            structure_filename=structure_filename,
            chains=chains,
        )
    )
    if not records:
        raise ValueError("No protein ATOM records matched the requested target chains.")
    if len(records) > 99999:
        raise ValueError(
            f"Target PDB would contain {len(records)} atoms, exceeding the legacy PDB atom limit."
        )

    pdb_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_format_pdb_atom_line(serial, record) for serial, record in enumerate(records, start=1)]
    lines.append("TER")
    lines.append("END")
    pdb_path.write_text("\n".join(lines) + "\n")
    residue_numbers_by_chain = _residue_numbers_by_chain(records)
    return {
        "pdb_path": str(pdb_path),
        "atom_count": len(records),
        "chain_ids": sorted({record["chain_id"] for record in records}),
        "residue_count_by_chain": {
            chain_id: len(numbers)
            for chain_id, numbers in residue_numbers_by_chain.items()
        },
        "residue_ranges_by_chain": {
            chain_id: ",".join(
                range_part[len(chain_id):]
                for range_part in format_target_input_ranges(chain_id, numbers)
            )
            for chain_id, numbers in residue_numbers_by_chain.items()
        },
        "residue_numbers_by_chain": residue_numbers_by_chain,
        "source": "auth_chain_clean_pdb_writer",
    }


def _iter_target_atom_records(
    *,
    structure_text: str,
    structure_filename: str,
    chains: str | Iterable[str] | None,
) -> Iterable[dict]:
    chain_filter = parse_chain_filter(chains)
    if structure_suffix(structure_filename, structure_text) in {".cif", ".mmcif"}:
        source_records = iter_cif_atom_site_records(structure_text)
    else:
        source_records = _iter_pdb_atom_records(structure_text)

    for record in source_records:
        chain_id = str(record["chain_id"]).strip() or "_"
        if chain_filter is not None and chain_id not in chain_filter:
            continue
        residue_name = _canonical_pdb_residue_name(str(record["residue_name"]).strip().upper())
        if residue_name not in AMINO_ACID_3_TO_1:
            continue
        alt_id = clean_cif_missing_value(str(record.get("alt_id", "")))
        if alt_id not in {"", "A"}:
            continue
        if len(chain_id) != 1:
            raise ValueError(
                f"Target chain ID {chain_id!r} cannot be represented in legacy PDB format. "
                "Pass or rename to a one-character chain ID before running Complexa."
            )
        yield {
            "atom_name": str(record["atom_name"]).strip(),
            "alt_id": alt_id,
            "residue_name": residue_name,
            "chain_id": chain_id,
            "residue_number": int(record["residue_number"]),
            "insertion_code": clean_cif_missing_value(str(record.get("insertion_code", "")))[:1],
            "x": float(record["x"]),
            "y": float(record["y"]),
            "z": float(record["z"]),
            "occupancy": float(record.get("occupancy", 1.0)),
            "b_factor": float(record.get("b_factor", 0.0)),
            "element": _infer_element(str(record.get("element", "")), str(record["atom_name"])),
        }


def _iter_pdb_atom_records(pdb_text: str) -> Iterable[dict]:
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if len(line) < 54:
            continue
        try:
            yield {
                "atom_name": line[12:16].strip(),
                "alt_id": line[16].strip(),
                "residue_name": line[17:20].strip().upper(),
                "chain_id": line[21].strip() or "_",
                "residue_number": int(line[22:26]),
                "insertion_code": line[26].strip(),
                "x": float(line[30:38]),
                "y": float(line[38:46]),
                "z": float(line[46:54]),
                "occupancy": _safe_pdb_float(line[54:60], default=1.0),
                "b_factor": _safe_pdb_float(line[60:66], default=0.0),
                "element": line[76:78].strip() if len(line) >= 78 else "",
            }
        except ValueError:
            continue


def _safe_pdb_float(value: str, *, default: float) -> float:
    try:
        return float(value.strip())
    except ValueError:
        return default


def _canonical_pdb_residue_name(residue_name: str) -> str:
    if residue_name == "MSE":
        return "MET"
    if residue_name == "SEC":
        return "CYS"
    if residue_name == "PYL":
        return "LYS"
    return residue_name


def _infer_element(element: str, atom_name: str) -> str:
    cleaned = "".join(char for char in (element or "").strip() if char.isalpha())
    if cleaned:
        return cleaned[:2].upper()
    atom_letters = "".join(char for char in atom_name.strip() if char.isalpha())
    return (atom_letters[:1] or "C").upper()


def _format_pdb_atom_name(atom_name: str, element: str) -> str:
    atom_name = atom_name.strip()
    if len(atom_name) >= 4:
        return atom_name[:4]
    if len(element.strip()) == 1 and atom_name and not atom_name[0].isdigit():
        return f" {atom_name:<3}"[:4]
    return f"{atom_name:<4}"[:4]


def _format_pdb_atom_line(serial: int, record: dict) -> str:
    return (
        f"ATOM  {serial:5d} "
        f"{_format_pdb_atom_name(record['atom_name'], record['element'])}"
        f"{record['alt_id'][:1]:1}"
        f"{record['residue_name']:>3} "
        f"{record['chain_id']:1}"
        f"{record['residue_number']:4d}"
        f"{record['insertion_code'][:1]:1}"
        f"   {record['x']:8.3f}{record['y']:8.3f}{record['z']:8.3f}"
        f"{record['occupancy']:6.2f}{record['b_factor']:6.2f}"
        f"          {record['element']:>2}  "
    )


def _residue_numbers_by_chain(records: Iterable[dict]) -> dict[str, list[int]]:
    residues_by_chain: dict[str, set[int]] = {}
    for record in records:
        residues_by_chain.setdefault(str(record["chain_id"]), set()).add(
            int(record["residue_number"])
        )
    return {
        chain_id: sorted(numbers)
        for chain_id, numbers in residues_by_chain.items()
        if numbers
    }


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


def normalize_target_input_to_available_residues(
    target_input: str,
    residue_numbers_by_chain: dict[str, list[int]],
) -> tuple[str, dict]:
    selectors = _parse_target_input(target_input)
    available_ranges = {
        chain_id: ",".join(
            range_part[len(chain_id):]
            for range_part in format_target_input_ranges(chain_id, numbers)
        )
        for chain_id, numbers in residue_numbers_by_chain.items()
    }
    corrected_parts: list[str] = []
    missing: dict[str, list[int]] = {}
    needs_correction = False
    for chain_id, start, end in selectors:
        available_numbers = residue_numbers_by_chain.get(chain_id)
        if not available_numbers:
            raise ValueError(
                f"target_input {target_input!r} uses chain {chain_id!r}, but available "
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
                f"target_input {target_input!r} selects no available residues for chain "
                f"{chain_id!r}. Available target residue ranges are {available_ranges}."
            )
        corrected_parts.extend(format_target_input_ranges(chain_id, selected_numbers))

    normalized = ",".join(corrected_parts) if needs_correction else ",".join(
        _format_target_input_selector(chain_id, start, end)
        for chain_id, start, end in selectors
    )
    return normalized, {
        "status": "corrected" if needs_correction else "valid",
        "requested": target_input,
        "target_input": normalized,
        "missing_residues": missing,
        "available_ranges": available_ranges,
    }


def _format_target_input_selector(chain_id: str, start: int, end: int) -> str:
    return f"{chain_id}{start}-{end}"


def validate_hotspot_residues(
    hotspot_residues: list[str],
    residue_numbers_by_chain: dict[str, list[int]],
) -> None:
    available_ranges = {
        chain_id: ",".join(
            range_part[len(chain_id):]
            for range_part in format_target_input_ranges(chain_id, numbers)
        )
        for chain_id, numbers in residue_numbers_by_chain.items()
    }
    for hotspot in hotspot_residues:
        match = re.fullmatch(r"([A-Za-z])(\d+)", str(hotspot).strip())
        if not match:
            raise ValueError(
                f"hotspot_residue {hotspot!r} is not valid. Use values like 'A41'."
            )
        chain_id = match.group(1).upper()
        number = int(match.group(2))
        if number not in set(residue_numbers_by_chain.get(chain_id, [])):
            raise ValueError(
                f"hotspot_residue {hotspot!r} is not present in the target. "
                f"Available target residue ranges are {available_ranges}."
            )


def inspect_target_tensors(
    *,
    pdb_path: Path,
    target_input: str,
    hotspot_residues: list[str],
) -> dict:
    script = f"""
from pathlib import Path

import json
from proteinfoundation.utils.pdb_utils import load_target_from_pdb

pdb_path = Path({str(pdb_path)!r})
target_input = {target_input!r}
hotspot_residues = {hotspot_residues!r}
target_mask, target_structure, target_residue_type, target_hotspots_mask, target_chain = load_target_from_pdb(
    target_input,
    str(pdb_path),
    hotspot_residues,
)
seq_target_mask = target_mask.sum(dim=-1).bool()
print(json.dumps({{
    "x_target_shape": list(target_structure.shape),
    "target_mask_shape": list(target_mask.shape),
    "seq_target_shape": list(target_residue_type.shape),
    "seq_target_mask_shape": list(seq_target_mask.shape),
    "target_hotspot_mask_shape": list(target_hotspots_mask.shape),
    "target_chain_shape": list(target_chain.shape),
    "target_residue_count": int(target_structure.shape[0]),
    "target_atom37_count": int(target_mask.sum().item()),
    "target_hotspot_count": int(target_hotspots_mask.sum().item()),
}}))
"""
    output = run_command([str(PYTHON_BIN), "-c", script])
    return json.loads(output.strip().splitlines()[-1])


def preprocess_target_structure(
    structure_text: str,
    structure_filename: str,
    target_name: str | None = None,
    target_input: str | None = None,
    chains: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length: list[int] | None = None,
) -> dict:
    """Convert one request target into the Complexa target PDB and override set."""
    from .modal_resources import data_volume, model_volume

    model_volume.reload()
    safe_target_name = sanitize_name(target_name or Path(structure_filename).stem)
    effective_hotspots = hotspot_residues or []
    result = preprocess_structure_text(
        structure_text,
        structure_id=safe_target_name,
        chains=chains,
        target_input=target_input,
    )

    PREPROCESS_DIR.mkdir(parents=True, exist_ok=True)
    structure_path = PREPROCESS_DIR / f"{safe_target_name}{structure_suffix(structure_filename, structure_text)}"
    structure_path.write_text(structure_text)

    pdb_path = TARGET_DATA_DIR / f"{safe_target_name}.pdb"
    pdb_info = write_target_pdb(
        structure_text=structure_text,
        structure_filename=structure_filename,
        pdb_path=pdb_path,
        chains=chains,
    )
    normalized_target_input, target_input_guard = normalize_target_input_to_available_residues(
        result.target_input,
        pdb_info["residue_numbers_by_chain"],
    )
    validate_hotspot_residues(effective_hotspots, pdb_info["residue_numbers_by_chain"])
    if normalized_target_input != result.target_input:
        result = replace(result, target_input=normalized_target_input)
    outputs = write_preprocessed_outputs(result, PREPROCESS_DIR)
    target_tensor_info = inspect_target_tensors(
        pdb_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=effective_hotspots,
    )

    length_range = binder_length or DEFAULT_BINDER_LENGTH
    if len(length_range) != 2:
        raise ValueError("binder_length must contain [min_length, max_length]")
    normalized_binder_length = [int(length_range[0]), int(length_range[1])]

    overrides = target_overrides(
        target_name=safe_target_name,
        target_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=effective_hotspots,
        binder_length=normalized_binder_length,
        pdb_id=safe_target_name,
    )
    target_config_json_path = write_target_config(
        target_name=safe_target_name,
        target_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=effective_hotspots,
        binder_length=normalized_binder_length,
        pdb_id=safe_target_name,
        overrides=overrides,
    )
    data_volume.commit()
    return {
        "target_name": safe_target_name,
        "length": result.length,
        "parsed_length": result.length,
        "target_residue_count": target_tensor_info["target_residue_count"],
        "sequence": result.sequence,
        "chain_sequences": result.chain_sequences,
        "target_input": result.target_input,
        "structure_path": str(structure_path),
        "pdb_path": str(pdb_path),
        "feature_json_path": outputs["json"],
        "target_config_json_path": target_config_json_path,
        "fasta_path": outputs["fasta"],
        "pdb_info": pdb_info,
        "target_input_guard": target_input_guard,
        "target_tensor_info": target_tensor_info,
        "hydra_overrides": overrides,
    }
