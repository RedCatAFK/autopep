from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from .config import COMPLEXA_ROOT, MODEL_DIR, MODEL_REPO_ID, PYTHON_BIN


def run_command(
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


def run_complexa(command: list[str], *, cwd: Path = COMPLEXA_ROOT) -> str:
    return run_command(command, cwd=cwd, env={"COMPLEXA_INIT": "uv"})


def local_weight_files() -> dict[str, str]:
    files = {}
    for filename in ("complexa.ckpt", "complexa_ae.ckpt"):
        path = MODEL_DIR / filename
        if path.exists():
            files[str(path)] = f"{path.stat().st_size / (1024 ** 3):.2f} GiB"
    return files


def ensure_model_weights(force: bool = False) -> dict[str, str]:
    from .modal_resources import model_volume

    model_volume.reload()
    present = local_weight_files()
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
    run_command([str(PYTHON_BIN), "-c", script])
    model_volume.commit()
    return local_weight_files()
