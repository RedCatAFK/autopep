"""Per-run in-memory broadcast for live event delivery to WebSocket subscribers.

Concurrency model: events are pushed from the agent task (one per run) and read
by zero or more WebSocket consumers per run. We fan out by giving each
subscriber its own queue; the publisher writes to all of them. This avoids the
"only one consumer can read each item" pitfall of a shared queue.

`publish` and `publish_terminal` are deliberately **synchronous**: they only do
in-memory queue puts (`asyncio.Queue.put_nowait`), and asyncio is single-
threaded, so there is no concurrent access to `_subscribers` between awaits.
A previous version used `loop.create_task(pubsub.publish(...))` from sync
contexts, which caused a publish-ordering bug: the awaited `publish_terminal`
in the run finally block ran to completion before the scheduled completed-event
task got a chance to run, so subscribers saw the `None` sentinel before the
`run_status: completed` event and the UI never left "writing response…".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}
_QUEUE_MAX = 4096


def publish(run_id: str, event: dict[str, Any]) -> None:
    """Push an event to every subscriber of `run_id`. Safe when no subscribers."""
    for queue in list(_subscribers.get(run_id, ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("pubsub queue full for run %s; dropping event", run_id)


def publish_terminal(run_id: str) -> None:
    """Signal end-of-stream to every subscriber. Idempotent."""
    for queue in list(_subscribers.get(run_id, ())):
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


@contextmanager
def subscribe(run_id: str) -> Iterator[asyncio.Queue[dict[str, Any] | None]]:
    """Yield a fresh queue subscribed to `run_id`. The queue is removed on exit.

    Sync context manager because all mutations of `_subscribers` happen between
    asyncio yields on a single loop — no actual concurrency to protect against.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.setdefault(run_id, set()).add(queue)
    try:
        yield queue
    finally:
        subs = _subscribers.get(run_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                _subscribers.pop(run_id, None)
