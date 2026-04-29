from __future__ import annotations

import modal

from .config import (
    APP_NAME,
    COMPLEXA_ROOT,
    MODEL_DIR,
    SECRET_NAME,
    WARM_START_PATCH_PATH,
    WARM_START_PATCH_REMOTE_PATH,
)


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
        str(WARM_START_PATCH_PATH),
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
    .add_local_python_source("proteina_complexa")
)

