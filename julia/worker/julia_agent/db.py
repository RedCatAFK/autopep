from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@contextmanager
def _connect(database_url: str):
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        yield conn


def mark_run_status(database_url: str, run_id: str, status: str) -> None:
    timestamp_sql = ""
    if status == "running":
        timestamp_sql = ", started_at = coalesce(started_at, now())"
    elif status in {"completed", "failed", "canceled"}:
        timestamp_sql = ", completed_at = coalesce(completed_at, now())"

    with _connect(database_url) as conn:
        conn.execute(
            f"update julia_runs set status = %s, updated_at = now(){timestamp_sql} where id = %s",
            (status, run_id),
        )


def insert_run_event(
    database_url: str,
    run_id: str,
    event_type: str,
    message: str | None,
    sequence: int,
    metadata: Mapping[str, Any],
) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            insert into julia_run_events (run_id, type, message, sequence, metadata, created_at)
            values (%s, %s, %s, %s, %s, now())
            """,
            (run_id, event_type, message, sequence, Jsonb(dict(metadata))),
        )


def append_assistant_delta(
    database_url: str, assistant_message_id: str, delta: str
) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            update julia_messages
            set content = coalesce(content, '') || %s
            where id = %s
            """,
            (delta, assistant_message_id),
        )


def insert_artifact(
    database_url: str,
    project_id: str,
    run_id: str,
    kind: str,
    filename: str,
    r2_key: str,
    content_type: str | None = None,
    size_bytes: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            insert into julia_artifacts (
                project_id, run_id, kind, filename, content_type, r2_key, size_bytes, metadata, created_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                project_id,
                run_id,
                kind,
                filename,
                content_type,
                r2_key,
                size_bytes,
                Jsonb(dict(metadata or {})),
            ),
        )


def fetch_run_events(
    database_url: str, run_id: str, after_sequence: int
) -> list[dict[str, Any]]:
    """Return events for `run_id` with sequence > after_sequence, ordered by sequence."""
    with _connect(database_url) as conn:
        rows = conn.execute(
            """
            select id::text as id,
                   run_id::text as "runId",
                   type::text as type,
                   message,
                   sequence,
                   metadata,
                   created_at as "createdAt"
            from julia_run_events
            where run_id = %s and sequence > %s
            order by sequence asc
            """,
            (run_id, int(after_sequence)),
        ).fetchall()
    return [dict(row) for row in rows]


def load_run_context(database_url: str, run_id: str) -> dict[str, Any] | None:
    with _connect(database_url) as conn:
        row = conn.execute(
            "select * from julia_runs where id = %s",
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


def load_context_artifacts(
    database_url: str, context_reference_ids: list[str]
) -> list[dict[str, Any]]:
    """Fetch artifact rows referenced by the given context reference UUIDs.

    Returns one row per resolved artifact with: id, filename, r2_key, kind, project_id.
    Missing or unreferenced ids are silently skipped.
    """
    if not context_reference_ids:
        return []
    with _connect(database_url) as conn:
        rows = conn.execute(
            """
            select a.id::text as id,
                   a.filename as filename,
                   a.r2_key as r2_key,
                   a.kind::text as kind,
                   a.project_id::text as project_id
            from julia_context_references c
            join julia_artifacts a on a.id = c.artifact_id
            where c.id::text = any(%s)
            """,
            (context_reference_ids,),
        ).fetchall()
    return [dict(row) for row in rows]
