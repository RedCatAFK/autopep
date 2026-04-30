from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import modal

from training.constants import (
    DATA_VOLUME_NAME,
    DEFAULT_ESM2_MODEL_ID,
    HEAD_ROOT,
    HF_HOME,
    MANIFEST_DIR,
    MODEL_VOLUME_NAME,
    embedding_model_dir,
    head_model_dir,
)
from training.heads import train_hla_mlp, train_sklearn_logistic_head
from training.io_utils import ensure_dirs, write_json

APP_NAME = "quality-scorers-head-train"
LIGHT_GPU = "T4"
TIMEOUT_SECONDS = 8 * 60 * 60

data_volume = modal.Volume.from_name(DATA_VOLUME_NAME, create_if_missing=True)
model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-runtime-ubuntu24.04",
        add_python="3.11",
    )
    .apt_install("ca-certificates")
    .pip_install(
        "joblib==1.4.2",
        "numpy==2.2.4",
        "pandas==2.2.3",
        "pyarrow==19.0.1",
        "scikit-learn==1.6.1",
        "torch==2.6.0",
    )
    .env(
        {
            "HF_HOME": str(HF_HOME),
            "PYTHONUNBUFFERED": "1",
        }
    )
    .add_local_python_source("training")
)

app = modal.App(APP_NAME, image=image)


def _load_embedding_artifacts(model_id: str, dataset: str):
    import numpy as np
    import pandas as pd

    root = embedding_model_dir(model_id)
    if dataset == "solubility":
        table_path = root / "solubility.parquet"
        matrix_path = root / "solubility.npy"
    elif dataset == "apr":
        table_path = root / "apr_hex.parquet"
        matrix_path = root / "apr_hex.npy"
    else:
        raise ValueError(f"Unknown embedding dataset: {dataset}")

    if not table_path.exists() or not matrix_path.exists():
        raise FileNotFoundError(
            f"Missing {dataset} embeddings for {model_id}. "
            "Run the ESM2 embedding app before training heads."
        )
    return pd.read_parquet(table_path), np.load(matrix_path)


def _split_xy(table, matrix, *, label_column: str, required_splits=("train", "valid", "test")):
    splits = {}
    for split in required_splits:
        mask = table["split"] == split
        if not bool(mask.any()):
            raise ValueError(f"Missing {split!r} split in embedding table")
        splits[split] = (
            matrix[mask.to_numpy()],
            table.loc[mask, label_column].to_numpy(),
        )
    return splits


def _subset_hla_embeddings_for_pairs(pairs, peptide_matrix_path: Path, hla_matrix_path: Path):
    import numpy as np

    pairs = pairs.copy()

    peptide_old_idx = np.array(sorted(pairs["peptide_idx"].unique()), dtype=np.int64)
    peptide_remap = {int(old): new for new, old in enumerate(peptide_old_idx.tolist())}
    peptide_matrix = np.load(peptide_matrix_path, mmap_mode="r")
    peptide_embeddings = np.asarray(peptide_matrix[peptide_old_idx])
    pairs["peptide_idx"] = pairs["peptide_idx"].map(peptide_remap).astype("int64")

    hla_old_idx = np.array(sorted(pairs["hla_idx"].unique()), dtype=np.int64)
    hla_remap = {int(old): new for new, old in enumerate(hla_old_idx.tolist())}
    hla_matrix = np.load(hla_matrix_path, mmap_mode="r")
    hla_embeddings = np.asarray(hla_matrix[hla_old_idx])
    pairs["hla_idx"] = pairs["hla_idx"].map(hla_remap).astype("int64")

    return pairs, peptide_embeddings, hla_embeddings


def _train_solubility_impl(model_id: str) -> dict[str, Any]:
    table, matrix = _load_embedding_artifacts(model_id, "solubility")
    splits = _split_xy(table, matrix, label_column="label")
    artifact_path = head_model_dir(model_id) / "solubility.joblib"
    result = train_sklearn_logistic_head(
        train_x=splits["train"][0],
        train_y=splits["train"][1],
        valid_x=splits["valid"][0],
        valid_y=splits["valid"][1],
        test_x=splits["test"][0],
        test_y=splits["test"][1],
        artifact_path=artifact_path,
        C=1.0,
        class_weight="balanced",
        metadata={
            "model_id": model_id,
            "head": "solubility",
            "embedding_table": str(embedding_model_dir(model_id) / "solubility.parquet"),
            "embedding_matrix": str(embedding_model_dir(model_id) / "solubility.npy"),
            "thresholds": {"pass": 0.70, "caution": 0.40},
        },
    )
    write_json(head_model_dir(model_id) / "solubility.metrics.json", result)
    write_json(MANIFEST_DIR / "solubility_head.json", result)
    return result


def _train_apr_impl(model_id: str) -> dict[str, Any]:
    import numpy as np
    from sklearn.model_selection import train_test_split

    table, matrix = _load_embedding_artifacts(model_id, "apr")
    train_mask = (table["split"] == "train").to_numpy()
    test_mask = (table["split"] == "test").to_numpy()
    if not bool(train_mask.any()) or not bool(test_mask.any()):
        raise ValueError("APR embeddings must contain non-empty train and test splits")

    train_indices = np.flatnonzero(train_mask)
    test_indices = np.flatnonzero(test_mask)
    train_labels = table.loc[train_mask, "label"].to_numpy()
    label_counts = table.loc[train_mask, "label"].value_counts()
    if label_counts.shape[0] < 2 or int(label_counts.min()) < 2:
        raise ValueError("APR train split needs at least two examples per class for calibration")

    fit_indices, valid_indices = train_test_split(
        train_indices,
        test_size=0.2,
        random_state=17,
        stratify=train_labels,
    )
    splits = {
        "train": (matrix[fit_indices], table.iloc[fit_indices]["label"].to_numpy()),
        "valid": (matrix[valid_indices], table.iloc[valid_indices]["label"].to_numpy()),
        "test": (matrix[test_indices], table.iloc[test_indices]["label"].to_numpy()),
    }
    artifact_path = head_model_dir(model_id) / "apr.joblib"
    result = train_sklearn_logistic_head(
        train_x=splits["train"][0],
        train_y=splits["train"][1],
        valid_x=splits["valid"][0],
        valid_y=splits["valid"][1],
        test_x=splits["test"][0],
        test_y=splits["test"][1],
        artifact_path=artifact_path,
        C=0.1,
        class_weight="balanced",
        metadata={
            "model_id": model_id,
            "head": "apr",
            "embedding_table": str(embedding_model_dir(model_id) / "apr_hex.parquet"),
            "embedding_matrix": str(embedding_model_dir(model_id) / "apr_hex.npy"),
            "thresholds": {"fail": 0.75, "caution": 0.40},
            "validation_note": "ANuPP provides Hex1279 train and Hex142 held-out test; 20% of Hex1279 is held out for calibration so Hex142 remains untouched for final reporting.",
        },
    )
    write_json(head_model_dir(model_id) / "apr.metrics.json", result)
    write_json(MANIFEST_DIR / "apr_head.json", result)
    return result


def _train_hla_el_impl(
    *,
    model_id: str,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
    patience: int,
    limit: int,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    root = embedding_model_dir(model_id)
    required = [
        root / "hla_el_pairs.parquet",
        root / "hla_peptides.npy",
        root / "hla_pseudosequences.npy",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing HLA embedding artifacts. Run embed_hla_el or embed_all first. "
            f"Missing: {missing}"
        )

    pairs = pd.read_parquet(root / "hla_el_pairs.parquet")
    if limit > 0:
        pairs = pairs.groupby("split", group_keys=False).head(limit).reset_index(drop=True)
        pairs, peptide_embeddings, hla_embeddings = _subset_hla_embeddings_for_pairs(
            pairs,
            root / "hla_peptides.npy",
            root / "hla_pseudosequences.npy",
        )
    else:
        peptide_embeddings = np.load(root / "hla_peptides.npy")
        hla_embeddings = np.load(root / "hla_pseudosequences.npy")

    artifact_path = head_model_dir(model_id) / "hla_el_mlp.pt"
    result = train_hla_mlp(
        pairs_df=pairs,
        peptide_embeddings=peptide_embeddings,
        hla_embeddings=hla_embeddings,
        artifact_path=artifact_path,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        patience=patience,
        metadata={
            "model_id": model_id,
            "head": "hla_el",
            "embedding_pair_table": str(root / "hla_el_pairs.parquet"),
            "peptide_embedding_matrix": str(root / "hla_peptides.npy"),
            "hla_embedding_matrix": str(root / "hla_pseudosequences.npy"),
            "thresholds": {"fail": 0.70, "caution": 0.35},
            "scope": "EL binary/soft-binary presentation-risk head only",
            "limit_per_split": limit if limit > 0 else None,
            "compacted_embedding_rows": bool(limit > 0),
        },
    )
    write_json(head_model_dir(model_id) / "hla_el.metrics.json", result)
    write_json(MANIFEST_DIR / "hla_el_head.json", result)
    return result


@app.function(
    gpu=LIGHT_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=2 * 60 * 60,
)
def train_solubility(model_id: str = DEFAULT_ESM2_MODEL_ID) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs([HEAD_ROOT, head_model_dir(model_id), MANIFEST_DIR])
    result = _train_solubility_impl(model_id)
    model_volume.commit()
    data_volume.commit()
    return result


@app.function(
    gpu=LIGHT_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=2 * 60 * 60,
)
def train_apr(model_id: str = DEFAULT_ESM2_MODEL_ID) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs([HEAD_ROOT, head_model_dir(model_id), MANIFEST_DIR])
    result = _train_apr_impl(model_id)
    model_volume.commit()
    data_volume.commit()
    return result


@app.function(
    gpu=LIGHT_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def train_hla_el(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    epochs: int = 10,
    batch_size: int = 2048,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    patience: int = 2,
    limit: int = 0,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs([HEAD_ROOT, head_model_dir(model_id), MANIFEST_DIR])
    result = _train_hla_el_impl(
        model_id=model_id,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        patience=patience,
        limit=limit,
    )
    model_volume.commit()
    data_volume.commit()
    return result


@app.function(
    gpu=LIGHT_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def train_all(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    hla_epochs: int = 10,
    hla_batch_size: int = 2048,
    hla_limit: int = 0,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs([HEAD_ROOT, head_model_dir(model_id), MANIFEST_DIR])
    results = {
        "solubility": _train_solubility_impl(model_id),
        "apr": _train_apr_impl(model_id),
        "hla_el": _train_hla_el_impl(
            model_id=model_id,
            epochs=hla_epochs,
            batch_size=hla_batch_size,
            learning_rate=1e-3,
            weight_decay=1e-4,
            patience=2,
            limit=hla_limit,
        ),
    }
    model_volume.commit()
    data_volume.commit()
    return results


@app.function(
    volumes={"/models": model_volume.read_only()},
    timeout=10 * 60,
)
def list_artifacts(model_id: str = DEFAULT_ESM2_MODEL_ID) -> dict[str, Any]:
    model_volume.reload()
    root = head_model_dir(model_id)
    if not root.exists():
        result = {"model_id": model_id, "root": str(root), "files": []}
        print(json.dumps(result, indent=2), flush=True)
        return result
    files = [
        {
            "path": str(path),
            "relative_path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    result = {"model_id": model_id, "root": str(root), "files": files}
    print(json.dumps(result, indent=2), flush=True)
    return result


@app.local_entrypoint()
def main(
    action: str = "train-all",
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    hla_epochs: int = 10,
    hla_batch_size: int = 2048,
    hla_limit: int = 0,
) -> None:
    if action == "train-solubility":
        result = train_solubility.remote(model_id=model_id)
    elif action == "train-apr":
        result = train_apr.remote(model_id=model_id)
    elif action == "train-hla-el":
        result = train_hla_el.remote(
            model_id=model_id,
            epochs=hla_epochs,
            batch_size=hla_batch_size,
            limit=hla_limit,
        )
    elif action == "train-all":
        result = train_all.remote(
            model_id=model_id,
            hla_epochs=hla_epochs,
            hla_batch_size=hla_batch_size,
            hla_limit=hla_limit,
        )
    elif action == "list-artifacts":
        result = list_artifacts.remote(model_id=model_id)
    else:
        raise ValueError(f"Unknown action: {action}")
    print(json.dumps(result, indent=2))
