"""Per-run in-memory broadcast for live event delivery to WebSocket subscribers.

The agent runner publishes every event into both Neon (durable) and the matching
run's `asyncio.Queue` (live). WebSocket subscribers replay missed events from
Neon by `?after=N` and then tail the queue.

Concurrency model: events are pushed from the agent task (one per run) and read
by zero or more WebSocket consumers per run. We fan out by giving each
subscriber its own queue; the publisher writes to all of them. This avoids the
"only one consumer can read each item" pitfall of a shared queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_subscribers: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}
_lock = asyncio.Lock()
_QUEUE_MAX = 4096


async def publish(run_id: str, event: dict[str, Any]) -> None:
    """Push an event to every subscriber of `run_id`. Safe when no subscribers."""
    async with _lock:
        queues = list(_subscribers.get(run_id, ()))
    for queue in queues:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("pubsub queue full for run %s; dropping event", run_id)


async def publish_terminal(run_id: str) -> None:
    """Signal end-of-stream to every subscriber. Idempotent."""
    async with _lock:
        queues = list(_subscribers.get(run_id, ()))
    for queue in queues:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


@asynccontextmanager
async def subscribe(run_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any] | None]]:
    """Yield a fresh queue subscribed to `run_id`. The queue is removed on exit."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_QUEUE_MAX)
    async with _lock:
        _subscribers.setdefault(run_id, set()).add(queue)
    try:
        yield queue
    finally:
        async with _lock:
            subs = _subscribers.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    _subscribers.pop(run_id, None)
