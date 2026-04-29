from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass
class EventWriter:
    database_url: str

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        title: str,
        summary: str | None = None,
        display: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into autopep_agent_event
                        (run_id, sequence, type, title, summary, display_json, raw_json)
                    values (
                        %s,
                        coalesce(
                            (
                                select max(sequence)
                                from autopep_agent_event
                                where run_id = %s
                            ),
                            0
                        ) + 1,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::jsonb
                    )
                    """,
                    (
                        run_id,
                        run_id,
                        event_type,
                        title,
                        summary,
                        json.dumps(display or {}),
                        json.dumps(raw or {}),
                    ),
                )
