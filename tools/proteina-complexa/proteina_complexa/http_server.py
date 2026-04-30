from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .auth import assert_authorized
from .commands import normalize_design_steps, normalize_overrides, smoke_overrides
from .config import DEFAULT_BINDER_LENGTH, DEFAULT_PIPELINE_CONFIG
from .design import run_design
from .logging_utils import log_event
from .payloads import DesignPayload, WarmStartPayload, normalize_design_payload
from .runtime import local_weight_files
from .target_preprocessing import preprocess_target_structure
from .warm_start import resolve_seed_binder_chain

try:
    from fastapi import Request as FastAPIRequest
except ImportError:
    FastAPIRequest = Any


MAX_BACKEND_ERROR_DETAIL_CHARS = 24000


async def parse_request_payload(request: Any) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise ValueError("Request body must be application/json")
    payload = await request.json()
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def validate_batched_warm_start_controls(design_payload: DesignPayload) -> None:
    warm_starts = design_payload.warm_starts or ([design_payload.warm_start] if design_payload.warm_start else [])
    if len(warm_starts) <= 1:
        return
    for field_name in ("noise_level", "start_t", "num_steps"):
        values = [
            getattr(warm_start, field_name)
            for warm_start in warm_starts
            if getattr(warm_start, field_name) is not None
        ]
        if values and any(value != values[0] for value in values[1:]):
            raise ValueError(f"Batched warm starts require the same {field_name} for every seed")


def resolve_warm_start_chains(
    warm_starts: list[WarmStartPayload],
) -> tuple[list[WarmStartPayload], list[dict[str, Any]]]:
    resolved_warm_starts = []
    chain_resolutions = []
    for index, warm_start in enumerate(warm_starts):
        resolution = resolve_seed_binder_chain(
            seed_binder_text=warm_start.structure_text,
            seed_binder_chain=warm_start.chain,
        )
        resolved_warm_starts.append(replace(warm_start, chain=resolution.chain))
        chain_resolution = {
            "index": index,
            "filename": warm_start.filename,
            **resolution.to_json_dict(),
        }
        chain_resolutions.append(chain_resolution)
    return resolved_warm_starts, chain_resolutions


def run_design_payload(design_payload: DesignPayload) -> dict:
    validate_batched_warm_start_controls(design_payload)
    requested_warm_starts = design_payload.warm_starts or (
        [design_payload.warm_start] if design_payload.warm_start else []
    )
    log_event(
        "design_request_normalized",
        run_name=design_payload.run_name,
        pipeline_config=design_payload.pipeline_config,
        design_steps=design_payload.design_steps,
        smoke=design_payload.smoke,
        override_count=len(design_payload.overrides),
        target={
            "filename": design_payload.target.filename,
            "name": design_payload.target.target_name,
            "target_input": design_payload.target.target_input,
            "chains": design_payload.target.chains,
            "hotspot_residues": design_payload.target.hotspot_residues,
            "binder_length": design_payload.target.binder_length,
            "structure_chars": len(design_payload.target.structure_text),
        },
        warm_starts=[
            {
                "filename": warm_start.filename,
                "requested_chain": warm_start.chain,
                "structure_chars": len(warm_start.structure_text),
                "noise_level": warm_start.noise_level,
                "start_t": warm_start.start_t,
                "num_steps": warm_start.num_steps,
            }
            for warm_start in requested_warm_starts
        ],
    )
    warm_starts, warm_start_chain_resolutions = resolve_warm_start_chains(requested_warm_starts)
    if warm_start_chain_resolutions:
        log_event(
            "warm_start_chains_resolved",
            run_name=design_payload.run_name,
            warm_start_count=len(warm_starts),
            chain_resolutions=warm_start_chain_resolutions,
        )
    preprocessed = preprocess_target_structure(
        structure_text=design_payload.target.structure_text,
        structure_filename=design_payload.target.filename,
        target_name=design_payload.target.target_name,
        target_input=design_payload.target.target_input,
        chains=design_payload.target.chains,
        hotspot_residues=design_payload.target.hotspot_residues,
        binder_length=design_payload.target.binder_length,
    )
    log_event(
        "target_preprocessed",
        run_name=design_payload.run_name,
        target_name=preprocessed["target_name"],
        length=preprocessed.get("length"),
        target_residue_count=preprocessed.get("target_residue_count"),
        target_input=preprocessed.get("target_input"),
        chain_sequence_lengths={
            chain_id: len(sequence)
            for chain_id, sequence in (preprocessed.get("chain_sequences") or {}).items()
        },
        pdb_path=preprocessed.get("pdb_path"),
        target_tensor_info=preprocessed.get("target_tensor_info"),
    )
    target_overrides = [
        override
        for override in preprocessed["hydra_overrides"]
        if not override.startswith("++generation.task_name=")
    ]
    effective_steps = normalize_design_steps(design_payload.design_steps)
    request_overrides = normalize_overrides(design_payload.overrides)
    warm_start_count = len(warm_starts)
    mode_overrides: list[str] = []
    if design_payload.smoke:
        effective_steps = ["generate"]
        mode_overrides = smoke_overrides(sample_count=warm_start_count or 1)
    elif warm_start_count > 1:
        mode_overrides = [
            f"++generation.dataloader.batch_size={warm_start_count}",
            f"++generation.dataloader.dataset.nres.nsamples={warm_start_count}",
        ]

    run_kwargs: dict[str, Any] = {}
    if warm_start_count > 1:
        run_kwargs["seed_binders"] = [
            {
                "structure_text": warm_start.structure_text,
                "filename": warm_start.filename,
                "chain": warm_start.chain,
                "noise_level": warm_start.noise_level,
                "start_t": warm_start.start_t,
                "num_steps": warm_start.num_steps,
            }
            for warm_start in warm_starts
        ]
    else:
        warm_start = warm_starts[0] if warm_starts else None
        run_kwargs.update(
            {
                "seed_binder_text": warm_start.structure_text if warm_start else None,
                "seed_binder_filename": warm_start.filename if warm_start else "seed_binder.pdb",
                "seed_binder_chain": warm_start.chain if warm_start else None,
                "seed_binder_noise_level": warm_start.noise_level if warm_start else None,
                "seed_binder_start_t": warm_start.start_t if warm_start else None,
                "seed_binder_num_steps": warm_start.num_steps if warm_start else None,
            }
        )

    design = run_design(
        task_name=preprocessed["target_name"],
        run_name=design_payload.run_name,
        pipeline_config=design_payload.pipeline_config,
        overrides=[*target_overrides, *mode_overrides, *request_overrides],
        steps=effective_steps,
        include_generated_pdbs=True,
        **run_kwargs,
    )
    log_event(
        "design_request_completed",
        run_name=design_payload.run_name,
        task_name=preprocessed["target_name"],
        warm_start_count=warm_start_count,
        warm_start_mode=(design.get("warm_start") or {}).get("mode"),
        generated_count=design.get("count", 0),
        pdb_filename=design.get("pdb_filename"),
    )
    return {
        "run_name": design_payload.run_name,
        "task_name": preprocessed["target_name"],
        "mode": "smoke-cif" if design_payload.smoke else "design-cif",
        "warm_start_count": warm_start_count,
        "warm_start_chain_resolution": (
            warm_start_chain_resolutions[0]
            if len(warm_start_chain_resolutions) == 1
            else warm_start_chain_resolutions
        ),
        "preprocessed_target": preprocessed,
        "design": design,
        "format": "pdb",
        "count": design.get("count", 0),
        "pdbs": design.get("pdbs", []),
        "pdb_filename": design.get("pdb_filename"),
        "pdb": design.get("pdb"),
    }


def run_design_request(payload: dict[str, Any]) -> dict:
    design_payload = normalize_design_payload(
        payload,
        default_pipeline_config=DEFAULT_PIPELINE_CONFIG,
        default_binder_length=DEFAULT_BINDER_LENGTH,
    )
    return run_design_payload(design_payload)


def pdb_download_headers(filename: str) -> dict[str, str]:
    safe_filename = Path(filename).name or "proteina_complexa_prediction.pdb"
    return {"Content-Disposition": f'attachment; filename="{safe_filename}"'}


def pdb_file_payload(result: dict[str, Any]) -> tuple[str, str]:
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


def request_wants_pdb_file(request: Any, payload: dict[str, Any]) -> bool:
    path = getattr(getattr(request, "url", None), "path", "")
    if str(path).endswith(".pdb"):
        return True

    return_format = str(payload.get("return_format") or payload.get("format") or "").lower()
    if return_format in {"pdb", "file", "download"}:
        return True

    accept = request.headers.get("accept", "").lower()
    return "chemical/x-pdb" in accept or "application/octet-stream" in accept


def backend_failure_detail(exc: RuntimeError) -> dict[str, str]:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) > MAX_BACKEND_ERROR_DETAIL_CHARS:
        message = "...<truncated>\n" + message[-MAX_BACKEND_ERROR_DETAIL_CHARS:]
    return {
        "error": "Proteina-Complexa backend command failed",
        "message": message,
    }


def create_app():
    from fastapi import FastAPI, HTTPException, Response
    from starlette.concurrency import run_in_threadpool

    web_app = FastAPI(title="Proteina-Complexa Modal Design", version="1.0.0")

    @web_app.get("/health")
    async def health(request: FastAPIRequest) -> dict[str, Any]:
        assert_authorized(request.headers)
        return {"status": "ok", "weights": local_weight_files()}

    @web_app.post("/")
    @web_app.post("/design")
    @web_app.post("/predict")
    @web_app.post("/design.pdb")
    @web_app.post("/predict.pdb")
    async def design(request: FastAPIRequest) -> Any:
        assert_authorized(request.headers)
        path = str(getattr(getattr(request, "url", None), "path", ""))
        log_event("http_request_started", path=path)
        try:
            payload = await parse_request_payload(request)
            log_event(
                "http_payload_received",
                path=path,
                keys=sorted(payload),
                has_warm_start=any(
                    name in payload and payload[name] is not None
                    for name in ("warm_start", "warm_starts", "seed_binder", "seed_binders")
                ),
            )
            result = await run_in_threadpool(run_design_request, payload)
            if request_wants_pdb_file(request, payload):
                filename, pdb_text = pdb_file_payload(result)
                log_event(
                    "http_request_completed",
                    path=path,
                    response_format="pdb",
                    run_name=result.get("run_name"),
                    pdb_filename=filename,
                    pdb_chars=len(pdb_text),
                )
                return Response(
                    content=pdb_text,
                    media_type="chemical/x-pdb",
                    headers=pdb_download_headers(filename),
                )
            log_event(
                "http_request_completed",
                path=path,
                response_format="json",
                run_name=result.get("run_name"),
                count=result.get("count"),
                warm_start_count=result.get("warm_start_count"),
            )
            return result
        except ValueError as exc:
            log_event(
                "http_request_failed",
                path=path,
                status_code=400,
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            log_event(
                "http_request_failed",
                path=path,
                status_code=502,
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            raise HTTPException(status_code=502, detail=backend_failure_detail(exc)) from exc

    return web_app
