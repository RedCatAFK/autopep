from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable

import modal

from preprocessing import preprocess_pdb_text, sanitize_name, write_preprocessed_outputs


APP_NAME = "proteina-complexa"
MODEL_REPO_ID = "nvidia/NV-Proteina-Complexa-Protein-Target-160M-v1"
MODEL_SUBDIR = "protein-target-160m"
MODEL_DIR = Path("/models") / MODEL_SUBDIR
COMPLEXA_ROOT = Path("/workspace/protein-foundation-models")
COMPLEXA_BIN = Path("/workspace/.venv/bin/complexa")
PYTHON_BIN = Path("/workspace/.venv/bin/python")
PREPROCESS_DIR = Path("/data/preprocessed_targets")

DEFAULT_PIPELINE_CONFIG = "configs/search_binder_local_pipeline.yaml"
DEFAULT_GPU = "A100-80GB"

model_volume = modal.Volume.from_name("proteina-complexa-models", create_if_missing=True)
data_volume = modal.Volume.from_name("proteina-complexa-data", create_if_missing=True)
runs_volume = modal.Volume.from_name("proteina-complexa-runs", create_if_missing=True)

hf_secret = modal.Secret.from_name("huggingface-secret")

app = modal.App(APP_NAME)


image = (
    modal.Image.from_registry("nvcr.io/nvidia/pytorch:24.08-py3")
    .apt_install("git", "rsync", "curl", "libxrender1", "libxext6")
    .run_commands(
        "git clone --depth 1 --branch dev https://github.com/NVIDIA-Digital-Bio/Proteina-Complexa "
        f"{COMPLEXA_ROOT}",
        f"cd {COMPLEXA_ROOT} && bash env/build_uv_env.sh --root /workspace/",
        f"{PYTHON_BIN} -m pip install --upgrade 'huggingface_hub[hf_transfer]'",
    )
    .env(
        {
            "AF2_DIR": f"{COMPLEXA_ROOT}/community_models/ckpts/AF2",
            "COMPLEXA_ROOT": str(COMPLEXA_ROOT),
            "DATA_PATH": "/data",
            "DSSP_EXEC": "/usr/local/bin/dssp",
            "FOLDSEEK_EXEC": "/workspace/.venv/bin/foldseek",
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "LOCAL_CODE_PATH": str(COMPLEXA_ROOT),
            "MMSEQS_EXEC": "/workspace/.venv/bin/mmseqs",
            "PYTHONPATH": f"{COMPLEXA_ROOT}/src",
            "RF3_CKPT_PATH": f"{COMPLEXA_ROOT}/community_models/ckpts/RF3/rf3_foundry_01_24_latest_remapped.ckpt",
            "RF3_EXEC_PATH": "/workspace/.venv/bin/rf3",
            "SC_EXEC": "/usr/local/bin/sc",
        }
    )
    .workdir(str(COMPLEXA_ROOT))
)


def _run(
    command: list[str],
    *,
    cwd: Path = COMPLEXA_ROOT,
    env: dict[str, str] | None = None,
) -> str:
    print("+", shlex.join(command), flush=True)
    completed = subprocess.run(
        command,
        check=True,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout, flush=True)
    return completed.stdout


def _checkpoint_overrides() -> list[str]:
    return [
        f"++ckpt_path={MODEL_DIR}",
        "++ckpt_name=complexa.ckpt",
        f"++autoencoder_ckpt_path={MODEL_DIR / 'complexa_ae.ckpt'}",
    ]


def _config_path(pipeline_config: str) -> str:
    path = Path(pipeline_config)
    if path.is_absolute():
        return str(path)
    return str(COMPLEXA_ROOT / path)


def _local_weight_files() -> dict[str, str]:
    files = {}
    for filename in ("complexa.ckpt", "complexa_ae.ckpt"):
        path = MODEL_DIR / filename
        if path.exists():
            files[str(path)] = f"{path.stat().st_size / (1024 ** 3):.2f} GiB"
    return files


def _normalize_overrides(overrides: Iterable[str] | None) -> list[str]:
    return [override for override in (overrides or []) if override]


def _parse_json_list(value: str, *, default: list | None = None) -> list:
    if not value:
        return list(default or [])
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON list")
    return parsed


def _target_overrides(
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
        f"++generation.target_dict_cfg.{target_name}.target_path={target_path}",
        f"++generation.target_dict_cfg.{target_name}.target_input={target_input_value}",
        f"++generation.target_dict_cfg.{target_name}.hotspot_residues={hotspots}",
        f"++generation.target_dict_cfg.{target_name}.binder_length={length_range}",
        f"++generation.target_dict_cfg.{target_name}.pdb_id={pdb_id}",
    ]


def _encode_pdb_latents(
    *,
    pdb_path: Path,
    latent_path: Path,
    target_input: str,
) -> dict:
    script = f"""
from pathlib import Path

import json
import torch
from atomworks.io.utils.io_utils import load_any
from atomworks.io.utils.selection import AtomSelectionStack
from atomworks.ml.encoding_definitions import AF2_ATOM37_ENCODING
from atomworks.ml.transforms.encoding import atom_array_to_encoding
from proteinfoundation.partial_autoencoder.autoencoder import AutoEncoder
from proteinfoundation.utils.coors_utils import ang_to_nm

pdb_path = Path({str(pdb_path)!r})
latent_path = Path({str(latent_path)!r})
target_input = {target_input!r}

struct = load_any(str(pdb_path), model=1)
selection = AtomSelectionStack.from_contig(target_input)
struct = struct[selection.get_mask(struct)]
if not hasattr(struct, "occupancy"):
    import numpy as np
    struct.set_annotation("occupancy", np.ones(len(struct), dtype=np.float32))

encoded = atom_array_to_encoding(
    struct,
    AF2_ATOM37_ENCODING,
    default_coord=0.0,
)
coords_nm = ang_to_nm(torch.from_numpy(encoded["xyz"]).float()).unsqueeze(0)
atom_mask = torch.from_numpy(encoded["mask"]).bool().unsqueeze(0)
coord_mask = atom_mask.unsqueeze(-1).expand(*atom_mask.shape, 3)
residue_type = torch.from_numpy(encoded["seq"]).long().unsqueeze(0)
residue_mask = atom_mask[..., 1]

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
batch = {{
    "coords_nm": coords_nm.to(device),
    "coords": (coords_nm * 10.0).to(device),
    "residue_type": residue_type.to(device),
    "mask_dict": {{
        "coords": coord_mask.to(device),
        "residue_type": residue_mask.to(device),
    }},
    "mask": residue_mask.to(device),
}}

model = AutoEncoder.load_from_checkpoint({str(MODEL_DIR / "complexa_ae.ckpt")!r})
model = model.to(device).eval()
with torch.no_grad():
    encoded_latents = model.encode(batch)

payload = {{
    "z_latent": encoded_latents["z_latent"].detach().cpu(),
    "mean": encoded_latents["mean"].detach().cpu(),
    "log_scale": encoded_latents["log_scale"].detach().cpu(),
    "ca_coords_nm": coords_nm[:, :, 1, :].detach().cpu(),
    "coords_nm": coords_nm.detach().cpu(),
    "atom_mask": atom_mask.detach().cpu(),
    "residue_mask": residue_mask.detach().cpu(),
    "residue_type": residue_type.detach().cpu(),
    "target_input": target_input,
    "pdb_path": str(pdb_path),
}}
latent_path.parent.mkdir(parents=True, exist_ok=True)
torch.save(payload, latent_path)
print(json.dumps({{
    "latent_path": str(latent_path),
    "z_latent_shape": list(payload["z_latent"].shape),
    "ca_coords_nm_shape": list(payload["ca_coords_nm"].shape),
}}))
"""
    output = _run([str(PYTHON_BIN), "-c", script])
    return json.loads(output.strip().splitlines()[-1])


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume,
    },
    timeout=60 * 60,
)
def preprocess_pdb(
    pdb_text: str,
    pdb_filename: str,
    target_name: str | None = None,
    target_input: str | None = None,
    chains: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length: list[int] | None = None,
    encode_latents: bool = True,
) -> dict:
    """Convert a PDB into sequence/features and optional Complexa autoencoder latents."""
    model_volume.reload()
    safe_target_name = sanitize_name(target_name or Path(pdb_filename).stem)
    result = preprocess_pdb_text(
        pdb_text,
        pdb_id=safe_target_name,
        chains=chains,
        target_input=target_input,
    )
    PREPROCESS_DIR.mkdir(parents=True, exist_ok=True)
    pdb_path = PREPROCESS_DIR / f"{safe_target_name}.pdb"
    pdb_path.write_text(pdb_text)
    outputs = write_preprocessed_outputs(result, PREPROCESS_DIR)

    latent_info = None
    if encode_latents:
        latent_path = PREPROCESS_DIR / f"{safe_target_name}.latents.pt"
        latent_info = _encode_pdb_latents(
            pdb_path=pdb_path,
            latent_path=latent_path,
            target_input=result.target_input,
        )

    length_range = binder_length or [60, 120]
    if len(length_range) != 2:
        raise ValueError("binder_length must contain [min_length, max_length]")

    overrides = _target_overrides(
        target_name=safe_target_name,
        target_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=hotspot_residues or [],
        binder_length=[int(length_range[0]), int(length_range[1])],
        pdb_id=safe_target_name,
    )
    data_volume.commit()
    return {
        "target_name": safe_target_name,
        "length": result.length,
        "sequence": result.sequence,
        "chain_sequences": result.chain_sequences,
        "target_input": result.target_input,
        "pdb_path": str(pdb_path),
        "feature_json_path": outputs["json"],
        "fasta_path": outputs["fasta"],
        "latent_info": latent_info,
        "hydra_overrides": overrides,
    }


@app.function(
    image=image,
    secrets=[hf_secret],
    volumes={"/models": model_volume},
    timeout=60 * 60,
)
def download_weights(force: bool = False) -> dict[str, str]:
    """Download the HF checkpoint pair into the persistent model Volume."""
    script = f"""
from huggingface_hub import hf_hub_download
from pathlib import Path

repo_id = {MODEL_REPO_ID!r}
target_dir = Path({str(MODEL_DIR)!r})
target_dir.mkdir(parents=True, exist_ok=True)
files = ["complexa.ckpt", "complexa_ae.ckpt"]

for filename in files:
    destination = target_dir / filename
    if destination.exists() and not {force!r}:
        print(f"already present: {{destination}}")
        continue
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        force_download={force!r},
    )
    print(f"downloaded {{filename}} -> {{path}}")
    """
    _run([str(PYTHON_BIN), "-c", script])
    model_volume.commit()
    return _local_weight_files()


@app.function(
    image=image,
    volumes={"/models": model_volume.read_only()},
    timeout=10 * 60,
)
def list_weights() -> dict[str, str]:
    model_volume.reload()
    return _local_weight_files()


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume.read_only(),
        "/runs": runs_volume,
    },
    timeout=30 * 60,
)
def validate(
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: list[str] | None = None,
) -> str:
    """Resolve a Complexa Hydra pipeline config before launching expensive jobs."""
    model_volume.reload()
    command = [
        str(COMPLEXA_BIN),
        "validate",
        "design",
        _config_path(pipeline_config),
        *_checkpoint_overrides(),
        *_normalize_overrides(overrides),
    ]
    return _run(command)


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume.read_only(),
        "/runs": runs_volume,
    },
    timeout=12 * 60 * 60,
)
def design_binder(
    task_name: str,
    run_name: str,
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: list[str] | None = None,
) -> dict[str, str]:
    """Run a single protein-target binder design job on one Modal GPU."""
    model_volume.reload()
    run_dir = Path("/runs") / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(COMPLEXA_BIN),
        "design",
        _config_path(pipeline_config),
        *_checkpoint_overrides(),
        f"++run_name={run_name}",
        f"++generation.task_name={task_name}",
        *_normalize_overrides(overrides),
    ]
    output = _run(command, cwd=run_dir)
    runs_volume.commit()
    return {"run_name": run_name, "task_name": task_name, "log_tail": output[-4000:]}


@app.function(
    image=image,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume.read_only(),
        "/runs": runs_volume.read_only(),
    },
    timeout=10 * 60,
)
def status(pipeline_config: str = DEFAULT_PIPELINE_CONFIG) -> str:
    """Run Complexa's status command against the mounted run Volume."""
    model_volume.reload()
    runs_volume.reload()
    return _run([str(COMPLEXA_BIN), "status", _config_path(pipeline_config)], cwd=Path("/runs"))


@app.local_entrypoint()
def main(
    action: str = "list-weights",
    task_name: str = "02_PDL1",
    run_name: str = "pdl1_modal_smoke",
    overrides_json: str = "[]",
    jobs_json: str = "",
    pdb_path: str = "",
    target_name: str = "",
    target_input: str = "",
    chains: str = "",
    hotspot_residues_json: str = "[]",
    binder_length_json: str = "[60, 120]",
    encode_latents: bool = True,
):
    overrides = json.loads(overrides_json)
    if action == "download-weights":
        print(download_weights.remote())
    elif action == "list-weights":
        print(list_weights.remote())
    elif action == "validate":
        print(validate.remote(overrides=overrides))
    elif action == "design":
        print(design_binder.remote(task_name=task_name, run_name=run_name, overrides=overrides))
    elif action == "preprocess-pdb":
        if not pdb_path:
            raise ValueError("--pdb-path is required for --action preprocess-pdb")
        path = Path(pdb_path)
        result = preprocess_pdb.remote(
            path.read_text(),
            path.name,
            target_name or None,
            target_input or None,
            chains or None,
            _parse_json_list(hotspot_residues_json),
            _parse_json_list(binder_length_json, default=[60, 120]),
            encode_latents,
        )
        print(json.dumps(result, indent=2))
    elif action == "design-pdb":
        if not pdb_path:
            raise ValueError("--pdb-path is required for --action design-pdb")
        path = Path(pdb_path)
        preprocessed = preprocess_pdb.remote(
            path.read_text(),
            path.name,
            target_name or None,
            target_input or None,
            chains or None,
            _parse_json_list(hotspot_residues_json),
            _parse_json_list(binder_length_json, default=[60, 120]),
            encode_latents,
        )
        target_overrides = [
            override
            for override in preprocessed["hydra_overrides"]
            if not override.startswith("++generation.task_name=")
        ]
        design_overrides = [*target_overrides, *_normalize_overrides(overrides)]
        print(
            design_binder.remote(
                task_name=preprocessed["target_name"],
                run_name=run_name,
                overrides=design_overrides,
            )
        )
    elif action == "batch":
        if not jobs_json:
            raise ValueError("--jobs-json is required for --action batch")
        jobs = json.loads(Path(jobs_json).read_text())
        calls = [
            (
                str(job["task_name"]),
                str(job["run_name"]),
                str(job.get("pipeline_config", DEFAULT_PIPELINE_CONFIG)),
                list(job.get("overrides", [])),
            )
            for job in jobs
        ]
        for result in design_binder.starmap(calls):
            print(json.dumps(result))
    elif action == "status":
        print(status.remote())
    else:
        raise ValueError(f"unknown action: {action}")
