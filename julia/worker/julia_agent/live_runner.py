"""Run a Julia turn through the OpenAI Agents SDK, streaming events live to
WebSocket subscribers.

Events emitted (pubsub-only — not persisted to Neon):
  - run_status (running, completed, failed, canceled)
  - text_delta as the model streams output text
  - tool_call_started / tool_call_completed bracketing each tool call
  - artifact_created after tool-result artifacts are uploaded to R2
  - run_error on failure

Per-event Postgres writes were removed because the synchronous psycopg calls
in the streaming hot path starved the asyncio loop, batching deltas at the
WebSocket sender. The WebSocket is now the single source of truth for
in-flight runs; the assistant message body is persisted exactly once at
end-of-run via `db.write_assistant_message`, and `julia_runs.status`
transitions are still recorded via `db.mark_run_status`.

Tool-result artifacts are still extracted and uploaded to R2 keyed by
(project, run, artifact id, filename), with `julia_artifacts` rows inserted
on upload (one-shot, not in the streaming hot path) and announced as
artifact_created events. After the turn we do one final scan over the run
workspace's outputs/ subdirectories and upload anything we missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from julia_agent import artifacts as artifact_helpers
from julia_agent import db
from julia_agent import pubsub
from julia_agent.agent import _agent_max_turns, build_julia_agent_with_tools
from julia_agent.config import WorkerConfig
from julia_agent.events import (
    normalize_run_error,
    normalize_run_status,
    normalize_text_delta,
    normalize_tool_call_completed,
    normalize_tool_call_started,
)
from julia_agent.tools import ensure_workspace_layout

MAX_TOOL_OUTPUT_PREVIEW_CHARS = 4000


@dataclass
class _ToolCall:
    name: str
    arguments: Any
    call_id: str
    started_sequence: int


@dataclass
class _LiveRunState:
    config: WorkerConfig
    database_url: str
    run_id: str
    project_id: str
    assistant_message_id: str
    workspace_dir: Path
    sequence: int = 1
    pending_tool_calls: dict[str, _ToolCall] = field(default_factory=dict)
    uploaded_paths: set[str] = field(default_factory=set)
    assistant_text: str = ""


def _next_sequence(state: _LiveRunState) -> int:
    state.sequence += 1
    return state.sequence


def _record_event(
    state: _LiveRunState,
    event: dict[str, Any],
    *,
    message: str | None = None,
) -> None:
    metadata = dict(event["payload"])
    if event["type"] == "text_delta":
        text = metadata.get("text")
        if isinstance(text, str):
            metadata["delta"] = text
    _persist_event(state, event["type"], message, metadata)


def _persist_event(
    state: _LiveRunState,
    event_type: str,
    message: str | None,
    metadata: dict[str, Any],
) -> int:
    """Broadcast an event to live WebSocket subscribers. Returns the new sequence.

    Run events are not persisted to Neon — we rely on the WebSocket as the
    single source of truth for in-flight runs. Synchronous psycopg writes here
    blocked the event loop and starved the WS sender, batching deltas instead
    of streaming them.
    """
    sequence = _next_sequence(state)
    payload = {
        "runId": state.run_id,
        "type": event_type,
        "message": message,
        "sequence": sequence,
        "metadata": metadata,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return sequence
    loop.create_task(pubsub.publish(state.run_id, payload))
    return sequence


async def run_live_turn(
    *,
    config: WorkerConfig,
    database_url: str,
    run_id: str,
    project_id: str,
    assistant_message_id: str,
    prompt: str,
    context_artifact_paths: list[Path] | None = None,
    starting_sequence: int = 1,
    max_turns: int | None = None,
) -> dict[str, Any]:
    """Run a single agent turn against a fresh per-run workspace and stream events."""

    workspace_dir = Path(tempfile.mkdtemp(prefix=f"julia-run-{run_id[:8]}-"))
    ensure_workspace_layout(workspace_dir)
    _hydrate_context_artifacts(workspace_dir, context_artifact_paths or [])

    state = _LiveRunState(
        config=config,
        database_url=database_url,
        run_id=run_id,
        project_id=project_id,
        assistant_message_id=assistant_message_id,
        workspace_dir=workspace_dir,
        sequence=starting_sequence,
    )

    db.mark_run_status(database_url, run_id, "running")
    _record_event(state, normalize_run_status(run_id, "running"), message="running")

    try:
        await _execute_streamed_turn(state, prompt, max_turns=max_turns)
        await _final_artifact_scan(state)
        _record_event(
            state, normalize_run_status(run_id, "completed"), message="completed"
        )
        db.mark_run_status(database_url, run_id, "completed")
        status = "completed"
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await _final_artifact_scan(state)
        with contextlib.suppress(Exception):
            _record_event(
                state, normalize_run_status(run_id, "canceled"), message="canceled"
            )
        with contextlib.suppress(Exception):
            db.mark_run_status(database_url, run_id, "canceled")
        raise
    except Exception as error:  # noqa: BLE001 — record then re-raise
        with contextlib.suppress(Exception):
            await _final_artifact_scan(state)
        _record_event(state, normalize_run_error(run_id, error), message=str(error))
        db.mark_run_status(database_url, run_id, "failed")
        status = "failed"
        raise
    finally:
        with contextlib.suppress(Exception):
            db.write_assistant_message(
                database_url, assistant_message_id, state.assistant_text
            )
        shutil.rmtree(workspace_dir, ignore_errors=True)
        with contextlib.suppress(Exception):
            await pubsub.publish_terminal(run_id)

    return {"runId": run_id, "status": status}


async def _execute_streamed_turn(
    state: _LiveRunState, prompt: str, *, max_turns: int | None = None
) -> None:
    from agents import Runner, trace

    agent = build_julia_agent_with_tools(state.workspace_dir)
    resolved_max_turns = max_turns if max_turns is not None else _agent_max_turns()

    with trace("julia worker turn"):
        stream = Runner.run_streamed(agent, prompt, max_turns=resolved_max_turns)
        async for event in stream.stream_events():
            await _handle_stream_event(state, event)


async def _handle_stream_event(state: _LiveRunState, event: Any) -> None:
    event_type = getattr(event, "type", None)
    if event_type == "raw_response_event":
        await _handle_raw_response(state, getattr(event, "data", None))
    elif event_type == "run_item_stream_event":
        await _handle_run_item(state, getattr(event, "item", None))


async def _handle_raw_response(state: _LiveRunState, data: Any) -> None:
    if data is None:
        return
    data_type = getattr(data, "type", None)
    if data_type != "response.output_text.delta":
        return
    delta = getattr(data, "delta", None) or ""
    if not isinstance(delta, str) or not delta:
        return
    state.assistant_text += delta
    _record_event(state, normalize_text_delta(state.run_id, delta), message=delta)


async def _handle_run_item(state: _LiveRunState, item: Any) -> None:
    if item is None:
        return
    item_type = getattr(item, "type", None)
    if item_type == "tool_call_item":
        _emit_tool_call_started(state, item)
    elif item_type == "tool_call_output_item":
        await _emit_tool_call_completed(state, item)


def _emit_tool_call_started(state: _LiveRunState, item: Any) -> None:
    raw_item = getattr(item, "raw_item", None)
    name = (
        getattr(item, "tool_name", None)
        or _maybe_get(raw_item, "name")
        or "tool"
    )
    call_id = (
        getattr(item, "call_id", None)
        or _maybe_get(raw_item, "call_id")
        or _maybe_get(raw_item, "id")
        or uuid.uuid4().hex
    )
    arguments = _parse_tool_arguments(_maybe_get(raw_item, "arguments"))
    started_sequence = _persist_event(
        state,
        "tool_call_started",
        f"{name} started",
        {
            "name": name,
            "input": arguments,
            "toolCallId": call_id,
        },
    )
    state.pending_tool_calls[call_id] = _ToolCall(
        name=name,
        arguments=arguments,
        call_id=call_id,
        started_sequence=started_sequence,
    )


async def _emit_tool_call_completed(state: _LiveRunState, item: Any) -> None:
    raw_item = getattr(item, "raw_item", None)
    call_id = (
        getattr(item, "call_id", None)
        or _maybe_get(raw_item, "call_id")
        or _maybe_get(raw_item, "id")
    )
    pending = state.pending_tool_calls.pop(call_id, None) if call_id else None
    name = pending.name if pending else (
        getattr(item, "tool_name", None) or _maybe_get(raw_item, "name") or "tool"
    )
    raw_output = getattr(item, "output", None)
    if raw_output is None and isinstance(item, dict):
        raw_output = item.get("output")
    parsed_output = _parse_tool_output(raw_output)
    output_summary = _summarize_for_event(parsed_output)

    artifact_records = await _upload_tool_result_artifacts(state, name, parsed_output)

    _persist_event(
        state,
        "tool_call_completed",
        f"{name} completed",
        {
            "name": name,
            "result": output_summary,
            "toolCallId": call_id,
            "artifacts": artifact_records,
        },
    )


async def _upload_tool_result_artifacts(
    state: _LiveRunState, tool_name: str, parsed_output: Any
) -> list[dict[str, Any]]:
    if not isinstance(parsed_output, dict):
        return []
    raw_paths = artifact_helpers.artifact_paths_from_tool_result(tool_name, parsed_output)
    if not raw_paths:
        return []
    records: list[dict[str, Any]] = []
    for raw_path in raw_paths:
        absolute = _resolve_workspace_path(state.workspace_dir, raw_path)
        if absolute is None:
            continue
        record = await _upload_single_artifact(state, absolute, source="tool_result")
        if record is not None:
            records.append(record)
    return records


async def _final_artifact_scan(state: _LiveRunState) -> None:
    output_root = state.workspace_dir / "outputs"
    if not output_root.exists():
        return
    for path in artifact_helpers.scan_allowed_outputs([output_root]):
        await _upload_single_artifact(state, path, source="final_scan")


async def _upload_single_artifact(
    state: _LiveRunState, absolute_path: Path, *, source: str
) -> dict[str, Any] | None:
    try:
        if not absolute_path.exists() or not absolute_path.is_file():
            return None
        key = str(absolute_path.resolve())
        if key in state.uploaded_paths:
            return None
        state.uploaded_paths.add(key)

        artifact_id = uuid.uuid4().hex
        relative = _relative_to_workspace(state.workspace_dir, absolute_path)
        r2_key = (
            f"workspaces/{state.project_id}/runs/{state.run_id}/"
            f"{artifact_id}/{absolute_path.name}"
        )

        size_bytes = absolute_path.stat().st_size
        sha256 = _sha256_of_file(absolute_path)
        kind = artifact_helpers.classify_artifact_kind(absolute_path)

        if state.config.r2_bucket:
            await asyncio.to_thread(
                _upload_to_r2,
                state.config,
                absolute_path,
                r2_key,
            )

        db.insert_artifact(
            state.database_url,
            state.project_id,
            state.run_id,
            kind,
            absolute_path.name,
            r2_key,
            None,
            size_bytes,
            {
                "artifactId": artifact_id,
                "displayPath": relative,
                "sandboxPath": relative,
                "sha256": sha256,
                "source": source,
            },
        )
        record = {
            "artifactId": artifact_id,
            "filename": absolute_path.name,
            "kind": kind,
            "r2Key": r2_key,
            "displayPath": relative,
            "size": size_bytes,
            "sha256": sha256,
            "source": source,
        }
        _persist_event(state, "artifact_created", absolute_path.name, record)
        return record
    except Exception as error:  # noqa: BLE001 — missing/transient artifact must not abort the run
        _persist_event(
            state,
            "run_error",
            f"artifact upload failed for {absolute_path.name}: {error}",
            {
                "scope": "artifact_upload",
                "filename": absolute_path.name,
                "error": str(error),
            },
        )
        return None


def _upload_to_r2(config: WorkerConfig, path: Path, key: str) -> None:
    from julia_agent.storage import create_r2_client, upload_file_to_r2

    if not config.r2_bucket:
        return
    client = create_r2_client(config)
    upload_file_to_r2(client, config.r2_bucket, path, key)


def _hydrate_context_artifacts(workspace_dir: Path, paths: list[Path]) -> None:
    if not paths:
        return
    target_dir = workspace_dir / "inputs" / "artifacts"
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        shutil.copy2(path, target_dir / path.name)


def _resolve_workspace_path(workspace_dir: Path, path: Path) -> Path | None:
    try:
        candidate = path if path.is_absolute() else workspace_dir / path
        resolved = candidate.resolve(strict=False)
    except Exception:
        return None
    workspace = workspace_dir.resolve(strict=False)
    if resolved != workspace and workspace not in resolved.parents:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _relative_to_workspace(workspace_dir: Path, path: Path) -> str:
    workspace = workspace_dir.resolve(strict=False)
    target = path.resolve(strict=False)
    try:
        return str(target.relative_to(workspace))
    except ValueError:
        return path.name


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_tool_arguments(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[:1200]
    return _jsonable(raw)


def _parse_tool_output(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _summarize_for_event(value: Any) -> Any:
    encoded = json.dumps(_jsonable(value), default=str)
    if len(encoded) > MAX_TOOL_OUTPUT_PREVIEW_CHARS:
        return {
            "truncated": True,
            "preview": encoded[:MAX_TOOL_OUTPUT_PREVIEW_CHARS],
        }
    return _jsonable(value)


def _maybe_get(value: Any, key: str) -> Any:
    """Read `key` from a dict-or-object value; returns None when absent."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
