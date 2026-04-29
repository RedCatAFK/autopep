from __future__ import annotations

from typing import Any


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_jsonable(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _as_jsonable(model_dump())
        except Exception:
            pass

    try:
        attrs = vars(value)
    except TypeError:
        attrs = None
    if attrs:
        return {
            str(key): _as_jsonable(item)
            for key, item in attrs.items()
            if not str(key).startswith("_")
        }

    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    try:
        return getattr(value, key, default)
    except Exception:
        return default


def _tool_name(item: Any) -> str | None:
    raw_item = _get(item, "raw_item", {}) or {}
    name = _get(raw_item, "name")
    if name is None:
        name = _get(_get(item, "tool_origin"), "agent_tool_name")
    if name is None:
        name = _get(item, "name")
    if name is None:
        return None
    return str(name)


def normalize_stream_event(event: Any) -> dict[str, Any] | None:
    event_type = _get(event, "type")

    if event_type == "raw_response_event":
        # response.created / response.completed / response.output_text.delta
        # are diagnostic-only and were previously persisted to the agent_events
        # ledger. They are now delivered exclusively via the Modal SSE stream
        # (Task 2.5) and the messages table (Task 2.9), so we drop them here
        # to avoid bloating the ledger with high-frequency token deltas and
        # redundant lifecycle markers.
        return None

    if event_type == "agent_updated_stream_event":
        # Agent-handoff signals are no longer persisted; surface them via
        # streaming if needed in a later task.
        return None

    if event_type == "run_item_stream_event":
        name = _get(event, "name", "")
        item = _get(event, "item")
        tool_name = _tool_name(item)
        raw = _as_jsonable(event)

        if name == "tool_called":
            return {
                "type": "tool_call_started",
                "title": "Tool call started",
                "summary": tool_name,
                "display": {"name": tool_name},
                "raw": raw,
            }

        if name == "tool_output":
            return {
                "type": "tool_call_completed",
                "title": "Tool call completed",
                "summary": tool_name,
                "display": {"name": tool_name},
                "raw": raw,
            }

        if name == "reasoning_item_created":
            return {
                "type": "reasoning_step",
                "title": "Reasoning step",
                "summary": None,
                "display": {},
                "raw": raw,
            }

        if name in {"message_output_created", "message_output"}:
            return {
                "type": "assistant_message_completed",
                "title": "Assistant message completed",
                "summary": None,
                "display": {},
                "raw": raw,
            }

    return None
