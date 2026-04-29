from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass(frozen=True)
class AgentRunContext:
    prompt: str
    model: str | None
    task_kind: str
    enabled_recipes: list[str]


@dataclass(frozen=True)
class AttachmentRow:
    """Row describing an attachment artifact referenced by an agent run."""

    artifact_id: str
    storage_key: str
    name: str


async def connect(database_url: str) -> Any:
    return await psycopg.AsyncConnection.connect(database_url)


async def claim_run(database_url: str, *, run_id: str) -> bool:
    """Atomically transition a run from `queued` to `running`.

    Returns True only if the row was claimed by this caller. If the run is
    already running, completed, failed, or cancelled, returns False — duplicate
    Modal invocations of the same `run_id` should bail out without side effects.
    """
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update autopep_agent_run
                set status = 'running',
                    started_at = now()
                where id = %s
                  and status = 'queued'
                returning id
                """,
                (run_id,),
            )
            claimed = await cur.fetchone()
    return claimed is not None


async def get_run_context(
    database_url: str,
    *,
    run_id: str,
    thread_id: str,
    workspace_id: str,
) -> AgentRunContext:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select prompt, model, task_kind
                from autopep_agent_run
                where id = %s
                  and thread_id = %s
                  and workspace_id = %s
                """,
                (run_id, thread_id, workspace_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError("Agent run was not found for the workspace thread.")

            await cur.execute(
                """
                select body_snapshot
                from autopep_run_recipe
                where run_id = %s
                order by created_at asc
                """,
                (run_id,),
            )
            recipe_rows = await cur.fetchall()

    return AgentRunContext(
        prompt=str(row[0]),
        model=str(row[1]) if row[1] else None,
        task_kind=str(row[2]) if row[2] else "chat",
        enabled_recipes=[str(recipe_row[0]) for recipe_row in recipe_rows],
    )


async def get_run_attachments(
    database_url: str,
    *,
    run_id: str,
) -> list[AttachmentRow]:
    """Return attachment artifacts referenced by ``run_id``'s workspace.

    A row is included when:
      * an ``autopep_context_reference`` of kind ``artifact`` exists for the
        run's workspace, AND
      * the referenced artifact has ``kind = 'attachment'``.

    Rows are returned in deterministic ``name, artifact_id`` order so that
    the system message announcing them, and the on-volume directory listing,
    are stable across runs.
    """

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select distinct a.id, a.storage_key, a.name
                from autopep_artifact a
                join autopep_context_reference cr
                  on cr.artifact_id = a.id and cr.kind = 'artifact'
                join autopep_agent_run r
                  on r.workspace_id = cr.workspace_id
                where r.id = %s and a.kind = 'attachment'
                order by a.name asc, a.id asc
                """,
                (run_id,),
            )
            rows = await cur.fetchall()
    return [
        AttachmentRow(
            artifact_id=str(row[0]),
            storage_key=str(row[1]),
            name=str(row[2]),
        )
        for row in rows
    ]


async def mark_run_completed(database_url: str, run_id: str) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update autopep_agent_run
                set status = 'completed',
                    finished_at = now()
                where id = %s
                """,
                (run_id,),
            )


async def mark_run_failed(
    database_url: str,
    run_id: str,
    error_summary: str,
) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update autopep_agent_run
                set status = 'failed',
                    finished_at = now(),
                    error_summary = %s
                where id = %s
                """,
                (error_summary, run_id),
            )


# ---------------------------------------------------------------------------
# Candidate score row mapping
# ---------------------------------------------------------------------------


def _candidate_score_status(
    *,
    overall_status: str,
    available: bool,
) -> str:
    """Pick the per-row status enum value.

    The ``candidate_score.status`` enum is one of ``ok | partial | failed |
    unavailable``. When the per-scorer ``available`` flag is False we always
    record ``unavailable`` regardless of the run-wide status — that matches
    the schema's intent: the row exists, but the scorer did not produce
    usable output.
    """

    if not available:
        return "unavailable"
    if overall_status in {"ok", "partial", "failed"}:
        return overall_status
    return "partial"


def map_scoring_result_to_rows(
    *,
    candidate_id: str,
    model_inference_id: str,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map a single scoring batch result into ``candidate_score`` row dicts.

    Returns three rows: dscript, prodigy, and the protein_interaction
    aggregate. Each row is shaped to be passed straight to
    :func:`insert_candidate_scores`.
    """

    overall_status = str(result.get("status") or "partial")
    scores = dict(result.get("scores") or {})
    warnings = list(result.get("warnings") or [])
    errors = list(result.get("errors") or [])

    rows: list[dict[str, Any]] = []

    dscript = dict(scores.get("dscript") or {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "dscript",
            "status": _candidate_score_status(
                overall_status=overall_status,
                available=bool(dscript.get("available")),
            ),
            "label": None,
            "value": dscript.get("interaction_probability"),
            "unit": "probability",
            "values_json": dscript,
            "warnings_json": dscript.get("warnings") or warnings,
            "errors_json": errors,
        },
    )

    prodigy = dict(scores.get("prodigy") or {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "prodigy",
            "status": _candidate_score_status(
                overall_status=overall_status,
                available=bool(prodigy.get("available")),
            ),
            "label": None,
            "value": prodigy.get("delta_g_kcal_per_mol"),
            "unit": "kcal/mol",
            "values_json": prodigy,
            "warnings_json": prodigy.get("warnings") or warnings,
            "errors_json": errors,
        },
    )

    aggregate = dict(result.get("aggregate") or {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "protein_interaction_aggregate",
            "status": _candidate_score_status(
                overall_status=overall_status,
                available=bool(aggregate.get("available")),
            ),
            "label": aggregate.get("label"),
            "value": None,
            "unit": None,
            "values_json": aggregate,
            "warnings_json": warnings,
            "errors_json": errors,
        },
    )
    return rows


# ---------------------------------------------------------------------------
# Persistence helpers for the MVP one-loop workflow
#
# TODO(MVP scale): every helper opens its own psycopg connection. Per-helper
# connections accumulate latency and put avoidable pressure on Postgres
# (TLS handshake, auth round-trip, search_path setup). Consider passing a
# single connection through the call chain or introducing a connection pool
# (e.g. psycopg_pool) when we move past the one-loop MVP. Acceptable for MVP
# scale where each helper is called a handful of times per run.
# ---------------------------------------------------------------------------


async def create_model_inference(
    database_url: str,
    *,
    workspace_id: str,
    run_id: str,
    model_name: str,
    request_json: dict[str, Any],
    endpoint_url: str,
) -> str:
    """Insert a ``model_inference`` row in ``running`` status; return its id."""

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into autopep_model_inference (
                    workspace_id,
                    run_id,
                    provider,
                    model_name,
                    status,
                    endpoint_url_snapshot,
                    request_json,
                    started_at
                )
                values (
                    %s, %s, 'modal', %s, 'running', %s, %s::jsonb, now()
                )
                returning id
                """,
                (
                    workspace_id,
                    run_id,
                    model_name,
                    endpoint_url,
                    json.dumps(request_json),
                ),
            )
            row = await cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to insert model_inference row.")
    return str(row[0])


async def complete_model_inference(
    database_url: str,
    *,
    inference_id: str,
    status: str,
    response_json: dict[str, Any],
    error_summary: str | None = None,
) -> None:
    """Finalize a ``model_inference`` row with status, response, and timestamps."""

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update autopep_model_inference
                set status = %s,
                    response_json = %s::jsonb,
                    finished_at = now(),
                    error_summary = %s
                where id = %s
                """,
                (
                    status,
                    json.dumps(response_json),
                    error_summary,
                    inference_id,
                ),
            )


async def create_artifact(
    database_url: str,
    *,
    workspace_id: str,
    run_id: str,
    kind: str,
    name: str,
    storage_key: str,
    content_type: str,
    size_bytes: int,
    sha256: str | None = None,
    source_artifact_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> str:
    """Insert an ``artifact`` row pointing at an R2 object; return its id."""

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into autopep_artifact (
                    workspace_id,
                    run_id,
                    source_artifact_id,
                    kind,
                    name,
                    storage_provider,
                    storage_key,
                    content_type,
                    size_bytes,
                    sha256,
                    metadata_json
                )
                values (
                    %s, %s, %s, %s, %s, 'r2', %s, %s, %s, %s, %s::jsonb
                )
                returning id
                """,
                (
                    workspace_id,
                    run_id,
                    source_artifact_id,
                    kind,
                    name,
                    storage_key,
                    content_type,
                    size_bytes,
                    sha256,
                    json.dumps(metadata_json or {}),
                ),
            )
            row = await cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to insert artifact row.")
    return str(row[0])


async def create_candidate(
    database_url: str,
    *,
    workspace_id: str,
    run_id: str,
    rank: int,
    source: str,
    title: str,
    sequence: str | None = None,
    structure_id: str | None = None,
    chain_ids: list[str] | None = None,
    score_json: dict[str, Any] | None = None,
    why_selected: str | None = None,
    artifact_id: str | None = None,
    fold_artifact_id: str | None = None,
    parent_inference_id: str | None = None,
    parent_candidate_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> str:
    """Insert a ``protein_candidate`` row; return its id."""

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into autopep_protein_candidate (
                    workspace_id,
                    run_id,
                    parent_candidate_id,
                    rank,
                    source,
                    structure_id,
                    chain_ids_json,
                    sequence,
                    title,
                    score_json,
                    why_selected,
                    artifact_id,
                    fold_artifact_id,
                    parent_inference_id,
                    metadata_json
                )
                values (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb,
                    %s, %s, %s, %s, %s::jsonb
                )
                returning id
                """,
                (
                    workspace_id,
                    run_id,
                    parent_candidate_id,
                    rank,
                    source,
                    structure_id,
                    json.dumps(list(chain_ids or [])),
                    sequence,
                    title,
                    json.dumps(score_json or {}),
                    why_selected,
                    artifact_id,
                    fold_artifact_id,
                    parent_inference_id,
                    json.dumps(metadata_json or {}),
                ),
            )
            row = await cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to insert protein_candidate row.")
    return str(row[0])


async def insert_candidate_scores(
    database_url: str,
    *,
    workspace_id: str,
    run_id: str,
    candidate_id: str,
    model_inference_id: str,
    rows: list[dict[str, Any]],
) -> None:
    """Batch-insert ``candidate_score`` rows produced by ``map_scoring_result_to_rows``.

    ``candidate_id`` flows from LLM-controlled tool arguments, so we verify
    that the candidate row actually belongs to ``(workspace_id, run_id)``
    before writing any score rows. If it does not, we raise rather than
    silently scoring a candidate from a different workspace or run.
    """

    if not rows:
        return

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select 1
                from autopep_protein_candidate
                where id = %s
                  and workspace_id = %s
                  and run_id = %s
                """,
                (candidate_id, workspace_id, run_id),
            )
            if await cur.fetchone() is None:
                raise RuntimeError(
                    "candidate not found in this workspace/run",
                )

            for row in rows:
                await cur.execute(
                    """
                    insert into autopep_candidate_score (
                        workspace_id,
                        run_id,
                        candidate_id,
                        model_inference_id,
                        scorer,
                        status,
                        label,
                        value,
                        unit,
                        values_json,
                        warnings_json,
                        errors_json
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb
                    )
                    """,
                    (
                        workspace_id,
                        run_id,
                        candidate_id,
                        model_inference_id,
                        row["scorer"],
                        row["status"],
                        row.get("label"),
                        row.get("value"),
                        row.get("unit"),
                        json.dumps(row.get("values_json") or {}),
                        json.dumps(row.get("warnings_json") or []),
                        json.dumps(row.get("errors_json") or []),
                    ),
                )


async def update_candidate_fold_artifact(
    database_url: str,
    *,
    workspace_id: str,
    run_id: str,
    candidate_id: str,
    fold_artifact_id: str,
) -> None:
    """Set ``fold_artifact_id`` on an existing ``protein_candidate`` row.

    ``candidate_id`` flows from LLM-controlled tool arguments, so the update
    is scoped to ``(workspace_id, run_id)``. If no row matches, raise rather
    than silently mutating a candidate that belongs to a different
    workspace or run.
    """

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                update autopep_protein_candidate
                set fold_artifact_id = %s
                where id = %s
                  and workspace_id = %s
                  and run_id = %s
                """,
                (fold_artifact_id, candidate_id, workspace_id, run_id),
            )
            if cur.rowcount == 0:
                raise RuntimeError(
                    "candidate not found in this workspace/run",
                )
