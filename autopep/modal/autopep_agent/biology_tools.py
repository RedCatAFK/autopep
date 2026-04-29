from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents import function_tool

from autopep_agent.db import (
    create_artifact,
    create_candidate,
    create_model_inference,
    complete_model_inference,
    insert_candidate_scores,
    map_scoring_result_to_rows,
    update_candidate_fold_artifact,
)
from autopep_agent.endpoint_clients import (
    PROTEINA_DESIGN_STEPS,
    PROTEINA_FAST_GENERATION_OVERRIDES,
    ChaiClient,
    ProteinaClient,
    ScoringClient,
)
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import put_object as r2_put_object
from autopep_agent.run_context import get_tool_run_context
from autopep_agent.structure_utils import (
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


# ---------------------------------------------------------------------------
# Proteina: generate_binder_candidates
# ---------------------------------------------------------------------------


async def _generate_binder_candidates(
    target_structure: str,
    target_filename: str,
    target_input: str | None,
    hotspot_residues: list[str],
    binder_length_min: int,
    binder_length_max: int,
) -> dict[str, Any]:
    """Generate binder designs and extract binder-chain sequences.

    Endpoint URLs and API keys are read from the active ``ToolRunContext``
    so the LLM never sees them.

    Args:
        target_structure: Target structure text accepted by Proteina.
        target_filename: Filename for the target structure.
        target_input: Optional target input selector.
        hotspot_residues: Target residues to bias the design.
        binder_length_min: Minimum binder length.
        binder_length_max: Maximum binder length.
    """

    ctx = get_tool_run_context()
    config = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    request_payload = {
        "target_filename": target_filename,
        "target_input": target_input,
        "hotspot_residues": list(hotspot_residues),
        "binder_length": [binder_length_min, binder_length_max],
        "design_steps": PROTEINA_DESIGN_STEPS,
        "overrides": PROTEINA_FAST_GENERATION_OVERRIDES,
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
            hotspot_residues=list(hotspot_residues),
            binder_length=[binder_length_min, binder_length_max],
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
                    "pdb": pdb_text,
                    "sequence": sequence,
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

    return {"raw": response, "candidates": candidates}


# ---------------------------------------------------------------------------
# Chai: fold_sequences_with_chai
# ---------------------------------------------------------------------------


async def _fold_sequences_with_chai(
    sequence_candidates: list[dict[str, Any]],
) -> Any:
    """Fold sequence candidates with Chai.

    Endpoint URL and API key are pulled from the active ``ToolRunContext``.

    Args:
        sequence_candidates: Candidate dictionaries with ``id`` and
            ``sequence``. Pass ``candidate_id`` to link the resulting fold
            artifact back to the persisted protein_candidate row.
    """

    ctx = get_tool_run_context()
    config = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    fasta = build_fasta(sequence_candidates)
    request_payload = {
        "fasta": fasta,
        "num_diffn_samples": 1,
        "candidate_ids": [
            str(c.get("candidate_id")) for c in sequence_candidates
            if c.get("candidate_id") is not None
        ],
    }
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="chai_1",
        request_json=request_payload,
        endpoint_url=ctx.chai_base_url,
    )

    try:
        client = ChaiClient(ctx.chai_base_url, ctx.chai_api_key)
        response = await client.predict(fasta=fasta, num_diffn_samples=1)
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

    candidate_id_by_name = {
        str(c.get("id") or c.get("name") or ""): c.get("candidate_id")
        for c in sequence_candidates
        if c.get("candidate_id") is not None
    }
    candidate_ids_by_index = [
        c.get("candidate_id")
        for c in sequence_candidates
        if c.get("candidate_id") is not None
    ]

    for index, cif_record in enumerate(_extract_cif_records(response), start=1):
        filename = cif_record["filename"]
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
        )
        await writer.append_event(
            run_id=ctx.run_id,
            event_type="artifact_created",
            title=f"Stored {filename}",
            summary=f"Saved Chai fold {filename} to R2.",
            display={"artifactId": artifact_id, "kind": "chai_result"},
        )

        match_key = _match_candidate_key(cif_record, fallback_index=index)
        candidate_db_id = candidate_id_by_name.get(match_key)
        if candidate_db_id is None and index <= len(candidate_ids_by_index):
            candidate_db_id = candidate_ids_by_index[index - 1]
        if candidate_db_id is not None:
            await update_candidate_fold_artifact(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                candidate_id=str(candidate_db_id),
                fold_artifact_id=artifact_id,
            )

    return response


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


generate_binder_candidates = function_tool(
    _generate_binder_candidates,
    name_override="generate_binder_candidates",
    strict_mode=False,
)
fold_sequences_with_chai = function_tool(
    _fold_sequences_with_chai,
    name_override="fold_sequences_with_chai",
    strict_mode=False,
)
score_candidate_interactions = function_tool(
    _score_candidate_interactions,
    name_override="score_candidate_interactions",
    strict_mode=False,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _match_candidate_key(record: Mapping[str, Any], *, fallback_index: int) -> str:
    candidate_key = record.get("candidate_key")
    if candidate_key:
        return str(candidate_key)
    filename = record.get("filename")
    if isinstance(filename, str) and filename:
        # Strip extension: candidate-1.cif -> candidate-1
        return filename.rsplit(".", 1)[0]
    return f"candidate-{fallback_index}"


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
