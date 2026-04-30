from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from agents import function_tool

from autopep_agent.db import (
    create_artifact,
    create_candidate,
    create_model_inference,
    complete_model_inference,
    insert_candidate_scores,
    load_candidates_by_id,
    map_scoring_result_to_rows,
    update_candidate_fold_artifact,
)
from autopep_agent.endpoint_clients import (
    PROTEINA_BATCH_SIZE,
    PROTEINA_DESIGN_STEPS,
    PROTEINA_FAST_GENERATION_OVERRIDES,
    ChaiClient,
    ProteinaClient,
    ScoringClient,
)
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import get_object as r2_get_object
from autopep_agent.r2_client import put_object as r2_put_object
from autopep_agent.run_context import get_tool_run_context
from autopep_agent.structure_utils import (
    build_complex_fasta,
    build_fasta,
    encode_structure_base64,
    extract_pdb_sequences,
)


def _summarize_error(error: BaseException) -> str:
    summary = str(error).strip() or error.__class__.__name__
    return summary[:1400]


def _candidate_artifact_key(*, workspace_id: str, run_id: str, filename: str) -> str:
    safe_name = filename.replace("/", "-").lstrip(".")
    return (
        f"workspaces/{workspace_id}/runs/{run_id}/proteina-result/{safe_name}"
    )


def _fold_artifact_key(*, workspace_id: str, run_id: str, filename: str) -> str:
    safe_name = filename.replace("/", "-").lstrip(".")
    return f"workspaces/{workspace_id}/runs/{run_id}/chai-result/{safe_name}"


_WORKSPACE_PREFIX = "/workspace/"


def _workspace_path_to_storage_key(workspace_id: str, workspace_path: str) -> str:
    """Translate a sandbox /workspace/-prefixed path into an R2 storage key.

    The R2 bucket is mounted at ``/workspace/`` inside the sandbox under
    ``workspaces/{workspace_id}/`` (see runner._build_workspace_manifest), so
    a sandbox path ``/workspace/runs/<run_id>/inputs/X.pdb`` maps to the R2
    key ``workspaces/{workspace_id}/runs/<run_id>/inputs/X.pdb``.

    Accepts either an absolute ``/workspace/...`` path or a relative path; the
    leading ``/workspace/`` (or ``workspace/``) is stripped before joining.
    """

    path = workspace_path.strip()
    if path.startswith(_WORKSPACE_PREFIX):
        suffix = path[len(_WORKSPACE_PREFIX):]
    elif path.startswith("workspace/"):
        suffix = path[len("workspace/"):]
    else:
        suffix = path.lstrip("/")
    return f"workspaces/{workspace_id}/{suffix.lstrip('/')}"


# ---------------------------------------------------------------------------
# Proteina: proteina_design  (batch-of-N + warm-start)
# ---------------------------------------------------------------------------


async def _proteina_design(
    target_pdb_path: str,
    hotspot_residues: list[str] | None = None,
    binder_length_min: int = 60,
    binder_length_max: int = 90,
    num_candidates: int = PROTEINA_BATCH_SIZE,
    warm_start_structure_path: str | None = None,
) -> dict[str, Any]:
    """Generate ``num_candidates`` binders for the target at ``target_pdb_path``.

    ``target_pdb_path`` is a sandbox path under ``/workspace/`` (e.g.
    ``/workspace/runs/<run_id>/inputs/6M0J.pdb``). The tool reads the file
    from R2 using the workspace_id from ``ToolRunContext`` — the LLM never
    needs to embed structure text in arguments.

    ``warm_start_structure_path``, when provided, is also a ``/workspace/``-
    relative path; the tool reads it and threads it through Proteina's
    warm-start so the diffusion is seeded from an existing pose.

    ``hotspot_residues`` defaults to ``[]`` (unconstrained design). The
    target_input selector defaults to chain ``A`` of the target PDB,
    formatted as ``A1-{len}``.

    Endpoint URLs and API keys are read from the active ``ToolRunContext``
    so the LLM never sees them.
    """

    ctx = get_tool_run_context()
    config = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    hotspots: list[str] = list(hotspot_residues or [])

    # Read the target PDB from R2 using workspace-mounted path semantics.
    target_storage_key = _workspace_path_to_storage_key(
        ctx.workspace_id, target_pdb_path,
    )
    target_bytes = await r2_get_object(
        bucket=config["bucket"],
        account_id=config["account_id"],
        access_key_id=config["access_key_id"],
        secret_access_key=config["secret_access_key"],
        key=target_storage_key,
    )
    target_structure = target_bytes.decode("utf-8")
    target_filename = target_pdb_path.rsplit("/", 1)[-1] or "target.pdb"

    # Derive a default ``target_input`` selector from the first chain of the
    # PDB, using the residue count for the chain. Proteina's ``target_input``
    # uses the form ``{chain}{first}-{last}``; for the simple PDB-derived
    # case we use ``{chain}1-{len}``.
    target_chains = extract_pdb_sequences(target_structure)
    target_input: str | None = None
    if target_chains:
        first_chain = next(iter(target_chains.keys()))
        chain_len = len(target_chains[first_chain])
        if chain_len > 0:
            target_input = f"{first_chain}1-{chain_len}"

    # Optional warm-start: read the seed structure from R2 too.
    warm_start_text: str | None = None
    warm_start_filename: str | None = None
    if warm_start_structure_path:
        warm_start_storage_key = _workspace_path_to_storage_key(
            ctx.workspace_id, warm_start_structure_path,
        )
        warm_start_bytes = await r2_get_object(
            bucket=config["bucket"],
            account_id=config["account_id"],
            access_key_id=config["access_key_id"],
            secret_access_key=config["secret_access_key"],
            key=warm_start_storage_key,
        )
        warm_start_text = warm_start_bytes.decode("utf-8")
        warm_start_filename = (
            warm_start_structure_path.rsplit("/", 1)[-1] or "warm_start.pdb"
        )

    request_payload = {
        "target_filename": target_filename,
        "target_input": target_input,
        "hotspot_residues": hotspots,
        "binder_length": [binder_length_min, binder_length_max],
        "design_steps": PROTEINA_DESIGN_STEPS,
        "overrides": PROTEINA_FAST_GENERATION_OVERRIDES,
        "num_candidates": num_candidates,
        "warm_start_filename": warm_start_filename,
    }
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="proteina_complexa",
        request_json=request_payload,
        endpoint_url=ctx.proteina_base_url,
    )

    try:
        client = ProteinaClient(ctx.proteina_base_url, ctx.proteina_api_key)
        response = await client.design(
            target_structure=target_structure,
            target_filename=target_filename,
            target_input=target_input,
            hotspot_residues=hotspots,
            binder_length=[binder_length_min, binder_length_max],
            warm_start_structure=warm_start_text,
            warm_start_filename=warm_start_filename,
        )
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        raise

    # The persistence loop (R2 upload + create_artifact + create_candidate +
    # events) is part of the inference's success criteria. If any of those
    # steps fail, the inference must be marked `failed` so we never end up
    # with a `completed` model_inference row whose artifacts/candidates are
    # missing or partial. complete_model_inference("completed", ...) only runs
    # AFTER the loop finishes cleanly.
    try:
        candidates: list[dict[str, Any]] = []
        for rank, pdb_record in enumerate(_extract_pdb_records(response), start=1):
            pdb_text = pdb_record["pdb"]
            filename = pdb_record["filename"]
            sequences = extract_pdb_sequences(pdb_text)
            target_sequence = sequences.get("A")
            sequence = sequences.get("B") or next(iter(sequences.values()), "")
            body = pdb_text.encode("utf-8")
            storage_key = _candidate_artifact_key(
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                filename=filename,
            )
            sha256 = await r2_put_object(
                bucket=config["bucket"],
                account_id=config["account_id"],
                access_key_id=config["access_key_id"],
                secret_access_key=config["secret_access_key"],
                key=storage_key,
                body=body,
                content_type="chemical/x-pdb",
            )

            artifact_id = await create_artifact(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                kind="proteina_result",
                name=filename,
                storage_key=storage_key,
                content_type="chemical/x-pdb",
                size_bytes=len(body),
                sha256=sha256,
            )
            await writer.append_event(
                run_id=ctx.run_id,
                event_type="artifact_created",
                title=f"Stored {filename}",
                summary=f"Saved Proteina design {filename} to R2.",
                display={"artifactId": artifact_id, "kind": "proteina_result"},
            )

            # Persist target_sequence into metadata_json so chai_fold_complex
            # can fold target+binder complexes by candidate_id alone.
            candidate_metadata: dict[str, Any] = {}
            if target_sequence:
                candidate_metadata["target_sequence"] = target_sequence

            candidate_db_id = await create_candidate(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                rank=rank,
                source="proteina_complexa",
                title=f"Proteina design #{rank}",
                sequence=sequence,
                chain_ids=sorted(sequences.keys()),
                artifact_id=artifact_id,
                parent_inference_id=inference_id,
                metadata_json=candidate_metadata or None,
            )
            await writer.append_event(
                run_id=ctx.run_id,
                event_type="candidate_ranked",
                title=f"Candidate #{rank} stored",
                summary=f"Persisted Proteina candidate {rank}.",
                display={
                    "candidateId": candidate_db_id,
                    "rank": rank,
                    "source": "proteina_complexa",
                },
            )

            candidates.append(
                {
                    "rank": rank,
                    "filename": filename,
                    "sequence": sequence,
                    "target_sequence": target_sequence,
                    "chain_sequences": sequences,
                    "candidate_id": candidate_db_id,
                    "artifact_id": artifact_id,
                },
            )
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={"raw": response} if not isinstance(response, dict) else response,
            error_summary=_summarize_error(exc),
        )
        raise

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"raw": response} if not isinstance(response, dict) else response,
    )

    return {"num_candidates": len(candidates), "candidates": candidates}


# ---------------------------------------------------------------------------
# Chai: chai_fold_complex  (parallel + always-complex)
# ---------------------------------------------------------------------------


async def _chai_fold_complex(
    candidate_ids: list[str],
    target_sequence: str | None = None,
    target_name: str = "target",
) -> dict[str, Any]:
    """Fold each candidate as a target+binder complex, in parallel.

    ``candidate_ids`` are ``protein_candidate`` row ids that have already
    been persisted (typically by ``proteina_design``). Each candidate is
    folded as a two-chain complex: target chain + binder chain.

    ``target_sequence`` is optional. When provided, every candidate is
    folded against the same target. When ``None``, each candidate's stored
    ``target_sequence`` (from ``metadata_json``) is used; this is the
    common case after ``proteina_design`` populates that field.

    All folds run via ``asyncio.gather`` so independent Chai requests
    overlap on the wire. The function returns ``{"succeeded", "failed",
    "candidates": [{candidate_id, ok}]}`` so the caller can see which
    candidates produced fold artifacts.

    Endpoint URL and API key are pulled from the active ``ToolRunContext``.
    """

    ctx = get_tool_run_context()
    config = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    if not candidate_ids:
        return {"succeeded": 0, "failed": 0, "candidates": []}

    rows = await load_candidates_by_id(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        candidate_ids=list(candidate_ids),
    )
    rows_by_id = {row["id"]: row for row in rows}

    shared_target = _clean_sequence(target_sequence)

    # Build one fold request per candidate. Candidates that can't be folded
    # (missing sequence, missing target sequence, or unknown id) are recorded
    # as ``ok=False`` so the caller's per-candidate accounting is exact.
    fold_plans: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        row = rows_by_id.get(candidate_id)
        if row is None or not row.get("sequence"):
            failed_results.append({"candidate_id": candidate_id, "ok": False})
            continue
        candidate_target_sequence = shared_target or _clean_sequence(
            row.get("target_sequence"),
        )
        if candidate_target_sequence is None:
            failed_results.append({"candidate_id": candidate_id, "ok": False})
            continue

        binder_sequence = _clean_sequence(str(row["sequence"]))
        if binder_sequence is None:
            failed_results.append({"candidate_id": candidate_id, "ok": False})
            continue

        candidate_name = f"candidate-{candidate_id}"
        fasta = build_complex_fasta(
            target_id=target_name.strip() or "target",
            target_sequence=candidate_target_sequence,
            binder_id=candidate_name,
            binder_sequence=binder_sequence,
        )
        fold_plans.append(
            {
                "candidate_id": candidate_id,
                "candidate_name": candidate_name,
                "fasta": fasta,
            },
        )

    if not fold_plans:
        return {
            "succeeded": 0,
            "failed": len(failed_results),
            "candidates": failed_results,
        }

    request_payload = {
        "complexes": [
            {
                "candidate_id": plan["candidate_id"],
                "id": plan["candidate_name"],
                "fasta": plan["fasta"],
            }
            for plan in fold_plans
        ],
        "num_diffn_samples": 1,
    }
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="chai_1",
        request_json=request_payload,
        endpoint_url=ctx.chai_base_url,
    )

    client = ChaiClient(ctx.chai_base_url, ctx.chai_api_key)

    async def _fold_one(plan: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        try:
            response = await client.predict(
                fasta=str(plan["fasta"]),
                num_diffn_samples=1,
            )
        except BaseException as exc:  # noqa: BLE001 — preserved for per-candidate accounting
            return plan, exc
        return plan, response

    fold_results = await asyncio.gather(
        *[_fold_one(plan) for plan in fold_plans],
        return_exceptions=False,
    )

    # Persist successful folds and collect per-candidate accounting. We do
    # the persistence sequentially to keep each candidate's R2 + DB writes
    # ordered, but the network-bound predict() calls already overlapped via
    # gather above.
    per_candidate: list[dict[str, Any]] = list(failed_results)
    raw_results: list[dict[str, Any]] = []
    persistence_error: BaseException | None = None
    try:
        for plan, response_or_exc in fold_results:
            candidate_id = plan["candidate_id"]
            if isinstance(response_or_exc, BaseException):
                per_candidate.append({"candidate_id": candidate_id, "ok": False})
                raw_results.append(
                    {
                        "candidate_id": candidate_id,
                        "error": _summarize_error(response_or_exc),
                    },
                )
                continue
            response = response_or_exc
            raw_results.append({"candidate_id": candidate_id, "raw": response})
            await _persist_chai_response(
                ctx=ctx,
                config=config,
                writer=writer,
                response=response,
                candidate_db_id=candidate_id,
                filename_prefix=str(plan["candidate_name"]),
            )
            per_candidate.append({"candidate_id": candidate_id, "ok": True})
    except BaseException as exc:
        persistence_error = exc

    if persistence_error is not None:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={"results": raw_results},
            error_summary=_summarize_error(persistence_error),
        )
        raise persistence_error

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"results": raw_results},
    )

    succeeded = sum(1 for entry in per_candidate if entry["ok"])
    failed = sum(1 for entry in per_candidate if not entry["ok"])
    return {
        "succeeded": succeeded,
        "failed": failed,
        "candidates": per_candidate,
    }


# ---------------------------------------------------------------------------
# Scoring: score_candidate_interactions
# ---------------------------------------------------------------------------


async def _score_candidate_interactions(
    target_name: str,
    target_sequence: str,
    candidates: list[dict[str, Any]],
) -> Any:
    """Score target-candidate interactions.

    Endpoint URL and API key are pulled from the active ``ToolRunContext``.

    Args:
        target_name: Name for protein A.
        target_sequence: Sequence for protein A.
        candidates: Binder candidate dictionaries. Pass ``candidate_id`` on
            each candidate to link the resulting score rows to the persisted
            protein_candidate row.
    """

    ctx = get_tool_run_context()

    items = [
        _build_scoring_item(target_name, target_sequence, candidate, index)
        for index, candidate in enumerate(candidates, start=1)
    ]
    request_payload = {
        "items": items,
        "options": {
            "run_dscript": True,
            "run_prodigy": True,
            "temperature_celsius": 25.0,
            "fail_fast": False,
        },
    }

    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="protein_interaction_scoring",
        request_json=request_payload,
        endpoint_url=ctx.scoring_base_url,
    )

    try:
        client = ScoringClient(ctx.scoring_base_url, ctx.scoring_api_key)
        response = await client.score_batch(items)
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        raise

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"raw": response} if not isinstance(response, dict) else response,
    )

    candidate_id_by_input = {
        _candidate_id(c, idx): c.get("candidate_id")
        for idx, c in enumerate(candidates, start=1)
        if c.get("candidate_id") is not None
    }

    for result_row in _extract_scoring_results(response):
        if not isinstance(result_row, Mapping):
            continue
        item_id = str(result_row.get("id") or "")
        # Prefer the request-side mapping: we trust the candidate_id we
        # paired with each input over whatever the (potentially LLM-shaped)
        # response echoes back. Fall back to the response's candidate_id
        # only if we have no request-side entry for this item_id.
        candidate_db_id = (
            candidate_id_by_input.get(item_id)
            or result_row.get("candidate_id")
        )
        if candidate_db_id is None:
            continue
        rows = map_scoring_result_to_rows(
            candidate_id=str(candidate_db_id),
            model_inference_id=inference_id,
            result=dict(result_row),
        )
        await insert_candidate_scores(
            ctx.database_url,
            workspace_id=ctx.workspace_id,
            run_id=ctx.run_id,
            candidate_id=str(candidate_db_id),
            model_inference_id=inference_id,
            rows=rows,
        )

    return response


# ---------------------------------------------------------------------------
# function_tool wrappers — these are what the LLM sees
# ---------------------------------------------------------------------------


proteina_design = function_tool(
    _proteina_design,
    name_override="proteina_design",
    strict_mode=False,
)
chai_fold_complex = function_tool(
    _chai_fold_complex,
    name_override="chai_fold_complex",
    strict_mode=False,
)
score_candidate_interactions = function_tool(
    _score_candidate_interactions,
    name_override="score_candidate_interactions",
    strict_mode=False,
)

# Aliases so runner.py keeps working before the merge step that switches
# imports to the new names. Both old and new exports point at the same
# function_tool instance.
generate_binder_candidates = proteina_design
fold_sequences_with_chai = chai_fold_complex


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clean_sequence(value: str | None) -> str | None:
    if value is None:
        return None
    sequence = value.strip().upper()
    return sequence or None


async def _persist_chai_response(
    *,
    ctx: Any,
    config: Mapping[str, str],
    writer: EventWriter,
    response: Any,
    candidate_db_id: Any,
    filename_prefix: str | None = None,
) -> None:
    for cif_record in _extract_cif_records(response):
        filename = _prefixed_fold_filename(
            cif_record["filename"],
            filename_prefix=filename_prefix,
        )
        cif_text = cif_record["cif"]
        body = cif_text.encode("utf-8")
        storage_key = _fold_artifact_key(
            workspace_id=ctx.workspace_id,
            run_id=ctx.run_id,
            filename=filename,
        )
        sha256 = await r2_put_object(
            bucket=config["bucket"],
            account_id=config["account_id"],
            access_key_id=config["access_key_id"],
            secret_access_key=config["secret_access_key"],
            key=storage_key,
            body=body,
            content_type="chemical/x-cif",
        )
        artifact_id = await create_artifact(
            ctx.database_url,
            workspace_id=ctx.workspace_id,
            run_id=ctx.run_id,
            kind="chai_result",
            name=filename,
            storage_key=storage_key,
            content_type="chemical/x-cif",
            size_bytes=len(body),
            sha256=sha256,
            metadata_json=(
                {"candidateId": str(candidate_db_id)}
                if candidate_db_id is not None
                else None
            ),
        )
        await writer.append_event(
            run_id=ctx.run_id,
            event_type="artifact_created",
            title=f"Stored {filename}",
            summary=f"Saved Chai fold {filename} to R2.",
            display={"artifactId": artifact_id, "kind": "chai_result"},
        )

        if candidate_db_id is not None:
            await update_candidate_fold_artifact(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                candidate_id=str(candidate_db_id),
                fold_artifact_id=artifact_id,
            )


def _prefixed_fold_filename(filename: str, *, filename_prefix: str | None) -> str:
    safe_filename = filename.replace("/", "-").lstrip(".") or "chai-result.cif"
    if not filename_prefix:
        return safe_filename
    safe_prefix = filename_prefix.replace("/", "-").lstrip(".") or "candidate"
    if safe_filename.startswith(f"{safe_prefix}-"):
        return safe_filename
    return f"{safe_prefix}-{safe_filename}"


def _r2_config_from_env() -> dict[str, str]:
    """Pull R2 credentials from ``WorkerConfig``.

    Imported lazily so tests that patch ``biology_tools`` don't drag the
    config import into module-load time.
    """

    from autopep_agent.config import WorkerConfig

    config = WorkerConfig.from_env()
    return {
        "bucket": config.r2_bucket,
        "account_id": config.r2_account_id,
        "access_key_id": config.r2_access_key_id,
        "secret_access_key": config.r2_secret_access_key,
    }


def _extract_pdb_records(response: Any) -> list[dict[str, str]]:
    records = _response_records(response)
    pdb_records: list[dict[str, str]] = []

    for index, record in enumerate(records, start=1):
        filename = f"candidate-{index}.pdb"
        pdb_text: str | None = None

        if isinstance(record, str):
            pdb_text = record
        elif isinstance(record, Mapping):
            filename = str(
                record.get("filename")
                or record.get("name")
                or record.get("path")
                or filename,
            )
            raw_pdb = (
                record.get("pdb")
                or record.get("pdb_text")
                or record.get("structure")
                or record.get("content")
            )
            if isinstance(raw_pdb, str):
                pdb_text = raw_pdb

        if pdb_text is not None:
            pdb_records.append({"filename": filename, "pdb": pdb_text})

    return pdb_records


def _extract_cif_records(response: Any) -> list[dict[str, str]]:
    records = _response_records(response, keys=("cifs", "cif", "structures", "results"))
    cif_records: list[dict[str, str]] = []

    for index, record in enumerate(records, start=1):
        filename = f"candidate-{index}.cif"
        cif_text: str | None = None
        candidate_key: str | None = None

        if isinstance(record, str):
            cif_text = record
        elif isinstance(record, Mapping):
            filename = str(
                record.get("filename")
                or record.get("name")
                or record.get("path")
                or filename,
            )
            raw_cif = (
                record.get("cif")
                or record.get("cif_text")
                or record.get("structure")
                or record.get("content")
            )
            if isinstance(raw_cif, str):
                cif_text = raw_cif
            candidate_key_value = (
                record.get("candidate_id")
                or record.get("id")
                or record.get("name")
            )
            if candidate_key_value is not None:
                candidate_key = str(candidate_key_value)

        if cif_text is not None:
            entry: dict[str, str] = {"filename": filename, "cif": cif_text}
            if candidate_key is not None:
                entry["candidate_key"] = candidate_key
            cif_records.append(entry)

    return cif_records


def _extract_scoring_results(response: Any) -> list[Any]:
    if isinstance(response, Mapping):
        for key in ("results", "items", "data", "scored"):
            value = response.get(key)
            if isinstance(value, list):
                return value
    if isinstance(response, list):
        return response
    return []


def _response_records(
    response: Any,
    keys: tuple[str, ...] = ("pdbs", "pdb", "structures", "results", "outputs"),
) -> list[Any]:
    if isinstance(response, Mapping):
        for key in keys:
            value = response.get(key)
            if value is None:
                continue
            return value if isinstance(value, list) else [value]
    if isinstance(response, list):
        return response
    return []


def _build_scoring_item(
    target_name: str,
    target_sequence: str,
    candidate: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    candidate_id = _candidate_id(candidate, index)
    item: dict[str, Any] = {
        "id": candidate_id,
        "protein_a": {"name": target_name, "sequence": target_sequence},
        "protein_b": {"name": candidate_id},
    }

    sequence = candidate.get("sequence")
    if sequence is not None:
        item["protein_b"]["sequence"] = str(sequence).strip().upper()

    structure_text = _candidate_structure_text(candidate)
    if structure_text:
        item["structure"] = {
            "format": "pdb",
            "content_base64": encode_structure_base64(structure_text),
            "chain_a": "A",
            "chain_b": "B",
        }

    return item


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    for key in ("id", "filename", "name"):
        value = candidate.get(key)
        if value:
            return str(value)
    rank = candidate.get("rank")
    if rank:
        return f"candidate-{rank}"
    return f"candidate-{index}"


def _candidate_structure_text(candidate: Mapping[str, Any]) -> str | None:
    for key in ("pdb", "structure", "structure_text"):
        value = candidate.get(key)
        if isinstance(value, str):
            return value
    return None


# Re-exported for callers (and tests) that previously imported ``build_fasta``
# transitively via biology_tools. The new ``_chai_fold_complex`` always builds
# a complex FASTA so this import is kept solely for backwards compatibility.
__all__ = [
    "proteina_design",
    "chai_fold_complex",
    "score_candidate_interactions",
    "generate_binder_candidates",
    "fold_sequences_with_chai",
    "build_fasta",
]
