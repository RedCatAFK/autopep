from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Iterable

import modal


APP_NAME = "proteina-complexa"
MODEL_REPO_ID = "nvidia/NV-Proteina-Complexa-Protein-Target-160M-v1"
MODEL_SUBDIR = "protein-target-160m"
MODEL_DIR = Path("/models") / MODEL_SUBDIR
COMPLEXA_ROOT = Path("/workspace/protein-foundation-models")
COMPLEXA_BIN = Path("/workspace/.venv/bin/complexa")
PYTHON_BIN = Path("/workspace/.venv/bin/python")

DEFAULT_PIPELINE_CONFIG = "configs/search_binder_local_pipeline.yaml"
DEFAULT_GPU = "A100-80GB"
AUTOPEP_WORKSPACES_VOLUME_NAME = "autopep-project-workspaces"

model_volume = modal.Volume.from_name("proteina-complexa-models", create_if_missing=True)
data_volume = modal.Volume.from_name("proteina-complexa-data", create_if_missing=True)
runs_volume = modal.Volume.from_name("proteina-complexa-runs", create_if_missing=True)
autopep_workspaces_volume = modal.Volume.from_name(
    AUTOPEP_WORKSPACES_VOLUME_NAME,
    create_if_missing=True,
    version=2,
)

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
        "/autopep": autopep_workspaces_volume.read_only(),
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
        "/autopep": autopep_workspaces_volume.read_only(),
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
        "/autopep": autopep_workspaces_volume.read_only(),
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
