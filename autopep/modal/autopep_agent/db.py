from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass(frozen=True)
class AgentRunContext:
    prompt: str
    model: str | None
    enabled_recipes: list[str]


async def connect(database_url: str) -> Any:
    return await psycopg.AsyncConnection.connect(database_url)


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
                select prompt, model
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
        enabled_recipes=[str(recipe_row[0]) for recipe_row in recipe_rows],
    )


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
