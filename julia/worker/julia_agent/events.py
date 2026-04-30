from __future__ import annotations

from typing import Any


def _event(run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"runId": run_id, "type": event_type, "payload": payload}


def normalize_text_delta(run_id: str, text: str) -> dict[str, Any]:
    return _event(run_id, "text_delta", {"text": text})


def normalize_tool_call_started(
    run_id: str, name: str, tool_input: Any | None = None
) -> dict[str, Any]:
    return _event(run_id, "tool_call_started", {"name": name, "input": tool_input})


def normalize_tool_call_completed(
    run_id: str, name: str, result: Any | None = None
) -> dict[str, Any]:
    return _event(run_id, "tool_call_completed", {"name": name, "result": result})


def normalize_run_error(run_id: str, error: BaseException | str) -> dict[str, Any]:
    if isinstance(error, BaseException):
        message = str(error)
        code = error.__class__.__name__
    else:
        message = error
        code = "Error"
    return _event(run_id, "run_error", {"message": message, "code": code})


def normalize_run_status(run_id: str, status: str) -> dict[str, Any]:
    return _event(run_id, "run_status", {"status": status})

