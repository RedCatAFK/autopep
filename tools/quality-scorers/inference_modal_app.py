from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal

from training.constants import (
    DATA_VOLUME_NAME,
    DEFAULT_ESM2_MODEL_ID,
    HF_HOME,
    MODEL_VOLUME_NAME,
    embedding_model_dir,
    esm2_local_dir,
    head_model_dir,
)
from training.datasets import allele_alias_key, parse_fasta, parse_pseudosequence_text
from training.embedding import embed_sequences
from training.heads import build_hla_mlp
from training.io_utils import invalid_tokens, is_valid_sequence, normalize_sequence

try:
    from fastapi import Request as FastAPIRequest
except ImportError:
    FastAPIRequest = Any


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("quality-scorers-inference")

APP_NAME = "quality-scorers-inference"
SECRET_NAME = "quality-scorers-api-key"
API_KEY_ENV = "QUALITY_SCORERS_API_KEY"

GPU = "T4"
TIMEOUT_SECONDS = 60 * 60
SCALEDOWN_WINDOW_SECONDS = 60
MAX_FASTA_BYTES = 128 * 1024
ESM_BATCH_SIZE = 256
MAX_HLA_PAIRS = 50000
HLA_FEATURE_BATCH_SIZE = 4096

MHC_I_PANEL = (
    "HLA-A*01:01",
    "HLA-A*02:01",
    "HLA-A*03:01",
    "HLA-A*24:02",
    "HLA-B*07:02",
    "HLA-B*08:01",
    "HLA-B*15:01",
    "HLA-B*40:01",
    "HLA-C*07:01",
    "HLA-C*07:02",
)
MHC_II_PANEL = (
    "HLA-DRB1*01:01",
    "HLA-DRB1*03:01",
    "HLA-DRB1*04:01",
    "HLA-DRB1*07:01",
    "HLA-DRB1*11:01",
    "HLA-DRB1*13:01",
    "HLA-DRB1*15:01",
    "HLA-DPA1*01:03/DPB1*02:01",
    "HLA-DQA1*05:01/DQB1*02:01",
    "HLA-DQA1*03:01/DQB1*03:02",
)


model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)
data_volume = modal.Volume.from_name(DATA_VOLUME_NAME, create_if_missing=True)
api_secret = modal.Secret.from_name(SECRET_NAME)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-runtime-ubuntu24.04",
        add_python="3.11",
    )
    .apt_install("ca-certificates")
    .pip_install(
        "fastapi==0.115.12",
        "joblib==1.4.2",
        "numpy==2.2.4",
        "pandas==2.2.3",
        "pyarrow==19.0.1",
        "safetensors==0.5.3",
        "scikit-learn==1.6.1",
        "torch==2.6.0",
        "transformers==4.51.3",
    )
    .env(
        {
            "HF_HOME": str(HF_HOME),
            "TRANSFORMERS_CACHE": str(HF_HOME / "transformers"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    .add_local_python_source("training")
)

app = modal.App(APP_NAME, image=image)


@dataclass(frozen=True)
class ParsedFasta:
    name: str
    sequence: str


@dataclass(frozen=True)
class HlaTarget:
    requested: str
    allele: str
    mhc_class: str
    pseudosequence: str


@dataclass
class Runtime:
    model_id: str
    tokenizer: Any
    esm_model: Any
    device: str
    solubility_head: dict[str, Any]
    apr_head: dict[str, Any]
    hla_model: Any
    hla_targets: list[HlaTarget]


def _expected_paths(model_id: str) -> list[Path]:
    esm_dir = esm2_local_dir(model_id)
    head_dir = head_model_dir(model_id)
    return [
        esm_dir / "config.json",
        esm_dir / "model.safetensors",
        esm_dir / "special_tokens_map.json",
        esm_dir / "tokenizer_config.json",
        esm_dir / "vocab.txt",
        head_dir / "solubility.joblib",
        head_dir / "apr.joblib",
        head_dir / "hla_el_mlp.pt",
    ]


def _assert_artifacts_present(model_id: str) -> None:
    missing = [str(path) for path in _expected_paths(model_id) if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Quality scorer inference artifacts are incomplete. "
            "Run the ESM2 embedding and head training jobs first. Missing: "
            + ", ".join(missing)
        )


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


async def _parse_request_payload(request: Any) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        payload = await request.json()
        if isinstance(payload, str):
            return {"fasta": payload}
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object or a FASTA string")
        return payload

    body = await request.body()
    try:
        fasta = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Request body must be UTF-8 FASTA text") from exc
    return {"fasta": fasta}


def _parse_single_fasta(fasta: str) -> ParsedFasta:
    fasta = str(fasta).strip()
    if not fasta:
        raise ValueError("FASTA input is empty")
    if len(fasta.encode("utf-8")) > MAX_FASTA_BYTES:
        raise ValueError(f"FASTA input exceeds {MAX_FASTA_BYTES} bytes")
    if not fasta.startswith(">"):
        raise ValueError("FASTA input must start with a header line beginning with '>'")

    records = parse_fasta(fasta)
    if len(records) != 1:
        raise ValueError("FASTA input must contain exactly one sequence record")

    record = records[0]
    sequence = normalize_sequence(record.sequence)
    if not sequence:
        raise ValueError("FASTA sequence is empty")
    if not is_valid_sequence(sequence):
        tokens = "".join(sorted(invalid_tokens(sequence)))
        raise ValueError(f"FASTA sequence contains unsupported amino-acid tokens: {tokens}")
    return ParsedFasta(name=record.header or "sequence", sequence=sequence)


def _sliding_windows(sequence: str, lengths: tuple[int, ...] | list[int]):
    for length in lengths:
        if len(sequence) < length:
            continue
        for start in range(len(sequence) - length + 1):
            yield start, start + length, sequence[start : start + length]


def _top_mean(values: list[float], *, k: int) -> float:
    if not values:
        return 0.0
    return float(sum(sorted(values, reverse=True)[:k]) / min(k, len(values)))


def _aggregate_hla_scores(scores: list[float]) -> float:
    if not scores:
        return 0.0
    max_score = float(max(scores))
    top20_mean = _top_mean([float(score) for score in scores], k=20)
    num_high = sum(float(score) >= 0.80 for score in scores)
    return float(0.5 * max_score + 0.3 * top20_mean + 0.2 * min(num_high / 10, 1.0))


def _head_probability(head_artifact: dict[str, Any], embeddings) -> list[float]:
    logits = head_artifact["pipeline"].decision_function(embeddings).reshape(-1, 1)
    return head_artifact["calibrator"].predict_proba(logits)[:, 1].astype(float).tolist()


def _resolve_hla_targets(model_id: str) -> list[HlaTarget]:
    import pandas as pd

    aliases: dict[str, tuple[str, str]] = {}
    table_path = embedding_model_dir(model_id) / "hla_pseudosequences.parquet"
    if table_path.exists():
        table = pd.read_parquet(table_path)
        aliases.update(
            {
                allele_alias_key(str(row.allele)): (str(row.allele), str(row.hla_pseudosequence))
                for row in table.itertuples(index=False)
            }
        )

    for path in Path("/data/raw/hla").rglob("*"):
        if not path.is_file():
            continue
        if path.name.lower() not in {"mhc_pseudo.dat", "pseudosequence.2016.all.x.dat"}:
            continue
        for allele, pseudosequence in parse_pseudosequence_text(path.read_text(errors="replace")).items():
            aliases.setdefault(allele_alias_key(allele), (allele, pseudosequence))

    if not aliases:
        raise RuntimeError(
            "No HLA pseudo-sequence metadata found. Expected either "
            f"{table_path} or raw DTU pseudo-sequence files under /data/raw/hla."
        )

    targets: list[HlaTarget] = []
    missing: list[str] = []
    for mhc_class, panel in (("MHC-I", MHC_I_PANEL), ("MHC-II", MHC_II_PANEL)):
        for requested in panel:
            resolved = aliases.get(allele_alias_key(requested))
            if resolved is None:
                missing.append(requested)
                continue
            allele, pseudosequence = resolved
            targets.append(
                HlaTarget(
                    requested=requested,
                    allele=allele,
                    mhc_class=mhc_class,
                    pseudosequence=pseudosequence,
                )
            )
    if missing:
        logger.warning("HLA panel alleles not found in trained metadata: %s", missing)
    if not targets:
        raise RuntimeError("No fixed HLA panel alleles resolved against trained HLA metadata")
    return targets


def _load_runtime(model_id: str = DEFAULT_ESM2_MODEL_ID) -> Runtime:
    import joblib
    import torch
    from transformers import AutoModel, AutoTokenizer

    started_at = time.perf_counter()
    model_volume.reload()
    data_volume.reload()
    _assert_artifacts_present(model_id)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(str(esm2_local_dir(model_id)))
    esm_model = AutoModel.from_pretrained(str(esm2_local_dir(model_id)), use_safetensors=True).to(device)
    esm_model.eval()

    head_dir = head_model_dir(model_id)
    solubility_head = joblib.load(head_dir / "solubility.joblib")
    apr_head = joblib.load(head_dir / "apr.joblib")

    hla_artifact = torch.load(head_dir / "hla_el_mlp.pt", map_location=device, weights_only=True)
    hla_model = build_hla_mlp(int(hla_artifact["config"]["input_dim"])).to(device)
    hla_model.load_state_dict(hla_artifact["state_dict"])
    hla_model.eval()

    runtime = Runtime(
        model_id=model_id,
        tokenizer=tokenizer,
        esm_model=esm_model,
        device=device,
        solubility_head=solubility_head,
        apr_head=apr_head,
        hla_model=hla_model,
        hla_targets=_resolve_hla_targets(model_id),
    )
    logger.info(
        "quality scorer runtime loaded; model_id=%s hla_targets=%d device=%s elapsed_seconds=%.2f",
        model_id,
        len(runtime.hla_targets),
        device,
        time.perf_counter() - started_at,
    )
    return runtime


def _embed(runtime: Runtime, sequences: list[str], *, batch_size: int = ESM_BATCH_SIZE):
    return embed_sequences(
        sequences,
        model=runtime.esm_model,
        tokenizer=runtime.tokenizer,
        device=runtime.device,
        batch_size=batch_size,
    )


def _score_solubility(runtime: Runtime, sequence: str) -> float:
    embedding = _embed(runtime, [sequence])
    return float(_head_probability(runtime.solubility_head, embedding)[0])


def _score_apr(runtime: Runtime, sequence: str) -> float:
    windows = [window for _start, _end, window in _sliding_windows(sequence, (6,))]
    if not windows:
        return 0.0
    unique_windows = sorted(set(windows))
    embeddings = _embed(runtime, unique_windows)
    scores = dict(zip(unique_windows, _head_probability(runtime.apr_head, embeddings), strict=True))
    return float(max(scores[window] for window in windows))


def _score_hla(runtime: Runtime, sequence: str) -> float:
    peptide_records = [
        (start, end, peptide, "MHC-I")
        for start, end, peptide in _sliding_windows(sequence, (8, 9, 10, 11))
    ] + [
        (start, end, peptide, "MHC-II")
        for start, end, peptide in _sliding_windows(sequence, (15,))
    ]
    if not peptide_records:
        return 0.0

    targets_by_class = {
        "MHC-I": [target for target in runtime.hla_targets if target.mhc_class == "MHC-I"],
        "MHC-II": [target for target in runtime.hla_targets if target.mhc_class == "MHC-II"],
    }
    pair_count = sum(len(targets_by_class[mhc_class]) for *_unused, mhc_class in peptide_records)
    if pair_count > MAX_HLA_PAIRS:
        raise ValueError(
            f"HLA scan would create {pair_count} peptide-HLA pairs; maximum is {MAX_HLA_PAIRS}"
        )

    import torch

    unique_peptides = sorted({record[2] for record in peptide_records})
    unique_hla = sorted({target.pseudosequence for target in runtime.hla_targets})
    peptide_embeddings_np = _embed(runtime, unique_peptides)
    hla_embeddings_np = _embed(runtime, unique_hla)
    peptide_embeddings = {
        peptide: torch.as_tensor(peptide_embeddings_np[index], dtype=torch.float32, device=runtime.device)
        for index, peptide in enumerate(unique_peptides)
    }
    hla_embeddings = {
        hla: torch.as_tensor(hla_embeddings_np[index], dtype=torch.float32, device=runtime.device)
        for index, hla in enumerate(unique_hla)
    }

    scores: list[float] = []
    feature_batch = []
    with torch.inference_mode():
        def flush_feature_batch() -> None:
            if not feature_batch:
                return
            feature_tensor = torch.stack(feature_batch)
            batch_scores = torch.sigmoid(runtime.hla_model(feature_tensor).squeeze(-1)).detach().cpu().tolist()
            scores.extend(float(score) for score in batch_scores)
            feature_batch.clear()

        for _start, _end, peptide, mhc_class in peptide_records:
            pep = peptide_embeddings[peptide]
            for target in targets_by_class[mhc_class]:
                hla = hla_embeddings[target.pseudosequence]
                feature_batch.append(torch.cat([pep, hla, torch.abs(pep - hla), pep * hla], dim=-1))
                if len(feature_batch) >= HLA_FEATURE_BATCH_SIZE:
                    flush_feature_batch()
        flush_feature_batch()

    return _aggregate_hla_scores(scores)


def _score_sequence(runtime: Runtime, sequence: str) -> dict[str, float]:
    solubility = _score_solubility(runtime, sequence)
    apr = _score_apr(runtime, sequence)
    hla = _score_hla(runtime, sequence)
    return {
        "solubility": solubility,
        "aggregation_apr": apr,
        "hla_presentation_risk": hla,
    }


@app.function(
    gpu=GPU,
    volumes={
        "/models": model_volume.read_only(),
        "/data": data_volume.read_only(),
    },
    secrets=[api_secret],
    min_containers=0,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=TIMEOUT_SECONDS,
)
@modal.asgi_app()
def fastapi_app():
    from fastapi import FastAPI, HTTPException

    runtime = _load_runtime()
    web_app = FastAPI(title="Quality Scorers Modal Inference", version="1.0.0")

    @web_app.get("/health")
    async def health(request: FastAPIRequest) -> dict[str, str]:
        _assert_authorized(request.headers)
        return {"status": "ok"}

    @web_app.post("/")
    @web_app.post("/predict")
    async def predict(request: FastAPIRequest) -> dict[str, dict[str, float]]:
        route_started_at = time.perf_counter()
        _assert_authorized(request.headers)
        try:
            payload = await _parse_request_payload(request)
            parsed = _parse_single_fasta(str(payload.get("fasta", "")))
            scores = _score_sequence(runtime, parsed.sequence)
            logger.info(
                "quality scorer request completed; name=%s length=%d elapsed_seconds=%.2f",
                parsed.name,
                len(parsed.sequence),
                time.perf_counter() - route_started_at,
            )
            return {"scores": scores}
        except ValueError as exc:
            logger.warning("quality scorer request rejected: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            logger.exception("quality scorer request failed")
            raise

    return web_app
