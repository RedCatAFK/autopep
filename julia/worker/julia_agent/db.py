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
    with _connect(database_url) as conn:
        conn.execute(
            "update julia_runs set status = %s, updated_at = now() where id = %s",
            (status, run_id),
        )


def insert_run_event(
    database_url: str, run_id: str, event_type: str, payload: Mapping[str, Any]
) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            insert into julia_run_events (run_id, type, payload, created_at)
            values (%s, %s, %s, now())
            """,
            (run_id, event_type, Jsonb(dict(payload))),
        )


def append_assistant_delta(database_url: str, run_id: str, delta: str) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            update julia_runs
            set assistant_text = coalesce(assistant_text, '') || %s,
                updated_at = now()
            where id = %s
            """,
            (delta, run_id),
        )


def insert_artifact(
    database_url: str,
    run_id: str,
    kind: str,
    key: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            """
            insert into julia_artifacts (run_id, kind, storage_key, metadata, created_at)
            values (%s, %s, %s, %s, now())
            """,
            (run_id, kind, key, Jsonb(dict(metadata or {}))),
        )


def load_run_context(database_url: str, run_id: str) -> dict[str, Any] | None:
    with _connect(database_url) as conn:
        row = conn.execute(
            "select * from julia_runs where id = %s",
            (run_id,),
        ).fetchone()
    return dict(row) if row else None
