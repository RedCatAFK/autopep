from __future__ import annotations

from pathlib import Path


APP_NAME = "proteina-complexa"
SECRET_NAME = "proteina-complexa-api-key"
API_KEY_ENV = "PROTEINA_COMPLEXA_API_KEY"

REPO_ROOT = Path(__file__).resolve().parents[1]
WARM_START_PATCH_PATH = REPO_ROOT / "patches" / "proteina-warm-start.patch"
WARM_START_PATCH_REMOTE_PATH = Path("/tmp/proteina-warm-start.patch")

MODEL_REPO_ID = "nvidia/NV-Proteina-Complexa-Protein-Target-160M-v1"
MODEL_SUBDIR = "protein-target-160m"
MODEL_DIR = Path("/models") / MODEL_SUBDIR

COMPLEXA_ROOT = Path("/workspace/protein-foundation-models")
COMPLEXA_BIN = Path("/workspace/.venv/bin/complexa")
PYTHON_BIN = Path("/workspace/.venv/bin/python")

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

