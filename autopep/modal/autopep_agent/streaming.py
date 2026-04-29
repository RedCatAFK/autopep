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
        data = _get(event, "data")
        data_type = _get(data, "type")
        if data_type == "response.created":
            return {
                "type": "assistant_message_started",
                "title": "Assistant message started",
                "summary": None,
                "display": {},
                "raw": _as_jsonable(event),
            }
        if data_type == "response.completed":
            return {
                "type": "assistant_message_completed",
                "title": "Assistant message completed",
                "summary": None,
                "display": {},
                "raw": _as_jsonable(event),
            }
        if data_type == "response.output_text.delta":
            delta = _get(data, "delta", "")
            if delta:
                return {
                    "type": "assistant_token_delta",
                    "title": "Assistant token",
                    "summary": None,
                    "display": {"delta": delta},
                    "raw": _as_jsonable(event),
                }
        return None

    if event_type == "agent_updated_stream_event":
        name = _get(_get(event, "new_agent"), "name", "Agent")
        return {
            "type": "agent_changed",
            "title": "Agent changed",
            "summary": name,
            "display": {"agentName": name},
            "raw": _as_jsonable(event),
        }

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
