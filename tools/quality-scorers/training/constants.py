from pathlib import Path

APP_PREFIX = "quality-scorers"

DATA_VOLUME_NAME = "quality-scorers-data"
MODEL_VOLUME_NAME = "quality-scorers-models"

DATA_ROOT = Path("/data")
MODEL_ROOT = Path("/models")

RAW_DIR = DATA_ROOT / "raw"
NORMALIZED_DIR = DATA_ROOT / "normalized"
EMBEDDING_DIR = DATA_ROOT / "embeddings"
MANIFEST_DIR = DATA_ROOT / "manifests"

HF_HOME = MODEL_ROOT / "huggingface"
ESM2_ROOT = MODEL_ROOT / "esm2"
HEAD_ROOT = MODEL_ROOT / "heads"

DEFAULT_ESM2_MODEL_ID = "facebook/esm2_t12_35M_UR50D"
DEFAULT_ESM2_MAX_AA = 1022
DEFAULT_CHUNK_OVERLAP = 128

VALID_AA = frozenset("ACDEFGHIKLMNPQRSTVWY")

SOLUBILITY_DATASET_ID = "SaProtHub/Dataset-Solubility"
SOLUBILITY_URL = "https://huggingface.co/datasets/SaProtHub/Dataset-Solubility"

ANUPP_DATASETS_URL = "https://web.iitm.ac.in/bioinfo2/anupp/datasets/"

DTU_NETMHC_BASE_URL = (
    "https://services.healthtech.dtu.dk/suppl/immunology/"
    "NAR_NetMHCpan_NetMHCIIpan/"
)
NETMHCPAN_TARBALL_URL = DTU_NETMHC_BASE_URL + "NetMHCpan_train.tar.gz"
NETMHCII_TARBALL_URL = DTU_NETMHC_BASE_URL + "NetMHCIIpan_train.tar.gz"


def model_key(model_id: str) -> str:
    return (
        model_id.replace("/", "__")
        .replace(":", "_")
        .replace("@", "_")
        .replace(" ", "_")
    )


def esm2_local_dir(model_id: str) -> Path:
    return ESM2_ROOT / model_key(model_id)


def embedding_model_dir(model_id: str) -> Path:
    return EMBEDDING_DIR / model_key(model_id)


def head_model_dir(model_id: str) -> Path:
    return HEAD_ROOT / model_key(model_id)

