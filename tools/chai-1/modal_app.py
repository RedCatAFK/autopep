from __future__ import annotations

import base64
import hmac
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import modal

APP_NAME = "chai-1-inference"
SECRET_NAME = "chai-1-api-key"
API_KEY_ENV = "CHAI_API_KEY"

MODEL_VOLUME_NAME = "chai-1-models"
MODEL_DIR = Path("/models/chai-1")
CHAI_DOWNLOADS_DIR = MODEL_DIR / "downloads"
HF_HOME = MODEL_DIR / "huggingface"

GPU = "L40S"
TIMEOUT_SECONDS = 60 * 60
SCALEDOWN_WINDOW_SECONDS = 60

MAX_FASTA_BYTES = 128 * 1024


weights_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-runtime-ubuntu24.04",
        add_python="3.11",
    )
    .apt_install("git", "libgomp1")
    .pip_install(
        "torch==2.6.0",
        "chai_lab==0.6.1",
        "fastapi==0.115.12",
        "gemmi==0.6.3",
    )
    .env(
        {
            "CHAI_DOWNLOADS_DIR": str(CHAI_DOWNLOADS_DIR),
            "HF_HOME": str(HF_HOME),
            "TRANSFORMERS_CACHE": str(HF_HOME / "transformers"),
            "PYTHONUNBUFFERED": "1",
        }
    )
)

app = modal.App(APP_NAME, image=image)


CHAI_COMPONENTS = (
    "feature_embedding.pt",
    "token_embedder.pt",
    "trunk.pt",
    "diffusion_module.pt",
    "confidence_head.pt",
    "bond_loss_input_proj.pt",
)


def _expected_weight_paths() -> list[Path]:
    return [
        CHAI_DOWNLOADS_DIR / "models_v2" / component for component in CHAI_COMPONENTS
    ] + [
        CHAI_DOWNLOADS_DIR / "conformers_v1.apkl",
        CHAI_DOWNLOADS_DIR / "esm" / "traced_sdpa_esm2_t36_3B_UR50D_fp16.pt",
    ]


def _ensure_model_assets() -> None:
    os.environ.setdefault("CHAI_DOWNLOADS_DIR", str(CHAI_DOWNLOADS_DIR))
    os.environ.setdefault("HF_HOME", str(HF_HOME))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(HF_HOME / "transformers"))

    CHAI_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HF_HOME.mkdir(parents=True, exist_ok=True)

    weights_volume.reload()
    missing_paths = [path for path in _expected_weight_paths() if not path.exists()]
    if not missing_paths:
        return

    from chai_lab.data.dataset.embeddings.esm import ESM_URL
    from chai_lab.utils.paths import (
        cached_conformers,
        chai1_component,
        download_if_not_exists,
    )

    cached_conformers.get_path()
    for component in CHAI_COMPONENTS:
        chai1_component(component)

    download_if_not_exists(
        ESM_URL,
        CHAI_DOWNLOADS_DIR / "esm" / "traced_sdpa_esm2_t36_3B_UR50D_fp16.pt",
    )

    weights_volume.commit()


def _normalise_fasta(fasta: str) -> str:
    fasta = fasta.strip()
    if not fasta:
        raise ValueError("FASTA input is empty")
    if len(fasta.encode("utf-8")) > MAX_FASTA_BYTES:
        raise ValueError(f"FASTA input exceeds {MAX_FASTA_BYTES} bytes")
    if not fasta.startswith(">"):
        raise ValueError(
            "FASTA input must start with a FASTA header line beginning with '>'"
        )
    return fasta + "\n"


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

    for candidate in _candidate_api_keys(headers):
        if hmac.compare_digest(candidate, expected):
            return

    from fastapi import HTTPException

    raise HTTPException(
        status_code=401,
        detail="Missing or invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _as_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc

    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _as_bool(value: Any, *, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


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


def _convert_cif_to_pdb(cif_path: Path, pdb_path: Path) -> None:
    import gemmi

    structure = gemmi.read_structure(str(cif_path))
    structure.write_pdb(str(pdb_path))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ranked_pdb_payload(
    *,
    candidates: Any,
    output_dir: Path,
    include_cif: bool,
) -> list[dict[str, Any]]:
    pdb_dir = output_dir / "pdb"
    pdb_dir.mkdir(parents=True, exist_ok=True)

    structures: list[dict[str, Any]] = []
    for rank, cif_path in enumerate(candidates.cif_paths, start=1):
        cif_path = Path(cif_path)
        pdb_name = f"rank_{rank}_{cif_path.stem}.pdb"
        pdb_path = pdb_dir / pdb_name
        _convert_cif_to_pdb(cif_path, pdb_path)

        score = None
        if hasattr(candidates, "ranking_data"):
            ranking_item = candidates.ranking_data[rank - 1]
            if hasattr(ranking_item, "aggregate_score"):
                score_value = ranking_item.aggregate_score
                if hasattr(score_value, "item"):
                    score_value = score_value.item()
                score = _safe_float(score_value)

        mean_plddt = None
        if hasattr(candidates, "plddt"):
            plddt_value = candidates.plddt[rank - 1]
            if hasattr(plddt_value, "mean"):
                plddt_value = plddt_value.mean()
            if hasattr(plddt_value, "item"):
                plddt_value = plddt_value.item()
            mean_plddt = _safe_float(plddt_value)

        item: dict[str, Any] = {
            "rank": rank,
            "filename": pdb_name,
            "pdb": pdb_path.read_text(),
            "aggregate_score": score,
            "mean_plddt": mean_plddt,
        }
        if include_cif:
            item["cif_filename"] = cif_path.name
            item["cif"] = cif_path.read_text()
        structures.append(item)

    return structures


def _run_chai_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    from chai_lab.chai1 import run_inference

    fasta = _normalise_fasta(str(payload.get("fasta", "")))
    num_trunk_recycles = _as_int(
        payload.get("num_trunk_recycles"),
        default=3,
        minimum=1,
        maximum=20,
        field_name="num_trunk_recycles",
    )
    num_diffn_timesteps = _as_int(
        payload.get("num_diffn_timesteps"),
        default=200,
        minimum=1,
        maximum=1000,
        field_name="num_diffn_timesteps",
    )
    num_diffn_samples = _as_int(
        payload.get("num_diffn_samples"),
        default=5,
        minimum=1,
        maximum=10,
        field_name="num_diffn_samples",
    )
    seed = _as_int(
        payload.get("seed"),
        default=42,
        minimum=0,
        maximum=2**31 - 1,
        field_name="seed",
    )
    include_cif = _as_bool(
        payload.get("include_cif"), default=False, field_name="include_cif"
    )

    work_dir = Path(tempfile.mkdtemp(prefix=f"chai-{uuid4().hex}-"))
    try:
        fasta_path = work_dir / "input.fasta"
        output_dir = work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=False)
        fasta_path.write_text(fasta)

        candidates = run_inference(
            fasta_file=fasta_path,
            output_dir=output_dir,
            num_trunk_recycles=num_trunk_recycles,
            num_diffn_timesteps=num_diffn_timesteps,
            seed=seed,
            device="cuda",
            use_esm_embeddings=True,
            use_msa_server=False,
            msa_directory=None,
            use_templates_server=False,
            template_hits_path=None,
            recycle_msa_subsample=0,
            num_diffn_samples=num_diffn_samples,
        )

        candidates = candidates.sorted()
        pdbs = _ranked_pdb_payload(
            candidates=candidates,
            output_dir=output_dir,
            include_cif=include_cif,
        )

        return {
            "format": "pdb",
            "count": len(pdbs),
            "pdbs": pdbs,
            "parameters": {
                "num_trunk_recycles": num_trunk_recycles,
                "num_diffn_timesteps": num_diffn_timesteps,
                "num_diffn_samples": num_diffn_samples,
                "seed": seed,
                "use_msa": False,
                "use_templates": False,
                "use_esm_embeddings": True,
            },
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.function(
    gpu=GPU,
    volumes={str(MODEL_DIR): weights_volume},
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    min_containers=0,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=TIMEOUT_SECONDS,
)
@modal.asgi_app()
def fastapi_app():
    from fastapi import FastAPI, HTTPException, Request

    _ensure_model_assets()
    web_app = FastAPI(title="Chai-1 Modal Inference", version="1.0.0")

    @web_app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        _assert_authorized(request.headers)
        return {"status": "ok"}

    @web_app.post("/")
    @web_app.post("/predict")
    async def predict(request: Request) -> dict[str, Any]:
        _assert_authorized(request.headers)
        try:
            payload = await _parse_request_payload(request)
            return _run_chai_prediction(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return web_app
