from __future__ import annotations

import base64
import gzip
import hmac
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Iterable

import modal

from api_contract import DesignPayload, normalize_design_payload
from preprocessing import (
    infer_structure_format,
    preprocess_structure_text,
    sanitize_name,
    write_preprocessed_outputs,
)
from proteina_warm_start import warm_start_support_status

try:
    from fastapi import Request as FastAPIRequest
except ImportError:
    FastAPIRequest = Any


APP_NAME = "proteina-complexa"
SECRET_NAME = "proteina-complexa-api-key"
API_KEY_ENV = "PROTEINA_COMPLEXA_API_KEY"
MODEL_REPO_ID = "nvidia/NV-Proteina-Complexa-Protein-Target-160M-v1"
MODEL_SUBDIR = "protein-target-160m"
MODEL_DIR = Path("/models") / MODEL_SUBDIR
COMPLEXA_ROOT = Path("/workspace/protein-foundation-models")
COMPLEXA_BIN = Path("/workspace/.venv/bin/complexa")
PYTHON_BIN = Path("/workspace/.venv/bin/python")
WARM_START_PATCH_REMOTE_PATH = Path("/tmp/proteina-warm-start.patch")
PREPROCESS_DIR = Path("/data/preprocessed_targets")
TARGET_DATA_DIR = Path("/data/target_data/preprocessed_targets")
SEED_BINDER_DIR = Path("/data/seed_binders")
RUNS_DIR = Path("/runs")

DEFAULT_PIPELINE_CONFIG = "configs/search_binder_local_pipeline.yaml"
DEFAULT_GPU = "A100-80GB"
DEFAULT_BINDER_LENGTH = [60, 120]
TIMEOUT_SECONDS = 12 * 60 * 60
SCALEDOWN_WINDOW_SECONDS = 60
MAX_RETURNED_PDBS = 20
MAX_PDB_BYTES = 4 * 1024 * 1024
TARGET_CONFIG_REQUIRED_FIELDS = {
    "source",
    "target_filename",
    "target_path",
    "target_input",
    "hotspot_residues",
    "binder_length",
    "pdb_id",
}

model_volume = modal.Volume.from_name("proteina-complexa-models", create_if_missing=True)
data_volume = modal.Volume.from_name("proteina-complexa-data", create_if_missing=True)
runs_volume = modal.Volume.from_name("proteina-complexa-runs", create_if_missing=True)

hf_secret = modal.Secret.from_name("huggingface-secret")
api_secret = modal.Secret.from_name(SECRET_NAME)

app = modal.App(APP_NAME)


image = (
    modal.Image.from_registry("nvcr.io/nvidia/pytorch:24.08-py3")
    .apt_install("git", "rsync", "curl", "libxrender1", "libxext6")
    .run_commands(
        "git clone --depth 1 --branch dev https://github.com/NVIDIA-Digital-Bio/Proteina-Complexa "
        f"{COMPLEXA_ROOT}",
        f"cd {COMPLEXA_ROOT} && bash env/build_uv_env.sh --root /workspace/",
    )
    .pip_install("fastapi==0.115.12")
    .env(
        {
            "AF2_DIR": f"{COMPLEXA_ROOT}/community_models/ckpts/AF2",
            "CKPT_PATH": str(MODEL_DIR),
            "COMMUNITY_MODELS_PATH": f"{COMPLEXA_ROOT}/community_models",
            "COMPLEXA_INIT": "uv",
            "COMPLEXA_ROOT": str(COMPLEXA_ROOT),
            "DATA_PATH": "/data",
            "DSSP_EXEC": "/usr/local/bin/dssp",
            "FOLDSEEK_EXEC": "/workspace/.venv/bin/foldseek",
            "LOCAL_CODE_PATH": str(COMPLEXA_ROOT),
            "MMSEQS_EXEC": "/workspace/.venv/bin/mmseqs",
            "PYTHONPATH": f"{COMPLEXA_ROOT}/src",
            "RF3_CKPT_PATH": f"{COMPLEXA_ROOT}/community_models/ckpts/RF3/rf3_foundry_01_24_latest_remapped.ckpt",
            "RF3_EXEC_PATH": "/workspace/.venv/bin/rf3",
            "SC_EXEC": "/usr/local/bin/sc",
            "TMOL_PATH": "/workspace/.venv/lib/python3.12/site-packages/tmol",
        }
    )
    .workdir(str(COMPLEXA_ROOT))
    .add_local_file(
        "patches/proteina-warm-start.patch",
        remote_path=str(WARM_START_PATCH_REMOTE_PATH),
        copy=True,
    )
    .run_commands(
        "cd {root} && "
        "if git apply --reverse --check {patch} >/dev/null 2>&1; then "
        "echo 'Proteina warm-start patch: already-applied'; "
        "elif grep -q seed_binder_pdb_path src/proteinfoundation/datasets/gen_dataset.py "
        "&& grep -q warm_start_initial_state src/proteinfoundation/proteina.py "
        "&& grep -q warm_start_checkpoints src/proteinfoundation/search/beam_search.py; then "
        "echo 'Proteina warm-start patch: native'; "
        "else git apply {patch}; "
        "fi".format(root=COMPLEXA_ROOT, patch=WARM_START_PATCH_REMOTE_PATH)
    )
    .add_local_python_source("api_contract")
    .add_local_python_source("preprocessing")
    .add_local_python_source("proteina_warm_start")
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
        check=False,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        print(completed.stdout, flush=True)
    if completed.returncode != 0:
        output_tail = completed.stdout[-4000:] if completed.stdout else "<no output>"
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}\n"
            f"--- subprocess output tail ---\n{output_tail}"
        )
    return completed.stdout


def _run_complexa(command: list[str], *, cwd: Path = COMPLEXA_ROOT) -> str:
    return _run(command, cwd=cwd, env={"COMPLEXA_INIT": "uv"})


def _extract_api_key_from_basic_auth(value: str) -> str | None:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception:
        return None

    _, separator, password = decoded.partition(":")
    if not separator:
        return None
    return password


def _candidate_api_keys(headers: Any) -> list[str]:
    api_keys: list[str] = []

    x_api_key = headers.get("x-api-key")
    if x_api_key:
        api_keys.append(x_api_key.strip())

    authorization = headers.get("authorization")
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        scheme = scheme.lower()
        credentials = credentials.strip()
        if scheme == "bearer" and credentials:
            api_keys.append(credentials)
        elif scheme == "basic" and credentials:
            basic_key = _extract_api_key_from_basic_auth(credentials)
            if basic_key:
                api_keys.append(basic_key)

    return api_keys


def _assert_authorized(headers: Any) -> None:
    expected = os.environ.get(API_KEY_ENV)
    if not expected:
        raise RuntimeError(f"Modal Secret {SECRET_NAME!r} must define {API_KEY_ENV}")
    try:
        expected_bytes = expected.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            f"Modal Secret {SECRET_NAME!r} value {API_KEY_ENV} must contain only ASCII characters"
        ) from exc

    for candidate in _candidate_api_keys(headers):
        try:
            candidate_bytes = candidate.encode("ascii")
        except UnicodeEncodeError:
            continue
        if hmac.compare_digest(candidate_bytes, expected_bytes):
            return

    from fastapi import HTTPException

    raise HTTPException(
        status_code=401,
        detail="Missing or invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _ensure_warm_start_support() -> str:
    status = warm_start_support_status(COMPLEXA_ROOT)
    print(f"Proteina warm-start support: {status}", flush=True)
    if status == "missing":
        raise RuntimeError(
            "Proteina warm-start hooks are not installed in this image. "
            "Rebuild the Modal image with patches/proteina-warm-start.patch or use a custom Proteina-Complexa image."
        )
    return status


def _tail_text(path: Path, *, limit: int = 12000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(errors="replace")
    return text[-limit:]


def _collect_run_log_tails(
    run_dir: Path,
    *,
    exclude: set[Path] | None = None,
    limit: int = 12000,
) -> str:
    log_paths = sorted(run_dir.glob("logs/**/*.log"), key=lambda path: path.stat().st_mtime)
    if exclude:
        log_paths = [path for path in log_paths if path not in exclude]
    if not log_paths:
        return ""
    sections = []
    for path in log_paths[-6:]:
        relative = path.relative_to(run_dir)
        sections.append(f"--- {relative} ---\n{_tail_text(path, limit=limit)}")
    return "\n\n".join(sections)


def _checkpoint_overrides() -> list[str]:
    return [
        f"++ckpt_path={MODEL_DIR}",
        "++ckpt_name=complexa.ckpt",
        f"++autoencoder_ckpt_path={MODEL_DIR / 'complexa_ae.ckpt'}",
    ]


def _normalize_design_steps(steps: Iterable[str] | None) -> list[str]:
    allowed = {"generate", "filter", "evaluate", "analyze"}
    normalized = [step for step in (steps or []) if step]
    invalid = [step for step in normalized if step not in allowed]
    if invalid:
        raise ValueError(f"Invalid design steps: {invalid}. Allowed: {sorted(allowed)}")
    return normalized


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


def _ensure_model_weights(force: bool = False) -> dict[str, str]:
    model_volume.reload()
    present = _local_weight_files()
    if len(present) == 2 and not force:
        return present

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


def _normalize_overrides(overrides: Iterable[str] | None) -> list[str]:
    return [override for override in (overrides or []) if override]


def _seed_binder_remote_path(
    *,
    task_name: str,
    run_name: str,
    seed_binder_filename: str = "seed_binder.pdb",
) -> Path:
    safe_task_name = sanitize_name(task_name)
    safe_run_name = sanitize_name(run_name)
    seed_name = Path(seed_binder_filename).name
    seed_path = Path(seed_name)
    if seed_path.suffix.lower() == ".gz":
        suffix = seed_path.with_suffix("").suffix
    else:
        suffix = seed_path.suffix
    if suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
        suffix = ".pdb"
    return SEED_BINDER_DIR / f"{safe_task_name}_{safe_run_name}{suffix}"


def _write_seed_binder_pdb(
    *,
    task_name: str,
    run_name: str,
    seed_binder_pdb_text: str,
    seed_binder_filename: str = "seed_binder.pdb",
) -> Path:
    SEED_BINDER_DIR.mkdir(parents=True, exist_ok=True)
    seed_path = _seed_binder_remote_path(
        task_name=task_name,
        run_name=run_name,
        seed_binder_filename=seed_binder_filename,
    )
    seed_path.write_text(seed_binder_pdb_text)
    data_volume.commit()
    return seed_path


def _seed_binder_overrides(
    *,
    seed_binder_pdb_path: Path,
    seed_binder_chain: str | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
) -> list[str]:
    prefix = "++generation.dataloader.dataset.conditional_features.0."
    overrides = [f"{prefix}seed_binder_pdb_path={seed_binder_pdb_path}"]
    if seed_binder_chain:
        overrides.append(f"{prefix}seed_binder_chain={seed_binder_chain}")
    if seed_binder_noise_level is not None:
        overrides.append(f"{prefix}seed_binder_noise_level={float(seed_binder_noise_level)}")
    if seed_binder_start_t is not None:
        overrides.append(f"{prefix}seed_binder_start_t={float(seed_binder_start_t)}")
    if seed_binder_num_steps is not None:
        overrides.append(f"{prefix}seed_binder_num_steps={int(seed_binder_num_steps)}")
    return overrides


def _target_override_prefix(target_name: str) -> str:
    return f"++generation.target_dict_cfg.{target_name}."


def _target_override_fields(target_name: str, overrides: Iterable[str] | None) -> set[str]:
    prefix = _target_override_prefix(target_name)
    fields = set()
    for override in _normalize_overrides(overrides):
        if not override.startswith(prefix) or "=" not in override:
            continue
        field = override[len(prefix) :].split("=", 1)[0]
        if field:
            fields.add(field)
    return fields


def _design_command(
    *,
    task_name: str,
    run_name: str,
    pipeline_config: str,
    overrides: Iterable[str] | None,
    steps: Iterable[str] | None,
) -> list[str]:
    design_steps = _normalize_design_steps(steps)
    command = [
        str(COMPLEXA_BIN),
        "design",
        _config_path(pipeline_config),
        *_checkpoint_overrides(),
        f"++run_name={run_name}",
        f"++generation.task_name={task_name}",
        *_normalize_overrides(overrides),
    ]
    if design_steps:
        command.extend(["--steps", *design_steps])
    return command


def _preprocessed_target_config_path(target_name: str, preprocess_dir: Path | None = None) -> Path:
    return (preprocess_dir or PREPROCESS_DIR) / f"{target_name}.target.json"


def _preprocessed_target_feature_path(target_name: str, preprocess_dir: Path | None = None) -> Path:
    return (preprocess_dir or PREPROCESS_DIR) / f"{target_name}.preprocess.json"


def _write_preprocessed_target_config(
    *,
    target_name: str,
    target_path: Path,
    target_input: str,
    hotspot_residues: list[str],
    binder_length: list[int],
    pdb_id: str,
    overrides: list[str],
) -> str:
    path = _preprocessed_target_config_path(target_name)
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


def _load_preprocessed_target_config(target_name: str) -> dict | None:
    config_path = _preprocessed_target_config_path(target_name)
    if config_path.exists():
        return json.loads(config_path.read_text())

    feature_path = _preprocessed_target_feature_path(target_name)
    if not feature_path.exists():
        return None

    metadata = json.loads(feature_path.read_text())
    return {
        "target_name": target_name,
        "source": "preprocessed_targets",
        "target_filename": target_name,
        "target_path": str(TARGET_DATA_DIR / f"{target_name}.pdb"),
        "target_input": metadata["target_input"],
        "hotspot_residues": metadata.get("hotspot_residues", []),
        "binder_length": metadata.get("binder_length", DEFAULT_BINDER_LENGTH),
        "pdb_id": metadata.get("pdb_id", target_name),
    }


def _target_overrides_from_preprocessed_config(target_name: str) -> list[str]:
    metadata = _load_preprocessed_target_config(target_name)
    if metadata is None:
        return []

    target_path = Path(str(metadata.get("target_path") or TARGET_DATA_DIR / f"{target_name}.pdb"))
    if not target_path.exists():
        raise FileNotFoundError(
            f"Preprocessed target metadata exists for {target_name!r}, but the PDB is missing: {target_path}. "
            "Run preprocess-cif/design-cif again so the target PDB is present in the Modal data volume."
        )

    binder_length = list(metadata.get("binder_length") or DEFAULT_BINDER_LENGTH)
    if len(binder_length) != 2:
        raise ValueError(f"Preprocessed target {target_name!r} has invalid binder_length: {binder_length!r}")

    overrides = _target_overrides(
        target_name=target_name,
        target_path=target_path,
        target_input=str(metadata["target_input"]),
        hotspot_residues=[str(value) for value in metadata.get("hotspot_residues", [])],
        binder_length=[int(binder_length[0]), int(binder_length[1])],
        pdb_id=str(metadata.get("pdb_id") or target_name),
    )
    return [override for override in overrides if not override.startswith("++generation.task_name=")]


def _resolve_design_overrides(task_name: str, overrides: Iterable[str] | None) -> list[str]:
    normalized = _normalize_overrides(overrides)
    present_fields = _target_override_fields(task_name, normalized)
    missing_fields = TARGET_CONFIG_REQUIRED_FIELDS - present_fields
    if not missing_fields:
        return normalized

    preprocessed_overrides = _target_overrides_from_preprocessed_config(task_name)
    if preprocessed_overrides:
        return [*preprocessed_overrides, *normalized]

    if present_fields:
        raise ValueError(
            f"Target overrides for {task_name!r} are incomplete. "
            f"Missing fields: {sorted(missing_fields)}"
        )

    return normalized


def _pipeline_config_name(pipeline_config: str) -> str:
    return Path(pipeline_config).stem


def _run_output_paths(*, task_name: str, run_name: str, pipeline_config: str) -> dict[str, Path]:
    run_dir = RUNS_DIR / run_name
    config_name = _pipeline_config_name(pipeline_config)
    inference_dir = run_dir / "inference" / f"{config_name}_{task_name}_{run_name}"
    evaluation_dir = run_dir / "evaluation_results" / f"{config_name}_{task_name}_{run_name}"
    hydra_dir = run_dir / "logs" / "hydra_outputs" / "${now:%Y-%m-%d}" / "${now:%H-%M-%S}"
    return {
        "run_dir": run_dir,
        "inference_dir": inference_dir,
        "evaluation_dir": evaluation_dir,
        "hydra_dir": hydra_dir,
    }


def _run_output_overrides(*, task_name: str, run_name: str, pipeline_config: str) -> list[str]:
    paths = _run_output_paths(task_name=task_name, run_name=run_name, pipeline_config=pipeline_config)
    return [
        f"++root_path={paths['inference_dir']}",
        f"++sample_storage_path={paths['inference_dir']}",
        f"++output_dir={paths['evaluation_dir']}",
        f"++results_dir={paths['evaluation_dir']}",
        f"++hydra.run.dir={paths['hydra_dir']}",
    ]


def _parse_json_list(value: str, *, default: list | None = None) -> list:
    if not value:
        return list(default or [])
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON list")
    return parsed


def _read_structure_text(path: Path) -> str:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt").read()
    return path.read_text()


def _collect_generated_pdbs(
    *,
    inference_dir: Path,
    max_files: int = MAX_RETURNED_PDBS,
    max_file_bytes: int = MAX_PDB_BYTES,
) -> list[dict[str, Any]]:
    if not inference_dir.exists():
        return []

    pdb_paths = sorted(
        (
            path
            for path in inference_dir.rglob("*.pdb")
            if path.is_file() and path.stat().st_size <= max_file_bytes
        ),
        key=lambda path: str(path),
    )
    pdbs = []
    for rank, path in enumerate(pdb_paths[:max_files], start=1):
        pdbs.append(
            {
                "rank": rank,
                "filename": path.name,
                "path": str(path),
                "relative_path": str(path.relative_to(inference_dir)),
                "pdb": path.read_text(errors="replace"),
            }
        )
    return pdbs


def _structure_suffix(filename: str, structure_text: str) -> str:
    suffixes = [suffix.lower() for suffix in Path(filename).suffixes]
    if suffixes and suffixes[-1] == ".gz":
        suffixes = suffixes[:-1]
    suffix = suffixes[-1] if suffixes else ""
    if suffix in {".pdb", ".cif", ".mmcif"}:
        return suffix
    return ".pdb" if infer_structure_format(structure_text) == "pdb" else ".cif"


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
        f"++generation.target_dict_cfg.{target_name}.source=preprocessed_targets",
        f"++generation.target_dict_cfg.{target_name}.target_filename={target_name}",
        f"++generation.target_dict_cfg.{target_name}.target_path={target_path}",
        f"++generation.target_dict_cfg.{target_name}.target_input={target_input_value}",
        f"++generation.target_dict_cfg.{target_name}.hotspot_residues={hotspots}",
        f"++generation.target_dict_cfg.{target_name}.binder_length={length_range}",
        f"++generation.target_dict_cfg.{target_name}.pdb_id={pdb_id}",
    ]


def _write_target_pdb(
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
    output = _run([str(PYTHON_BIN), "-c", script])
    return json.loads(output.strip().splitlines()[-1])


def _inspect_target_tensors(
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
    output = _run([str(PYTHON_BIN), "-c", script])
    return json.loads(output.strip().splitlines()[-1])


def _encode_target_latents(
    *,
    structure_path: Path,
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

structure_path = Path({str(structure_path)!r})
latent_path = Path({str(latent_path)!r})
target_input = {target_input!r}

loaded = load_any(str(structure_path), model=1)
struct = loaded[0] if isinstance(loaded, (list, tuple)) else loaded
selection = AtomSelectionStack.from_contig(target_input)
struct = struct[selection.get_mask(struct)]
print(json.dumps({{"selected_atoms": int(len(struct)), "target_input": target_input}}), flush=True)
if len(struct) == 0:
    raise ValueError(f"Target selection matched no atoms: {{target_input}}")
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
residue_type = torch.from_numpy(encoded["seq"]).long().unsqueeze(0)
residue_mask = atom_mask[..., 1]
print(json.dumps({{
    "encoded_xyz_shape": list(encoded["xyz"].shape),
    "encoded_mask_shape": list(encoded["mask"].shape),
    "encoded_seq_shape": list(encoded["seq"].shape),
    "ca_residue_count": int(residue_mask.sum().item()),
}}), flush=True)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
batch = {{
    "coords_nm": coords_nm.to(device),
    "coords": (coords_nm * 10.0).to(device),
    "coord_mask": atom_mask.to(device),
    "residue_type": residue_type.to(device),
    "residue_mask": residue_mask.to(device),
    "mask_dict": {{
        "coords": atom_mask.to(device),
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
    "structure_path": str(structure_path),
}}
latent_path.parent.mkdir(parents=True, exist_ok=True)
torch.save(payload, latent_path)
print(json.dumps({{
    "latent_path": str(latent_path),
    "z_latent_shape": list(payload["z_latent"].shape),
    "ca_coords_nm_shape": list(payload["ca_coords_nm"].shape),
}}))
"""
    script_path = Path("/tmp") / f"{latent_path.stem}.encode_latents.py"
    script_path.write_text(script)
    output = _run([str(PYTHON_BIN), str(script_path)])
    return json.loads(output.strip().splitlines()[-1])


def _preprocess_target_structure_impl(
    structure_text: str,
    structure_filename: str,
    target_name: str | None = None,
    target_input: str | None = None,
    chains: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length: list[int] | None = None,
    encode_latents: bool = False,
) -> dict:
    """Convert a target structure into a Complexa target PDB plus diagnostics."""
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
    structure_path = PREPROCESS_DIR / f"{safe_target_name}{_structure_suffix(structure_filename, structure_text)}"
    structure_path.write_text(structure_text)
    outputs = write_preprocessed_outputs(result, PREPROCESS_DIR)
    pdb_path = TARGET_DATA_DIR / f"{safe_target_name}.pdb"
    pdb_info = _write_target_pdb(structure_path=structure_path, pdb_path=pdb_path)
    target_tensor_info = _inspect_target_tensors(
        pdb_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=effective_hotspots,
    )

    latent_info = None
    if encode_latents:
        latent_path = PREPROCESS_DIR / f"{safe_target_name}.latents.pt"
        latent_info = _encode_target_latents(
            structure_path=pdb_path,
            latent_path=latent_path,
            target_input=result.target_input,
        )

    length_range = binder_length or DEFAULT_BINDER_LENGTH
    if len(length_range) != 2:
        raise ValueError("binder_length must contain [min_length, max_length]")
    normalized_binder_length = [int(length_range[0]), int(length_range[1])]

    overrides = _target_overrides(
        target_name=safe_target_name,
        target_path=pdb_path,
        target_input=result.target_input,
        hotspot_residues=effective_hotspots,
        binder_length=normalized_binder_length,
        pdb_id=safe_target_name,
    )
    target_config_json_path = _write_preprocessed_target_config(
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
        "cif_path": str(structure_path),
        "pdb_path": str(pdb_path),
        "feature_json_path": outputs["json"],
        "target_config_json_path": target_config_json_path,
        "fasta_path": outputs["fasta"],
        "pdb_info": pdb_info,
        "target_tensor_info": target_tensor_info,
        "latent_info": latent_info,
        "hydra_overrides": overrides,
    }


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume,
    },
    timeout=60 * 60,
)
def preprocess_cif(
    cif_text: str,
    cif_filename: str,
    target_name: str | None = None,
    target_input: str | None = None,
    chains: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length: list[int] | None = None,
    encode_latents: bool = False,
) -> dict:
    """Convert a CIF/PDB target into the Complexa target layout."""
    return _preprocess_target_structure_impl(
        structure_text=cif_text,
        structure_filename=cif_filename,
        target_name=target_name,
        target_input=target_input,
        chains=chains,
        hotspot_residues=hotspot_residues,
        binder_length=binder_length,
        encode_latents=encode_latents,
    )


@app.function(
    image=image,
    secrets=[hf_secret],
    volumes={"/models": model_volume},
    timeout=60 * 60,
)
def download_weights(force: bool = False) -> dict[str, str]:
    """Download the HF checkpoint pair into the persistent model Volume."""
    return _ensure_model_weights(force=force)


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
    return _run_complexa(command)


def _design_binder_impl(
    task_name: str,
    run_name: str,
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: list[str] | None = None,
    steps: list[str] | None = None,
    seed_binder_pdb_text: str | None = None,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_chain: str | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
    include_generated_pdbs: bool = False,
) -> dict:
    """Run a single protein-target binder design job on one Modal GPU."""
    model_volume.reload()
    data_volume.reload()
    runs_volume.reload()
    run_paths = _run_output_paths(task_name=task_name, run_name=run_name, pipeline_config=pipeline_config)
    run_dir = run_paths["run_dir"]
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_logs = set(run_dir.glob("logs/**/*.log"))
    seed_overrides: list[str] = []
    warm_start: dict[str, str] = {"mode": "cold"}
    if seed_binder_pdb_text:
        try:
            support_status = _ensure_warm_start_support()
            seed_binder_path = _write_seed_binder_pdb(
                task_name=task_name,
                run_name=run_name,
                seed_binder_pdb_text=seed_binder_pdb_text,
                seed_binder_filename=seed_binder_filename,
            )
            seed_overrides = _seed_binder_overrides(
                seed_binder_pdb_path=seed_binder_path,
                seed_binder_chain=seed_binder_chain,
                seed_binder_noise_level=seed_binder_noise_level,
                seed_binder_start_t=seed_binder_start_t,
                seed_binder_num_steps=seed_binder_num_steps,
            )
            warm_start = {
                "mode": "warm",
                "seed_binder_pdb_path": str(seed_binder_path),
                "support_status": support_status,
            }
        except Exception as exc:
            print(f"Warm-start setup failed; falling back to cold start: {exc}", flush=True)
    design_overrides = [
        *_run_output_overrides(task_name=task_name, run_name=run_name, pipeline_config=pipeline_config),
        *_resolve_design_overrides(task_name, overrides),
        *seed_overrides,
    ]
    command = _design_command(
        task_name=task_name,
        run_name=run_name,
        pipeline_config=pipeline_config,
        overrides=design_overrides,
        steps=steps,
    )
    try:
        output = _run_complexa(command, cwd=COMPLEXA_ROOT)
    except Exception as exc:
        log_tails = _collect_run_log_tails(run_dir, exclude=existing_logs)
        runs_volume.commit()
        if log_tails:
            raise RuntimeError(f"{exc}\n--- run log tails ---\n{log_tails}") from exc
        raise
    runs_volume.commit()
    result = {"run_name": run_name, "task_name": task_name, "warm_start": warm_start, "log_tail": output[-4000:]}
    if include_generated_pdbs:
        pdbs = _collect_generated_pdbs(inference_dir=run_paths["inference_dir"])
        result["format"] = "pdb"
        result["count"] = len(pdbs)
        result["pdbs"] = pdbs
        if pdbs:
            result["pdb_filename"] = pdbs[0]["filename"]
            result["pdb"] = pdbs[0]["pdb"]
    return result


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume,
        "/runs": runs_volume,
    },
    timeout=TIMEOUT_SECONDS,
)
def design_binder(
    task_name: str,
    run_name: str,
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: list[str] | None = None,
    steps: list[str] | None = None,
    seed_binder_pdb_text: str | None = None,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_chain: str | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
    include_generated_pdbs: bool = False,
) -> dict:
    return _design_binder_impl(
        task_name=task_name,
        run_name=run_name,
        pipeline_config=pipeline_config,
        overrides=overrides,
        steps=steps,
        seed_binder_pdb_text=seed_binder_pdb_text,
        seed_binder_filename=seed_binder_filename,
        seed_binder_chain=seed_binder_chain,
        seed_binder_noise_level=seed_binder_noise_level,
        seed_binder_start_t=seed_binder_start_t,
        seed_binder_num_steps=seed_binder_num_steps,
        include_generated_pdbs=include_generated_pdbs,
    )


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
    return _run_complexa([str(COMPLEXA_BIN), "status", _config_path(pipeline_config)], cwd=Path("/runs"))


async def _parse_request_payload(request: Any) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise ValueError("Request body must be application/json")
    payload = await request.json()
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _smoke_overrides() -> list[str]:
    return [
        "++generation.search.algorithm=single-pass",
        "++generation.reward_model=null",
        "++generation.dataloader.batch_size=1",
        "++generation.dataloader.dataset.nres.nsamples=1",
        "++generation.args.nsteps=20",
    ]


def _run_design_payload(design_payload: DesignPayload) -> dict:
    preprocessed = _preprocess_target_structure_impl(
        structure_text=design_payload.target.structure_text,
        structure_filename=design_payload.target.filename,
        target_name=design_payload.target.target_name,
        target_input=design_payload.target.target_input,
        chains=design_payload.target.chains,
        hotspot_residues=design_payload.target.hotspot_residues,
        binder_length=design_payload.target.binder_length,
        encode_latents=design_payload.target.encode_latents,
    )
    target_overrides = [
        override
        for override in preprocessed["hydra_overrides"]
        if not override.startswith("++generation.task_name=")
    ]
    effective_steps = _normalize_design_steps(design_payload.design_steps)
    request_overrides = _normalize_overrides(design_payload.overrides)
    mode_overrides: list[str] = []
    if design_payload.smoke:
        effective_steps = ["generate"]
        mode_overrides = _smoke_overrides()

    warm_start = design_payload.warm_start
    design = _design_binder_impl(
        task_name=preprocessed["target_name"],
        run_name=design_payload.run_name,
        pipeline_config=design_payload.pipeline_config,
        overrides=[*target_overrides, *mode_overrides, *request_overrides],
        steps=effective_steps,
        seed_binder_pdb_text=warm_start.structure_text if warm_start else None,
        seed_binder_filename=warm_start.filename if warm_start else "seed_binder.pdb",
        seed_binder_chain=warm_start.chain if warm_start else None,
        seed_binder_noise_level=warm_start.noise_level if warm_start else None,
        seed_binder_start_t=warm_start.start_t if warm_start else None,
        seed_binder_num_steps=warm_start.num_steps if warm_start else None,
        include_generated_pdbs=True,
    )
    return {
        "run_name": design_payload.run_name,
        "task_name": preprocessed["target_name"],
        "mode": "smoke-cif" if design_payload.smoke else "design-cif",
        "preprocessed_target": preprocessed,
        "design": design,
        "format": "pdb",
        "count": design.get("count", 0),
        "pdbs": design.get("pdbs", []),
        "pdb_filename": design.get("pdb_filename"),
        "pdb": design.get("pdb"),
    }


def _run_design_request(payload: dict[str, Any]) -> dict:
    design_payload = normalize_design_payload(
        payload,
        default_pipeline_config=DEFAULT_PIPELINE_CONFIG,
        default_binder_length=DEFAULT_BINDER_LENGTH,
    )
    return _run_design_payload(design_payload)


def _pdb_download_headers(filename: str) -> dict[str, str]:
    safe_filename = Path(filename).name or "proteina_complexa_prediction.pdb"
    return {"Content-Disposition": f'attachment; filename="{safe_filename}"'}


def _pdb_file_payload(result: dict[str, Any]) -> tuple[str, str]:
    pdb_text = result.get("pdb")
    filename = result.get("pdb_filename") or "proteina_complexa_prediction.pdb"
    if pdb_text:
        return str(filename), str(pdb_text)

    pdbs = result.get("pdbs") or []
    if pdbs:
        first = pdbs[0]
        return str(first.get("filename") or filename), str(first["pdb"])

    raise ValueError(
        "Proteina-Complexa completed, but no generated PDB was found in the run output."
    )


def _request_wants_pdb_file(request: Any, payload: dict[str, Any]) -> bool:
    path = getattr(getattr(request, "url", None), "path", "")
    if str(path).endswith(".pdb"):
        return True

    return_format = str(payload.get("return_format") or payload.get("format") or "").lower()
    if return_format in {"pdb", "file", "download"}:
        return True

    accept = request.headers.get("accept", "").lower()
    return "chemical/x-pdb" in accept or "application/octet-stream" in accept


@app.function(
    image=image,
    gpu=DEFAULT_GPU,
    volumes={
        "/models": model_volume,
        "/data": data_volume,
        "/runs": runs_volume,
    },
    secrets=[api_secret, hf_secret],
    min_containers=0,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=TIMEOUT_SECONDS,
)
@modal.asgi_app()
def fastapi_app():
    from fastapi import FastAPI, HTTPException, Response
    from starlette.concurrency import run_in_threadpool

    _ensure_model_weights()
    web_app = FastAPI(title="Proteina-Complexa Modal Design", version="1.0.0")

    @web_app.get("/health")
    async def health(request: FastAPIRequest) -> dict[str, Any]:
        _assert_authorized(request.headers)
        return {"status": "ok", "weights": _local_weight_files()}

    @web_app.post("/")
    @web_app.post("/design")
    @web_app.post("/predict")
    @web_app.post("/design.pdb")
    @web_app.post("/predict.pdb")
    async def design(request: FastAPIRequest) -> Any:
        _assert_authorized(request.headers)
        try:
            payload = await _parse_request_payload(request)
            result = await run_in_threadpool(_run_design_request, payload)
            if _request_wants_pdb_file(request, payload):
                filename, pdb_text = _pdb_file_payload(result)
                return Response(
                    content=pdb_text,
                    media_type="chemical/x-pdb",
                    headers=_pdb_download_headers(filename),
                )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return web_app


@app.local_entrypoint()
def main(
    action: str = "list-weights",
    task_name: str = "02_PDL1",
    run_name: str = "pdl1_modal_smoke",
    overrides_json: str = "[]",
    design_steps_json: str = "[]",
    jobs_json: str = "",
    cif_path: str = "",
    target_name: str = "",
    target_input: str = "",
    chains: str = "",
    hotspot_residues_json: str = "[]",
    binder_length_json: str = "[60, 120]",
    encode_latents: bool = False,
    seed_binder_pdb_path: str = "",
    seed_binder_chain: str = "",
    seed_binder_noise_level: float = -1.0,
    seed_binder_start_t: float = -1.0,
    seed_binder_num_steps: int = 0,
):
    overrides = json.loads(overrides_json)
    design_steps = _normalize_design_steps(_parse_json_list(design_steps_json))
    seed_binder_pdb_text = ""
    seed_binder_filename = "seed_binder.pdb"
    if seed_binder_pdb_path:
        seed_path = Path(seed_binder_pdb_path)
        if seed_path.exists():
            seed_binder_pdb_text = _read_structure_text(seed_path)
            seed_binder_filename = seed_path.name
        else:
            print(f"Seed binder PDB not found; falling back to cold start: {seed_path}", flush=True)
    warm_noise_level = seed_binder_noise_level if seed_binder_noise_level >= 0 else None
    warm_start_t = seed_binder_start_t if seed_binder_start_t >= 0 else None
    warm_num_steps = seed_binder_num_steps if seed_binder_num_steps > 0 else None
    if action == "download-weights":
        print(download_weights.remote())
    elif action == "list-weights":
        print(list_weights.remote())
    elif action == "validate":
        print(validate.remote(overrides=overrides))
    elif action == "design":
        print(
            design_binder.remote(
                task_name=task_name,
                run_name=run_name,
                overrides=overrides,
                steps=design_steps,
                seed_binder_pdb_text=seed_binder_pdb_text or None,
                seed_binder_filename=seed_binder_filename,
                seed_binder_chain=seed_binder_chain or None,
                seed_binder_noise_level=warm_noise_level,
                seed_binder_start_t=warm_start_t,
                seed_binder_num_steps=warm_num_steps,
            )
        )
    elif action == "preprocess-cif":
        if not cif_path:
            raise ValueError("--cif-path is required for --action preprocess-cif")
        path = Path(cif_path)
        result = preprocess_cif.remote(
            _read_structure_text(path),
            path.name,
            target_name or None,
            target_input or None,
            chains or None,
            _parse_json_list(hotspot_residues_json),
            _parse_json_list(binder_length_json, default=[60, 120]),
            encode_latents,
        )
        print(json.dumps(result, indent=2))
    elif action in {"design-cif", "smoke-cif"}:
        if not cif_path:
            raise ValueError(f"--cif-path is required for --action {action}")
        path = Path(cif_path)
        preprocessed = preprocess_cif.remote(
            _read_structure_text(path),
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
        smoke_overrides = []
        effective_steps = design_steps
        if action == "smoke-cif":
            effective_steps = ["generate"]
            smoke_overrides = _smoke_overrides()
        design_overrides = [*target_overrides, *smoke_overrides, *_normalize_overrides(overrides)]
        print(
            design_binder.remote(
                task_name=preprocessed["target_name"],
                run_name=run_name,
                overrides=design_overrides,
                steps=effective_steps,
                seed_binder_pdb_text=seed_binder_pdb_text or None,
                seed_binder_filename=seed_binder_filename,
                seed_binder_chain=seed_binder_chain or None,
                seed_binder_noise_level=warm_noise_level,
                seed_binder_start_t=warm_start_t,
                seed_binder_num_steps=warm_num_steps,
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
