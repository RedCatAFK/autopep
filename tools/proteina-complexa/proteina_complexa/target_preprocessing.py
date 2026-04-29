from __future__ import annotations

import json
from pathlib import Path

from .config import DEFAULT_BINDER_LENGTH, PREPROCESS_DIR, PYTHON_BIN, TARGET_DATA_DIR
from .preprocessing import (
    infer_structure_format,
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
    structure_path: Path,
    pdb_path: Path,
) -> dict:
    script = f"""
from pathlib import Path

import json
import numpy as np
from atomworks.io.utils.io_utils import load_any
from biotite.structure.io import save_structure

structure_path = Path({str(structure_path)!r})
pdb_path = Path({str(pdb_path)!r})
loaded = load_any(str(structure_path), model=1)
struct = loaded[0] if isinstance(loaded, (list, tuple)) else loaded
if not hasattr(struct, "occupancy"):
    struct.set_annotation("occupancy", np.ones(len(struct), dtype=np.float32))
pdb_path.parent.mkdir(parents=True, exist_ok=True)
save_structure(str(pdb_path), struct)
print(json.dumps({{
    "pdb_path": str(pdb_path),
    "atom_count": int(len(struct)),
    "chain_ids": sorted({{str(chain_id) for chain_id in struct.chain_id.tolist()}}),
}}))
"""
    output = run_command([str(PYTHON_BIN), "-c", script])
    return json.loads(output.strip().splitlines()[-1])


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
    outputs = write_preprocessed_outputs(result, PREPROCESS_DIR)

    pdb_path = TARGET_DATA_DIR / f"{safe_target_name}.pdb"
    pdb_info = write_target_pdb(structure_path=structure_path, pdb_path=pdb_path)
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
        "target_tensor_info": target_tensor_info,
        "hydra_overrides": overrides,
    }
