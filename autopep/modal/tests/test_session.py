"""Tests for PostgresSession — SDK Session adapter against ``thread_items``.

Tests are integration-style — they use a real Postgres ``DATABASE_URL``.
Skip if ``DATABASE_URL`` is not set in the environment.
"""

from __future__ import annotations

import os
import uuid as uuidlib

import psycopg  # type: ignore[import-not-found]
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for session integration tests.",
)


@pytest_asyncio.fixture
async def fresh_thread():
    """Create a fresh user + workspace + thread row and yield the thread UUID.

    Drops the workspace (cascading to thread + thread_items) and the user
    after the test completes.
    """

    db_url = os.environ["DATABASE_URL"]
    suffix = uuidlib.uuid4().hex[:12]
    user_id = f"test-session-user-{suffix}"
    user_email = f"test-session-{suffix}@example.invalid"
    workspace_id = str(uuidlib.uuid4())
    thread_id = str(uuidlib.uuid4())

    async with await psycopg.AsyncConnection.connect(db_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into "user" (id, name, email, email_verified, created_at, updated_at)
                values (%s, %s, %s, false, now(), now())
                """,
                (user_id, "Session Test", user_email),
            )
            await cur.execute(
                """
                insert into autopep_workspace (id, owner_id, name)
                values (%s, %s, %s)
                """,
                (workspace_id, user_id, "session test"),
            )
            await cur.execute(
                """
                insert into autopep_thread (id, workspace_id, title)
                values (%s, %s, %s)
                """,
                (thread_id, workspace_id, "Session test thread"),
            )
        await conn.commit()

    try:
        yield thread_id
    finally:
        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            async with conn.cursor() as cur:
                # Workspace cascade drops thread + thread_items.
                await cur.execute(
                    "delete from autopep_workspace where id = %s",
                    (workspace_id,),
                )
                await cur.execute(
                    'delete from "user" where id = %s',
                    (user_id,),
                )
            await conn.commit()


@pytest.mark.asyncio
async def test_get_items_returns_prior_user_message(fresh_thread: str) -> None:
    from autopep_agent.db import insert_thread_item
    from autopep_agent.session import PostgresSession

    db_url = os.environ["DATABASE_URL"]
    await insert_thread_item(
        db_url,
        thread_id=fresh_thread,
        run_id=None,
        item_type="message",
        role="user",
        content_json={"type": "input_text", "text": "hello"},
    )
    session = PostgresSession(database_url=db_url, thread_id=fresh_thread)
    items = await session.get_items()
    assert len(items) == 1
    assert items[0]["type"] == "message"
    assert items[0]["role"] == "user"
    assert any(c.get("text") == "hello" for c in items[0]["content"])


@pytest.mark.asyncio
async def test_round_trip_preserves_function_call_shape(fresh_thread: str) -> None:
    from autopep_agent.session import PostgresSession

    db_url = os.environ["DATABASE_URL"]
    session = PostgresSession(database_url=db_url, thread_id=fresh_thread)
    await session.add_items(
        [
            {
                "type": "function_call",
                "name": "literature_search",
                "arguments": '{"query": "EGFR inhibitors"}',
                "call_id": "call_abc123",
            },
            {
                "type": "function_call_output",
                "call_id": "call_abc123",
                "output": '{"results": []}',
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I found nothing."}],
            },
        ]
    )
    items = await session.get_items()
    assert [it["type"] for it in items] == [
        "function_call",
        "function_call_output",
        "message",
    ]
    assert items[0]["name"] == "literature_search"
    assert items[1]["call_id"] == "call_abc123"
    assert items[2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_clear_session_empties_the_thread(fresh_thread: str) -> None:
    from autopep_agent.session import PostgresSession

    db_url = os.environ["DATABASE_URL"]
    session = PostgresSession(database_url=db_url, thread_id=fresh_thread)
    await session.add_items(
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "x"}],
            }
        ]
    )
    assert len(await session.get_items()) == 1
    await session.clear_session()
    assert len(await session.get_items()) == 0


@pytest.mark.asyncio
async def test_pop_item_removes_and_returns_latest(fresh_thread: str) -> None:
    from autopep_agent.session import PostgresSession

    db_url = os.environ["DATABASE_URL"]
    session = PostgresSession(database_url=db_url, thread_id=fresh_thread)
    await session.add_items(
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "first"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "second"}],
            },
        ]
    )
    popped = await session.pop_item()
    assert popped is not None
    assert popped["type"] == "message"
    assert popped["role"] == "assistant"
    remaining = await session.get_items()
    assert len(remaining) == 1
    assert remaining[0]["role"] == "user"
