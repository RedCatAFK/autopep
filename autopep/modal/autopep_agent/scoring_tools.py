"""score_candidates — fan-out scoring across interaction + quality endpoints.

This tool fans out to two Modal endpoints in parallel via ``asyncio.gather``:

* ``ScoringClient`` — the protein-interaction batch endpoint that runs both
  D-SCRIPT and PRODIGY for each (target, candidate) pair.
* ``QualityScorersClient`` — the per-candidate quality scorer endpoint
  (solubility / aggregation-APR / HLA-presentation risk). Its deployed
  contract accepts one FASTA record per HTTP call, so the client gathers
  one-at-a-time using ``asyncio.gather``.

Both endpoints have their results persisted to the database under separate
``model_inference`` rows, and each per-candidate score is written to
``candidate_score`` rows. A failure on one endpoint does not abort the
other — partial results are returned with the failed endpoint's error
summarized in ``response["errors"]``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from agents import function_tool

from autopep_agent.db import (
    complete_model_inference,
    create_model_inference,
    insert_candidate_scores,
    load_candidates_by_id,
)
from autopep_agent.endpoint_clients import (
    QualityScorersClient,
    ScoringClient,
)
from autopep_agent.run_context import get_tool_run_context


# Quality scorers the deployed endpoint produces. Keep this in sync with
# tools/quality-scorers/inference_modal_app.py::_score_sequence.
_QUALITY_SCORER_KEYS: tuple[str, ...] = (
    "solubility",
    "aggregation_apr",
    "hla_presentation_risk",
)


def _summarize_error(exc: BaseException) -> str:
    return (str(exc).strip() or exc.__class__.__name__)[:1400]


def _build_interaction_items(
    candidates: list[dict[str, Any]],
    *,
    target_name: str,
    target_sequence: str,
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(c["id"]),
            "protein_a": {"name": target_name, "sequence": target_sequence},
            "protein_b": {
                "name": str(c["id"]),
                "sequence": (c.get("sequence") or "").upper(),
            },
        }
        for c in candidates
    ]


def _interaction_rows(
    candidate_id: str,
    model_inference_id: str,
    scores: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dscript = scores.get("dscript")
    if isinstance(dscript, Mapping):
        rows.append(
            {
                "scorer": "dscript",
                "value": float(dscript.get("interaction_probability") or 0.0),
                "unit": "probability",
                "label": dscript.get("label"),
                "values_json": dict(dscript),
                "warnings_json": list(dscript.get("warnings") or []),
                "errors_json": [],
                "model_inference_id": model_inference_id,
                "status": "ok",
            },
        )
    prodigy = scores.get("prodigy")
    if isinstance(prodigy, Mapping):
        rows.append(
            {
                "scorer": "prodigy",
                "value": float(
                    prodigy.get("delta_g_kcal_mol")
                    or prodigy.get("delta_g_kcal_per_mol")
                    or 0.0,
                ),
                "unit": "kcal/mol",
                "label": prodigy.get("label"),
                "values_json": dict(prodigy),
                "warnings_json": list(prodigy.get("warnings") or []),
                "errors_json": [],
                "model_inference_id": model_inference_id,
                "status": "ok",
            },
        )
    return rows


def _quality_rows(
    candidate_id: str,
    model_inference_id: str,
    scores: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scorer in _QUALITY_SCORER_KEYS:
        value = scores.get(scorer)
        if value is None:
            continue
        rows.append(
            {
                "scorer": scorer,
                "value": float(value),
                "unit": "probability",
                "label": None,
                "values_json": {scorer: value},
                "warnings_json": [],
                "errors_json": [],
                "model_inference_id": model_inference_id,
                "status": "ok",
            },
        )
    return rows


async def _run_interaction_scoring(
    ctx: Any,
    items: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, str]:
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="protein_interaction_scoring",
        request_json={"items": items},
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
        return None, _summarize_error(exc), inference_id

    response_json = response if isinstance(response, dict) else {"raw": response}
    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json=response_json,
    )
    return response_json, None, inference_id


async def _run_quality_scoring(
    ctx: Any,
    sequences: list[tuple[str, str]],
) -> tuple[dict[str, Any] | None, str | None, str]:
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="quality_scorers",
        request_json={"sequences": [{"id": cid, "sequence": seq} for cid, seq in sequences]},
        endpoint_url=ctx.quality_scorers_base_url,
    )
    try:
        client = QualityScorersClient(
            ctx.quality_scorers_base_url,
            ctx.quality_scorers_api_key,
        )
        response = await client.score_batch(sequences)
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        return None, _summarize_error(exc), inference_id

    response_json = response if isinstance(response, dict) else {"raw": response}
    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json=response_json,
    )
    return response_json, None, inference_id


def _index_quality_response(
    response: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Index the quality-scorer aggregated response by candidate id.

    The aggregated shape produced by ``QualityScorersClient.score_batch`` is
    ``{"results": [{"id": ..., "scores": {...}}, ...]}`` — see that method
    for the exact construction.
    """

    if not response:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for entry in response.get("results") or []:
        if not isinstance(entry, Mapping):
            continue
        cid = entry.get("id")
        if cid is None:
            continue
        scores = entry.get("scores")
        if isinstance(scores, Mapping):
            indexed[str(cid)] = dict(scores)
    return indexed


def _index_interaction_response(
    response: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not response:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for entry in response.get("results") or []:
        if not isinstance(entry, Mapping):
            continue
        cid = entry.get("id")
        if cid is None:
            continue
        scores = entry.get("scores")
        if isinstance(scores, Mapping):
            indexed[str(cid)] = dict(scores)
    return indexed


async def _score_candidates(
    target_name: str,
    target_sequence: str,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Score candidates in parallel across interaction + quality endpoints.

    Args:
        target_name: Display name for the target protein (chain A).
        target_sequence: Amino-acid sequence for the target.
        candidate_ids: Persisted ``protein_candidate`` ids to score. Each
            candidate is loaded from the database; sequences are pulled
            server-side rather than passed through the LLM so the model
            cannot accidentally rewrite them.
    """

    ctx = get_tool_run_context()

    candidates = await load_candidates_by_id(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        candidate_ids=candidate_ids,
    )
    if not candidates:
        raise RuntimeError(f"No candidates found for ids {candidate_ids}")

    interaction_items = _build_interaction_items(
        candidates,
        target_name=target_name,
        target_sequence=target_sequence,
    )
    sequences = [
        (str(c["id"]), (c.get("sequence") or "").upper()) for c in candidates
    ]

    interaction_result, quality_result = await asyncio.gather(
        _run_interaction_scoring(ctx, interaction_items),
        _run_quality_scoring(ctx, sequences),
    )
    interaction_response, interaction_error, interaction_inference_id = interaction_result
    quality_response, quality_error, quality_inference_id = quality_result

    interaction_by_id = _index_interaction_response(interaction_response)
    quality_by_id = _index_quality_response(quality_response)

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = str(candidate["id"])
        interaction_scores = interaction_by_id.get(cid, {})
        quality_scores = quality_by_id.get(cid, {})
        merged = {**interaction_scores, **quality_scores}
        results.append({"candidate_id": cid, "scores": merged})

        rows = _interaction_rows(
            cid, interaction_inference_id, interaction_scores,
        ) + _quality_rows(cid, quality_inference_id, quality_scores)
        if rows:
            await insert_candidate_scores(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                candidate_id=cid,
                model_inference_id=interaction_inference_id,
                rows=rows,
            )

    response: dict[str, Any] = {
        "target_name": target_name,
        "results": results,
    }
    errors: dict[str, str] = {}
    if interaction_error:
        errors["interaction"] = interaction_error
    if quality_error:
        errors["quality_scorers"] = quality_error
    if errors:
        response["errors"] = errors

    return response


score_candidates = function_tool(
    _score_candidates,
    name_override="score_candidates",
    strict_mode=False,
)
