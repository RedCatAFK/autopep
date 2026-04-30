"""PostgresSession — SDK Session adapter persisting items in autopep_thread_item.

Round-trip rule: ``content_json`` stores the literal SDK item shape so the
SDK can read what it wrote without translation. The TS-side webhook
writes simplified message rows (``{type: "input_text"|"output_text", text}``);
when those are returned by ``get_items``, we re-shape them into the canonical
SDK message-item form (with ``role`` + ``content`` array) so the SDK keeps
multi-turn parity with what the user actually saw in the UI.
"""

from __future__ import annotations

from typing import Any, Mapping

import psycopg
from agents.memory import Session, SessionSettings

from autopep_agent.db import (
    insert_thread_item,
    select_thread_items_for_session,
)


_SDK_CANONICAL_TYPES = {
    "message",
    "function_call",
    "function_call_output",
    "reasoning",
}


def _content_json_to_sdk_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a ``thread_items`` row's ``content_json`` into an SDK input item.

    Two shapes need handling:

    1. Native SDK shape: ``content_json`` already has the full item
       (``{type, role, content, ...}``). We return it as-is.
    2. Simplified webhook/legacy shape: ``content_json`` is just
       ``{type: "input_text"|"output_text", text: "..."}``. We wrap it into
       the SDK's message-item shape, deriving the ``role`` from the row and
       choosing ``input_text`` vs ``output_text`` based on that role.
    """

    payload = dict(row.get("content_json") or {})
    item_type = row.get("item_type")

    # Already SDK-canonical -> use as-is.
    if payload.get("type") in _SDK_CANONICAL_TYPES:
        return payload

    # Reshape simplified message rows into the SDK message-item form.
    if item_type == "message":
        text = payload.get("text", "")
        role = row.get("role") or "assistant"
        content_kind = "output_text" if role == "assistant" else "input_text"
        return {
            "type": "message",
            "role": role,
            "content": [{"type": content_kind, "text": text}],
        }

    # Fallback: stamp the type from the row so the SDK at least sees a typed item.
    payload["type"] = item_type or "message"
    return payload


def _role_for_item(item: Mapping[str, Any]) -> str | None:
    """Derive the ``role`` column value from an SDK item, if any.

    The schema's ``role`` column applies to message-shaped rows. Function
    calls and reasoning rows are role-less; tool outputs get ``"tool"``.
    """

    item_type = str(item.get("type") or "")
    if item_type == "message":
        return str(item.get("role") or "assistant")
    if item_type == "function_call_output":
        return "tool"
    return None


class PostgresSession(Session):
    """SDK ``Session`` backed by the ``autopep_thread_item`` Postgres table.

    Workspace isolation: each workspace's active ``thread_id`` is unique, so
    ``PostgresSession(thread_id=...)`` is naturally scoped per-workspace.

    Round-trip preservation: ``content_json`` stores the SDK's literal item
    shape, so what the SDK adds in turn N is exactly what ``get_items``
    returns in turn N+1.
    """

    def __init__(
        self,
        *,
        database_url: str,
        thread_id: str,
        run_id: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._thread_id = thread_id
        self._run_id = run_id
        # Session protocol requires session_id and session_settings as
        # *attributes* (not methods). The SDK reads them via attribute access
        # (e.g. session.session_settings.limit) so they must be present.
        self.session_id: str = thread_id
        self.session_settings: SessionSettings = SessionSettings()

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = await select_thread_items_for_session(
            self._database_url, thread_id=self._thread_id
        )
        items = [_content_json_to_sdk_item(row) for row in rows]
        if limit is not None and limit >= 0:
            return items[-limit:] if limit > 0 else []
        return items

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            item_type = str(item.get("type") or "message")
            await insert_thread_item(
                self._database_url,
                thread_id=self._thread_id,
                run_id=self._run_id,
                item_type=item_type,
                role=_role_for_item(item),
                content_json=dict(item),
            )

    async def pop_item(self) -> dict[str, Any] | None:
        """Delete and return the most recent ``thread_item`` for this thread.

        Used by the SDK for retries / rollback. Returns ``None`` if the
        thread has no items.
        """

        async with await psycopg.AsyncConnection.connect(
            self._database_url
        ) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    delete from autopep_thread_item
                    where id = (
                        select id from autopep_thread_item
                        where thread_id = %s
                        order by sequence desc
                        limit 1
                    )
                    returning
                        id,
                        run_id,
                        sequence,
                        item_type,
                        role,
                        content_json,
                        attachment_refs_json,
                        context_refs_json,
                        recipe_refs_json,
                        created_at
                    """,
                    (self._thread_id,),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        rec = {
            "id": str(row[0]),
            "run_id": str(row[1]) if row[1] is not None else None,
            "sequence": int(row[2]),
            "item_type": str(row[3]),
            "role": str(row[4]) if row[4] is not None else None,
            "content_json": row[5] if row[5] is not None else {},
            "attachment_refs_json": row[6],
            "context_refs_json": row[7],
            "recipe_refs_json": row[8],
            "created_at": row[9].isoformat() if row[9] is not None else None,
        }
        return _content_json_to_sdk_item(rec)

    async def clear_session(self) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._database_url
        ) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "delete from autopep_thread_item where thread_id = %s",
                    (self._thread_id,),
                )

