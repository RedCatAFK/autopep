from __future__ import annotations

from pathlib import Path
from typing import Any


def binary_metrics(y_true, y_score, *, threshold: float = 0.5) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import (
        average_precision_score,
        balanced_accuracy_score,
        brier_score_loss,
        matthews_corrcoef,
        roc_auc_score,
    )

    y_true_arr = np.asarray(y_true, dtype=float)
    y_hard = (y_true_arr >= threshold).astype(int)
    y_score_arr = np.asarray(y_score, dtype=float)
    y_pred = (y_score_arr >= threshold).astype(int)

    metrics: dict[str, Any] = {
        "n": int(y_true_arr.shape[0]),
        "positive_fraction": float(y_hard.mean()) if y_hard.size else None,
    }
    if len(set(y_hard.tolist())) > 1:
        metrics["auroc"] = float(roc_auc_score(y_hard, y_score_arr))
        metrics["auprc"] = float(average_precision_score(y_hard, y_score_arr))
        metrics["balanced_accuracy"] = float(balanced_accuracy_score(y_hard, y_pred))
        metrics["mcc"] = float(matthews_corrcoef(y_hard, y_pred))
    else:
        metrics["auroc"] = None
        metrics["auprc"] = None
        metrics["balanced_accuracy"] = None
        metrics["mcc"] = None
    metrics["brier"] = float(brier_score_loss(y_hard, y_score_arr.clip(0.0, 1.0)))
    return metrics


def train_sklearn_logistic_head(
    *,
    train_x,
    train_y,
    valid_x,
    valid_y,
    test_x,
    test_y,
    artifact_path: Path,
    C: float,
    class_weight: str = "balanced",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logreg",
                LogisticRegression(
                    C=C,
                    class_weight=class_weight,
                    max_iter=2000,
                    solver="lbfgs",
                ),
            ),
        ]
    )
    pipeline.fit(train_x, train_y)

    valid_logits = pipeline.decision_function(valid_x).reshape(-1, 1)
    calibrator = LogisticRegression(max_iter=1000, solver="lbfgs")
    calibrator.fit(valid_logits, valid_y)

    def calibrated_scores(x):
        logits = pipeline.decision_function(x).reshape(-1, 1)
        return calibrator.predict_proba(logits)[:, 1]

    train_scores = calibrated_scores(train_x)
    valid_scores = calibrated_scores(valid_x)
    test_scores = calibrated_scores(test_x)

    metrics = {
        "train": binary_metrics(train_y, train_scores),
        "valid": binary_metrics(valid_y, valid_scores),
        "test": binary_metrics(test_y, test_scores),
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": pipeline,
            "calibrator": calibrator,
            "metadata": metadata or {},
            "metrics": metrics,
        },
        artifact_path,
    )
    return {
        "artifact_path": str(artifact_path),
        "metrics": metrics,
        "train_rows": int(np.asarray(train_y).shape[0]),
        "valid_rows": int(np.asarray(valid_y).shape[0]),
        "test_rows": int(np.asarray(test_y).shape[0]),
    }


def build_hla_mlp(input_dim: int):
    import torch

    return torch.nn.Sequential(
        torch.nn.Linear(input_dim, 512),
        torch.nn.GELU(),
        torch.nn.Dropout(0.1),
        torch.nn.Linear(512, 128),
        torch.nn.GELU(),
        torch.nn.Dropout(0.1),
        torch.nn.Linear(128, 1),
    )


def train_hla_mlp(
    *,
    pairs_df,
    peptide_embeddings,
    hla_embeddings,
    artifact_path: Path,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
    patience: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import numpy as np
    import torch
    from torch.utils.data import DataLoader, Dataset

    device = "cuda" if torch.cuda.is_available() else "cpu"
    peptide_tensor = torch.as_tensor(peptide_embeddings, dtype=torch.float32, device=device)
    hla_tensor = torch.as_tensor(hla_embeddings, dtype=torch.float32, device=device)

    frames = {
        split: pairs_df[pairs_df["split"] == split].reset_index(drop=True)
        for split in ("train", "valid", "test")
    }
    missing = [split for split, frame in frames.items() if frame.empty]
    if missing:
        raise ValueError(f"HLA training requires non-empty train/valid/test splits; missing {missing}")

    def collate(batch):
        peptide_idx = torch.as_tensor([item[0] for item in batch], dtype=torch.long, device=device)
        hla_idx = torch.as_tensor([item[1] for item in batch], dtype=torch.long, device=device)
        targets = torch.as_tensor([item[2] for item in batch], dtype=torch.float32, device=device)
        pep = peptide_tensor[peptide_idx]
        hla = hla_tensor[hla_idx]
        features = torch.cat([pep, hla, torch.abs(pep - hla), pep * hla], dim=-1)
        return features, targets

    class BoundPairDataset(Dataset):
        def __init__(self, frame):
            self.peptide_idx = frame["peptide_idx"].to_numpy(dtype=np.int64)
            self.hla_idx = frame["hla_idx"].to_numpy(dtype=np.int64)
            self.target = frame["target"].to_numpy(dtype=np.float32)

        def __len__(self):
            return int(self.peptide_idx.shape[0])

        def __getitem__(self, index):
            return int(self.peptide_idx[index]), int(self.hla_idx[index]), float(self.target[index])

    datasets = {split: BoundPairDataset(frame) for split, frame in frames.items()}
    train_loader = DataLoader(
        datasets["train"],
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate,
    )
    eval_loaders = {
        split: DataLoader(datasets[split], batch_size=batch_size, shuffle=False, collate_fn=collate)
        for split in ("train", "valid", "test")
    }

    input_dim = int(peptide_embeddings.shape[1] * 4)
    model = build_hla_mlp(input_dim).to(device)
    hard_train = (frames["train"]["target"].to_numpy(dtype=float) >= 0.5).astype(int)
    positives = max(int(hard_train.sum()), 1)
    negatives = max(int(hard_train.shape[0] - hard_train.sum()), 1)
    criterion = torch.nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negatives / positives], dtype=torch.float32, device=device)
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )

    def predict(split: str) -> np.ndarray:
        model.eval()
        scores = []
        with torch.inference_mode():
            for features, _target in eval_loaders[split]:
                logits = model(features).squeeze(-1)
                scores.append(torch.sigmoid(logits).detach().cpu().numpy())
        return np.concatenate(scores, axis=0)

    best_state = None
    best_valid_auprc = -1.0
    stale_epochs = 0
    history: list[dict[str, Any]] = []

    for epoch in range(1, epochs + 1):
        model.train()
        losses = []
        for features, targets in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(features).squeeze(-1)
            loss = criterion(logits, targets)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))

        valid_scores = predict("valid")
        valid_metrics = binary_metrics(frames["valid"]["target"].to_numpy(), valid_scores)
        valid_auprc = valid_metrics["auprc"] if valid_metrics["auprc"] is not None else -1.0
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)) if losses else None,
                "valid": valid_metrics,
            }
        )
        if valid_auprc > best_valid_auprc:
            best_valid_auprc = valid_auprc
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    metrics = {
        split: binary_metrics(frames[split]["target"].to_numpy(), predict(split))
        for split in ("train", "valid", "test")
    }

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
            "config": {
                "input_dim": input_dim,
                "peptide_dim": int(peptide_embeddings.shape[1]),
                "architecture": "Linear(4d,512)-GELU-Dropout(0.1)-Linear(512,128)-GELU-Dropout(0.1)-Linear(128,1)",
            },
            "metadata": metadata or {},
            "metrics": metrics,
            "history": history,
        },
        artifact_path,
    )
    return {
        "artifact_path": str(artifact_path),
        "metrics": metrics,
        "history": history,
        "train_rows": int(frames["train"].shape[0]),
        "valid_rows": int(frames["valid"].shape[0]),
        "test_rows": int(frames["test"].shape[0]),
    }
