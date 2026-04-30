from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


MAX_LOG_STRING_CHARS = 1000
MAX_LOG_LIST_ITEMS = 40
MAX_LOG_DICT_ITEMS = 80


def _safe_log_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_LOG_STRING_CHARS:
            return value
        return f"{value[:MAX_LOG_STRING_CHARS]}...<{len(value)} chars>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        items = list(value.items())
        safe = {
            str(key): _safe_log_value(item_value)
            for key, item_value in items[:MAX_LOG_DICT_ITEMS]
        }
        if len(items) > MAX_LOG_DICT_ITEMS:
            safe["_truncated_items"] = len(items) - MAX_LOG_DICT_ITEMS
        return safe
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        safe_items = [_safe_log_value(item) for item in items[:MAX_LOG_LIST_ITEMS]]
        if len(items) > MAX_LOG_LIST_ITEMS:
            safe_items.append(f"...<{len(items) - MAX_LOG_LIST_ITEMS} more items>")
        return safe_items
    return str(value)


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **{key: _safe_log_value(value) for key, value in fields.items()},
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
