from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from julia_agent import db, pubsub
from julia_agent.config import WorkerConfig
from julia_agent.live_runner import run_live_turn

logger = logging.getLogger(__name__)

app = FastAPI(title="Julia Worker")


class WorkerStartPayload(BaseModel):
    run_id: str = Field(alias="runId")
    project_id: str = Field(alias="projectId")
    thread_id: str = Field(alias="threadId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    content: str | None = None
    context_reference_ids: list[str] = Field(default_factory=list, alias="contextReferenceIds")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs/start", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    request: Request, x_julia_signature: str | None = Header(default=None)
) -> dict[str, Any]:
    """Spawn the agent in a background task and return immediately.

    The mutation that calls this endpoint must not block on agent completion;
    runs can take 30+ minutes. We start the task on the running event loop and
    let Modal keep the function alive until it finishes.
    """
    body = await request.body()
    config = WorkerConfig.from_env()
    if not verify_signature(body, x_julia_signature, config.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Julia worker signature")

    payload = WorkerStartPayload.model_validate(await request.json())

    if not config.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is required")

    asyncio.create_task(_run_agent_background(config, payload))
    return {"runId": payload.run_id, "status": "running"}


async def _run_agent_background(
    config: WorkerConfig, payload: WorkerStartPayload
) -> None:
    """Wraps run_live_run with full error catching so the background task never crashes Modal."""
    try:
        await run_live_run(config, config.database_url or "", payload)
    except Exception:  # noqa: BLE001 — top-level guard for the background task
        logger.exception("Julia run %s failed", payload.run_id)


@app.websocket("/runs/{run_id}/events")
async def stream_run_events(websocket: WebSocket, run_id: str) -> None:
    """Live event stream for a run.

    Auth: HMAC-signed token in `?token=`, scoped to (run_id, exp). Token is minted
    by the Vercel mutation and proves the calling user owns the run.

    Behavior:
      1. Replay events with sequence > `?after=N` from Neon (resume on refresh).
      2. Subscribe to in-memory pubsub for live events while the agent runs.
      3. Close cleanly when the run is terminal AND the queue is drained.
    """
    config = WorkerConfig.from_env()
    token = websocket.query_params.get("token") or ""
    after_param = websocket.query_params.get("after") or "0"
    try:
        after_sequence = max(0, int(after_param))
    except ValueError:
        after_sequence = 0

    if not _verify_ws_token(token, run_id, config.webhook_secret):
        await websocket.close(code=4401, reason="invalid token")
        return
    if not config.database_url:
        await websocket.close(code=4503, reason="database not configured")
        return

    await websocket.accept()
    try:
        async with pubsub.subscribe(run_id) as queue:
            last_sequence = await _replay_events(
                websocket, config.database_url, run_id, after_sequence
            )
            terminal = _run_is_terminal(config.database_url, run_id)
            if terminal and not _has_events_after(config.database_url, run_id, last_sequence):
                await websocket.close(code=1000, reason="run already terminal")
                return

            heartbeat_task = asyncio.create_task(_heartbeat(websocket))
            try:
                async for event in _drain_queue(queue):
                    if event is None:
                        break
                    if int(event.get("sequence", 0)) <= last_sequence:
                        continue
                    last_sequence = max(last_sequence, int(event.get("sequence", 0)))
                    await websocket.send_text(json.dumps(event, default=str))
            finally:
                heartbeat_task.cancel()
                with __import__("contextlib").suppress(asyncio.CancelledError):
                    await heartbeat_task
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        logger.exception("ws stream failed for run %s", run_id)
        with __import__("contextlib").suppress(Exception):
            await websocket.close(code=1011, reason="internal error")
        return

    with __import__("contextlib").suppress(Exception):
        await websocket.close(code=1000)


async def _drain_queue(queue: asyncio.Queue) -> AsyncIterator[dict[str, Any] | None]:
    while True:
        item = await queue.get()
        yield item
        if item is None:
            return


async def _replay_events(
    websocket: WebSocket, database_url: str, run_id: str, after_sequence: int
) -> int:
    """Send any events already persisted with sequence > after_sequence. Returns last sequence sent."""
    rows = await asyncio.to_thread(db.fetch_run_events, database_url, run_id, after_sequence)
    last = after_sequence
    for row in rows:
        sequence = int(row.get("sequence", 0))
        last = max(last, sequence)
        await websocket.send_text(json.dumps(row, default=str))
    return last


def _run_is_terminal(database_url: str, run_id: str) -> bool:
    context = db.load_run_context(database_url, run_id)
    if not context:
        return False
    status_value = str(context.get("status") or "")
    return status_value in {"completed", "failed", "canceled"}


def _has_events_after(database_url: str, run_id: str, after_sequence: int) -> bool:
    return bool(db.fetch_run_events(database_url, run_id, after_sequence))


async def _heartbeat(websocket: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(15)
            await websocket.send_text(json.dumps({"type": "heartbeat"}))
    except (WebSocketDisconnect, RuntimeError):
        return


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def _verify_ws_token(token: str, run_id: str, secret: str | None) -> bool:
    """Token format: `<runId>.<expiresAtUnix>.<hmacHex>`."""
    if not secret or not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    token_run_id, expires_at, signature = parts
    if not hmac.compare_digest(token_run_id, run_id):
        return False
    try:
        if int(expires_at) < int(__import__("time").time()):
            return False
    except ValueError:
        return False
    payload = f"{token_run_id}.{expires_at}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def run_live_run(
    config: WorkerConfig, database_url: str, payload: WorkerStartPayload
) -> dict[str, Any]:
    run_context = db.load_run_context(database_url, payload.run_id) or {}
    assistant_message_id = _string_or_default(
        _metadata_value(run_context, "assistantMessageId"),
        payload.assistant_message_id,
    )
    project_id = _string_or_default(run_context.get("project_id"), payload.project_id)
    prompt = payload.content or _string_or_default(run_context.get("input"), "")
    if not prompt:
        raise RuntimeError("Run has no prompt content")

    hydration_dir: Path | None = None
    try:
        context_paths: list[Path] = []
        if payload.context_reference_ids:
            hydration_dir = Path(tempfile.mkdtemp(prefix=f"julia-ctx-{payload.run_id[:8]}-"))
            context_paths = await asyncio.to_thread(
                _download_context_artifacts,
                config,
                database_url,
                payload.context_reference_ids,
                hydration_dir,
            )

        result = await run_live_turn(
            config=config,
            database_url=database_url,
            run_id=payload.run_id,
            project_id=project_id,
            assistant_message_id=assistant_message_id,
            prompt=prompt,
            context_artifact_paths=context_paths,
            starting_sequence=1,
        )
    finally:
        if hydration_dir is not None:
            shutil.rmtree(hydration_dir, ignore_errors=True)

    return {"runId": payload.run_id, "status": result.get("status")}


def _download_context_artifacts(
    config: WorkerConfig,
    database_url: str,
    context_reference_ids: list[str],
    target_dir: Path,
) -> list[Path]:
    rows = db.load_context_artifacts(database_url, context_reference_ids)
    if not rows or not config.r2_bucket:
        return []

    from julia_agent.storage import create_r2_client, download_file_from_r2

    client = create_r2_client(config)
    paths: list[Path] = []
    for row in rows:
        filename = str(row.get("filename") or "context")
        r2_key = row.get("r2_key")
        if not r2_key:
            continue
        dest = target_dir / f"{row.get('id')}_{filename}"
        try:
            download_file_from_r2(client, config.r2_bucket, r2_key, dest)
            paths.append(dest)
        except Exception:  # noqa: BLE001 — best-effort hydration
            continue
    return paths


def _metadata_value(run_context: dict[str, Any], key: str) -> Any:
    metadata = run_context.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default
