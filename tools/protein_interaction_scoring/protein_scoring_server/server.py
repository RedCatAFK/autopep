from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from .scorers.dscript_scorer import DScriptScorer
from .scorers.preprocessing import preprocess_structure
from .scorers.prodigy_scorer import ProdigyScorer
from .scorers.schemas import (
    AggregateIndicator,
    BatchSummary,
    DScriptResult,
    DScriptScore,
    ProdigyResult,
    ProdigyScore,
    ProteinSummary,
    ScoreBatchRequest,
    ScoreBatchResponse,
    ScoreItem,
    ScoreItemResult,
    ScoreSet,
    SequencePair,
)
from .scorers.utils import (
    DEFAULT_MAX_BATCH_SIZE,
    MAX_STRUCTURE_BYTES,
    StructureDecodeError,
    StructureTooLargeError,
    structure_extension,
    sequence_warnings,
    short_hash,
)


logger = logging.getLogger(__name__)
DEFAULT_API_KEY = "password123"


@dataclass
class PreparedItem:
    item: ScoreItem
    sequence_a: str | None = None
    sequence_b: str | None = None
    structure_path: Path | None = None
    structure_format: str | None = None
    chain_a: str | None = None
    chain_b: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class DScriptScorerProtocol(Protocol):
    def load(self) -> None: ...

    @property
    def is_loaded(self) -> bool: ...

    @property
    def is_available(self) -> bool: ...

    def score_batch(self, pairs: list[SequencePair]) -> dict[str, DScriptResult]: ...


class ProdigyScorerProtocol(Protocol):
    def load(self) -> None: ...

    @property
    def is_loaded(self) -> bool: ...

    @property
    def is_available(self) -> bool: ...

    def score_structure(
        self,
        item_id: str,
        structure_path: Path,
        *,
        structure_format: str = "pdb",
        chain_a: str | None = None,
        chain_b: str | None = None,
        temperature_celsius: float = 25.0,
    ) -> ProdigyResult: ...


class BatchScoringService:
    def __init__(
        self,
        *,
        dscript_scorer: DScriptScorerProtocol | None = None,
        prodigy_scorer: ProdigyScorerProtocol | None = None,
    ) -> None:
        self.dscript_scorer = dscript_scorer or DScriptScorer()
        self.prodigy_scorer = prodigy_scorer or ProdigyScorer()
        self._loaded = False

    def load(self) -> None:
        self.dscript_scorer.load()
        self.prodigy_scorer.load()
        self._loaded = True

    def health(self) -> dict[str, bool | str]:
        return {
            "status": "ok",
            "code_version": os.getenv("APP_VERSION", "local"),
            "dscript_loaded": self.dscript_scorer.is_loaded,
            "prodigy_available": self.prodigy_scorer.is_available,
            "gpu_available": gpu_available(),
        }

    def score_batch(self, request: ScoreBatchRequest) -> ScoreBatchResponse:
        if not self._loaded:
            self.load()

        if len(request.items) > DEFAULT_MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"batch size exceeds {DEFAULT_MAX_BATCH_SIZE} items",
            )

        options = request.options
        item_ids = [item.id for item in request.items]
        logger.info(
            "score_batch submitted=%s ids=%s run_dscript=%s run_prodigy=%s",
            len(request.items),
            item_ids,
            options.run_dscript,
            options.run_prodigy,
        )
        for item in request.items:
            logger.info(
                "item=%s sequence_a_len=%s sequence_a_hash=%s "
                "sequence_b_len=%s sequence_b_hash=%s structure_present=%s",
                item.id,
                len(item.protein_a.sequence or ""),
                short_hash(item.protein_a.sequence),
                len(item.protein_b.sequence or ""),
                short_hash(item.protein_b.sequence),
                item.structure is not None,
            )

        with tempfile.TemporaryDirectory(prefix="protein_scoring_batch_") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            prepared_items = self._prepare_items(request, temp_dir)

            dscript_started = time.perf_counter()
            dscript_results = self._score_dscript(request, prepared_items)
            logger.info(
                "dscript_runtime_seconds=%.3f", time.perf_counter() - dscript_started
            )

            prodigy_started = time.perf_counter()
            prodigy_results = self._score_prodigy(request, prepared_items)
            logger.info(
                "prodigy_runtime_seconds=%.3f", time.perf_counter() - prodigy_started
            )

            results = [
                self._merge_item_result(
                    prepared,
                    dscript_results[prepared.item.id],
                    prodigy_results[prepared.item.id],
                    request,
                )
                for prepared in prepared_items
            ]
        summary = BatchSummary(
            submitted=len(results),
            succeeded=sum(result.status == "ok" for result in results),
            partial=sum(result.status == "partial" for result in results),
            failed=sum(result.status == "failed" for result in results),
        )
        return ScoreBatchResponse(results=results, batch_summary=summary)

    def _prepare_items(
        self,
        request: ScoreBatchRequest,
        temp_dir: Path,
    ) -> list[PreparedItem]:
        prepared_items: list[PreparedItem] = []
        for index, item in enumerate(request.items):
            prepared = PreparedItem(
                item=item,
                sequence_a=item.protein_a.sequence,
                sequence_b=item.protein_b.sequence,
            )

            if item.structure is None:
                prepared_items.append(prepared)
                continue

            try:
                structure = preprocess_structure(
                    item,
                    temp_dir,
                    item_index=index,
                )
            except StructureTooLargeError as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            except StructureDecodeError as exc:
                prepared.errors.append(str(exc))
                prepared_items.append(prepared)
                continue
            except Exception as exc:
                prepared.errors.append(f"structure preprocessing failed: {exc}")
                prepared_items.append(prepared)
                continue

            prepared.structure_path = structure.scoring_path
            prepared.structure_format = structure.scoring_format
            prepared.chain_a = structure.chain_a
            prepared.chain_b = structure.chain_b
            prepared.warnings.extend(structure.warnings)
            prepared.errors.extend(structure.errors)

            extracted_a = (
                structure.sequences_by_chain.get(structure.chain_a)
                if structure.chain_a
                else None
            )
            extracted_b = (
                structure.sequences_by_chain.get(structure.chain_b)
                if structure.chain_b
                else None
            )
            if not prepared.sequence_a and extracted_a:
                prepared.sequence_a = extracted_a
                prepared.warnings.append(
                    f"protein_a.sequence was missing; extracted sequence from structure chain {structure.chain_a}"
                )
            elif prepared.sequence_a and extracted_a and prepared.sequence_a != extracted_a:
                prepared.warnings.append(
                    f"protein_a.sequence differs from structure chain {structure.chain_a}; using provided sequence"
                )

            if not prepared.sequence_b and extracted_b:
                prepared.sequence_b = extracted_b
                prepared.warnings.append(
                    f"protein_b.sequence was missing; extracted sequence from structure chain {structure.chain_b}"
                )
            elif prepared.sequence_b and extracted_b and prepared.sequence_b != extracted_b:
                prepared.warnings.append(
                    f"protein_b.sequence differs from structure chain {structure.chain_b}; using provided sequence"
                )

            prepared_items.append(prepared)
        return prepared_items

    def _score_dscript(
        self,
        request: ScoreBatchRequest,
        prepared_items: list[PreparedItem],
    ) -> dict[str, DScriptResult]:
        if not request.options.run_dscript:
            return {
                prepared.item.id: DScriptResult.unavailable(
                    "D-SCRIPT was not requested",
                    warnings=["D-SCRIPT scoring was disabled by options.run_dscript"],
                )
                for prepared in prepared_items
            }

        pairs = [
            SequencePair(
                item_id=prepared.item.id,
                protein_a_name=prepared.item.protein_a.name,
                sequence_a=prepared.sequence_a,
                protein_b_name=prepared.item.protein_b.name,
                sequence_b=prepared.sequence_b,
            )
            for prepared in prepared_items
        ]
        scored = self.dscript_scorer.score_batch(pairs)
        results: dict[str, DScriptResult] = {}
        for prepared in prepared_items:
            result = scored.get(prepared.item.id)
            if result is None:
                result = DScriptResult.unavailable(
                    "D-SCRIPT did not return a result for this item"
                )
            result.warnings.extend(sequence_warnings(prepared.sequence_a))
            result.warnings.extend(sequence_warnings(prepared.sequence_b))
            results[prepared.item.id] = result
            self._maybe_fail_fast(request, prepared.item.id, "dscript", result.errors)
        return results

    def _score_prodigy(
        self,
        request: ScoreBatchRequest,
        prepared_items: list[PreparedItem],
    ) -> dict[str, ProdigyResult]:
        if not request.options.run_prodigy:
            return {
                prepared.item.id: ProdigyResult.unavailable(
                    "PRODIGY was not requested",
                    temperature_celsius=request.options.temperature_celsius,
                    warnings=["PRODIGY scoring was disabled by options.run_prodigy"],
                )
                for prepared in prepared_items
            }

        results: dict[str, ProdigyResult] = {}
        for prepared in prepared_items:
            item = prepared.item
            if item.structure is None:
                result = ProdigyResult.unavailable(
                    "PRODIGY requires structure.content_base64 for this item",
                    temperature_celsius=request.options.temperature_celsius,
                )
                results[item.id] = result
                self._maybe_fail_fast(request, item.id, "prodigy", result.errors)
                continue

            if prepared.errors:
                result = ProdigyResult.unavailable(
                    "; ".join(prepared.errors),
                    temperature_celsius=request.options.temperature_celsius,
                    warnings=prepared.warnings,
                )
                results[item.id] = result
                self._maybe_fail_fast(request, item.id, "prodigy", result.errors)
                continue

            if prepared.structure_path is None:
                result = ProdigyResult.unavailable(
                    "structure preprocessing did not produce a scorable structure file",
                    temperature_celsius=request.options.temperature_celsius,
                    warnings=prepared.warnings,
                )
                results[item.id] = result
                self._maybe_fail_fast(request, item.id, "prodigy", result.errors)
                continue

            result = self.prodigy_scorer.score_structure(
                item.id,
                prepared.structure_path,
                structure_format=prepared.structure_format or item.structure.format,
                chain_a=prepared.chain_a,
                chain_b=prepared.chain_b,
                temperature_celsius=request.options.temperature_celsius,
            )
            results[item.id] = result
            self._maybe_fail_fast(request, item.id, "prodigy", result.errors)

        return results

    def _merge_item_result(
        self,
        prepared: PreparedItem,
        dscript_result: DScriptResult,
        prodigy_result: ProdigyResult,
        request: ScoreBatchRequest,
    ) -> ScoreItemResult:
        item = prepared.item
        errors: list[str] = []
        warnings: list[str] = list(prepared.warnings)
        if request.options.run_dscript:
            errors.extend(f"dscript: {error}" for error in dscript_result.errors)
        warnings.extend(dscript_result.warnings)
        if request.options.run_prodigy:
            errors.extend(f"prodigy: {error}" for error in prodigy_result.errors)
        warnings.extend(prodigy_result.warnings)

        status = item_status(
            dscript_available=dscript_result.available,
            prodigy_available=prodigy_result.available,
            run_dscript=request.options.run_dscript,
            run_prodigy=request.options.run_prodigy,
        )

        return ScoreItemResult(
            id=item.id,
            status=status,
            protein_a=ProteinSummary(name=item.protein_a.name),
            protein_b=ProteinSummary(name=item.protein_b.name),
            scores=ScoreSet(
                dscript=DScriptScore(
                    available=dscript_result.available,
                    interaction_probability=dscript_result.interaction_probability,
                    raw_score=dscript_result.raw_score,
                    model_name=dscript_result.model_name,
                    warnings=dscript_result.warnings,
                ),
                prodigy=ProdigyScore(
                    available=prodigy_result.available,
                    delta_g_kcal_per_mol=prodigy_result.delta_g_kcal_per_mol,
                    kd_molar=prodigy_result.kd_molar,
                    temperature_celsius=prodigy_result.temperature_celsius,
                    warnings=prodigy_result.warnings,
                ),
            ),
            aggregate=aggregate_indicator(dscript_result, prodigy_result),
            errors=errors,
            warnings=warnings,
        )

    def _maybe_fail_fast(
        self,
        request: ScoreBatchRequest,
        item_id: str,
        scorer_name: str,
        errors: list[str],
    ) -> None:
        if request.options.fail_fast and errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "id": item_id,
                    "scorer": scorer_name,
                    "errors": errors,
                },
            )


def item_status(
    *,
    dscript_available: bool,
    prodigy_available: bool,
    run_dscript: bool,
    run_prodigy: bool,
) -> str:
    requested = []
    if run_dscript:
        requested.append(dscript_available)
    if run_prodigy:
        requested.append(prodigy_available)

    if not requested:
        return "failed"
    if all(requested):
        return "ok"
    if any(requested):
        return "partial"
    return "failed"


def aggregate_indicator(
    dscript_result: DScriptResult,
    prodigy_result: ProdigyResult,
) -> AggregateIndicator:
    probability = dscript_result.interaction_probability
    delta_g = prodigy_result.delta_g_kcal_per_mol
    if (
        not dscript_result.available
        or not prodigy_result.available
        or probability is None
        or delta_g is None
    ):
        return AggregateIndicator(
            available=False,
            label="insufficient_data",
            notes="Both D-SCRIPT probability and PRODIGY delta G are required for the aggregate indicator.",
        )

    if probability >= 0.7 and delta_g <= -7.0:
        return AggregateIndicator(
            available=True,
            label="likely_binder",
            notes="D-SCRIPT suggests interaction and PRODIGY suggests favorable binding free energy.",
        )
    if probability >= 0.5 or delta_g <= -5.0:
        return AggregateIndicator(
            available=True,
            label="possible_binder",
            notes="At least one computational indicator supports possible binding.",
        )
    return AggregateIndicator(
        available=True,
        label="unlikely_binder",
        notes="Both computational indicators are below the configured binding thresholds.",
    )


def gpu_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def configured_api_key() -> str:
    return os.getenv("API_KEY", DEFAULT_API_KEY)


def require_api_key(request: Request) -> None:
    expected = configured_api_key()
    supplied = request.headers.get("x-api-key", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1].strip()

    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def request_from_multipart(request: Request) -> ScoreBatchRequest:
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"multipart form could not be parsed: {exc}",
        ) from exc

    payload_value = form.get("payload") or form.get("request")
    if payload_value is None or isinstance(payload_value, StarletteUploadFile):
        raise HTTPException(
            status_code=422,
            detail="multipart upload requires a JSON 'payload' form field",
        )

    try:
        payload: dict[str, Any] = json.loads(str(payload_value))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"payload is not valid JSON: {exc}",
        ) from exc

    uploads: list[tuple[str, StarletteUploadFile]] = []
    files_by_key: dict[str, StarletteUploadFile] = {}
    for key, value in form.multi_items():
        if not isinstance(value, StarletteUploadFile):
            continue
        uploads.append((key, value))
        files_by_key[key] = value
        if value.filename:
            files_by_key[value.filename] = value
            files_by_key[Path(value.filename).name] = value
            files_by_key[Path(value.filename).stem] = value

    items = payload.get("items")
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="payload.items must be a list")

    for item in items:
        if not isinstance(item, dict):
            continue
        structure = item.get("structure")
        upload = find_upload_for_item(
            item,
            structure if isinstance(structure, dict) else None,
            uploads,
            files_by_key,
            allow_single_upload_fallback=len(items) == 1,
        )
        if upload is None:
            continue

        if not isinstance(structure, dict):
            structure = {}
            item["structure"] = structure

        content = await upload.read()
        if len(content) > MAX_STRUCTURE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"uploaded structure exceeds {MAX_STRUCTURE_BYTES} bytes",
            )
        if not content.strip():
            raise HTTPException(status_code=422, detail="uploaded structure is empty")

        structure["content_base64"] = base64.b64encode(content).decode("ascii")
        structure.pop("file_field", None)
        structure.pop("filename", None)
        if not structure.get("format"):
            structure["format"] = infer_structure_format_from_name(
                upload.filename or ""
            )

    try:
        return ScoreBatchRequest.model_validate(payload)
    except ValidationError as exc:
        status_code = 413 if validation_error_details_are_oversized(exc.errors()) else 422
        raise HTTPException(
            status_code=status_code,
            detail=jsonable_encoder(exc.errors()),
        ) from exc


def find_upload_for_item(
    item: dict[str, Any],
    structure: dict[str, Any] | None,
    uploads: list[tuple[str, StarletteUploadFile]],
    files_by_key: dict[str, StarletteUploadFile],
    *,
    allow_single_upload_fallback: bool,
) -> StarletteUploadFile | None:
    candidates: list[str] = []
    if structure:
        candidates.extend(
            str(value)
            for value in (
                structure.get("file_field"),
                structure.get("filename"),
                structure.get("file"),
            )
            if value
        )
        if structure.get("content_base64"):
            return None

    item_id = str(item.get("id", ""))
    if item_id:
        candidates.extend(
            [
                item_id,
                f"{item_id}.pdb",
                f"{item_id}.cif",
                f"{item_id}.mmcif",
                f"{item_id}_structure",
                f"{item_id}_structure.pdb",
                f"{item_id}_structure.cif",
                f"{item_id}_structure.mmcif",
            ]
        )

    for candidate in candidates:
        upload = files_by_key.get(candidate)
        if upload is not None:
            return upload

    if allow_single_upload_fallback and len(uploads) == 1:
        return uploads[0][1]
    return None


def infer_structure_format_from_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdb":
        return "pdb"
    if suffix == ".cif":
        return "cif"
    if suffix == ".mmcif":
        return "mmcif"
    try:
        return structure_extension(filename).lstrip(".")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="could not infer structure format; include structure.format as pdb, cif, or mmcif",
        ) from None


def create_app(
    *,
    service: BatchScoringService | None = None,
    load_on_startup: bool = True,
) -> FastAPI:
    scoring_service = service or BatchScoringService()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if load_on_startup:
            scoring_service.load()
        yield

    app = FastAPI(
        title="Protein Interaction Scoring API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        status_code = 413 if validation_error_is_oversized(exc) else 422
        return JSONResponse(
            status_code=status_code,
            content=jsonable_encoder({"detail": exc.errors()}),
        )

    @app.get("/health", dependencies=[Depends(require_api_key)])
    def health() -> dict[str, bool | str]:
        return scoring_service.health()

    @app.post(
        "/score_batch",
        response_model=ScoreBatchResponse,
        dependencies=[Depends(require_api_key)],
    )
    def score_batch(request: ScoreBatchRequest) -> ScoreBatchResponse:
        return scoring_service.score_batch(request)

    @app.post(
        "/score_batch_upload",
        response_model=ScoreBatchResponse,
        dependencies=[Depends(require_api_key)],
    )
    async def score_batch_upload(request: Request) -> ScoreBatchResponse:
        batch_request = await request_from_multipart(request)
        return scoring_service.score_batch(batch_request)

    return app


def validation_error_is_oversized(exc: RequestValidationError) -> bool:
    return validation_error_details_are_oversized(exc.errors())


def validation_error_details_are_oversized(errors: list[dict[str, Any]]) -> bool:
    for error in errors:
        error_type = str(error.get("type", ""))
        loc = tuple(error.get("loc", ()))
        if error_type in {"too_long", "list_too_long", "string_too_long"}:
            if "items" in loc or "content_base64" in loc:
                return True
    return False


app = create_app()
