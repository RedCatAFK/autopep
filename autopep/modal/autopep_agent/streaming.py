from __future__ import annotations

from typing import Any


# Maximum bytes of coalesced stdout / stderr we keep on the
# ``sandbox_command_completed`` event's display payload. Anything past this
# is dropped and the matching ``stdoutTruncated`` / ``stderrTruncated`` flag
# is set so the UI can show a "(truncated)" hint instead of paging in
# megabytes of build output.
SANDBOX_OUTPUT_MAX_BYTES = 10_000


def cap_sandbox_output(text: str, *, max_bytes: int = SANDBOX_OUTPUT_MAX_BYTES) -> str:
    """Truncate ``text`` to at most ``max_bytes`` bytes (UTF-8 length).

    Returns ``text`` unchanged when it is already within the cap. When the
    text exceeds the cap, returns the first ``max_bytes - 1`` characters
    followed by a single ellipsis so the UI can render a truncation hint
    without manual byte arithmetic. We measure length in characters rather
    than encoded bytes — sandbox output is overwhelmingly ASCII for binder
    pipelines and the 10 KB cap is a soft ceiling, not a hard transport
    limit.
    """
    if len(text) <= max_bytes:
        return text
    if max_bytes <= 0:
        return ""
    return text[: max_bytes - 1] + "…"


class SandboxOutputCoalescer:
    """Buffer per-chunk sandbox stdout / stderr deltas until command completion.

    The Agents SDK (and our smoke sandbox path) can emit a steady stream of
    ``sandbox_stdout_delta`` / ``sandbox_stderr_delta`` events, one per chunk
    flushed by the underlying process. Persisting each delta to the durable
    ``agent_events`` ledger bloats the ledger and makes the UI's per-event
    rendering quadratic. Instead, we keep the chunks in memory keyed by
    ``commandId`` and merge them into the parent ``sandbox_command_completed``
    event's ``display`` payload, where the UI can render the full output as a
    single block.
    """

    def __init__(self, *, max_bytes: int = SANDBOX_OUTPUT_MAX_BYTES) -> None:
        self._max_bytes = max_bytes
        self._buffers: dict[str, dict[str, list[str]]] = {}

    def start(self, command_id: str) -> None:
        """Allocate fresh stdout / stderr buffers for ``command_id``.

        Safe to call repeatedly — a re-start (e.g. retried command) discards
        any previously buffered chunks for that ``command_id``.
        """
        self._buffers[command_id] = {"stdout": [], "stderr": []}

    def stdout_delta(self, command_id: str, text: str) -> None:
        """Append a stdout chunk. Lazily allocates the buffer on first use."""
        self._buffers.setdefault(command_id, {"stdout": [], "stderr": []})["stdout"].append(text)

    def stderr_delta(self, command_id: str, text: str) -> None:
        """Append a stderr chunk. Lazily allocates the buffer on first use."""
        self._buffers.setdefault(command_id, {"stdout": [], "stderr": []})["stderr"].append(text)

    def complete(
        self,
        command_id: str,
        base_display: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the enriched display dict for ``sandbox_command_completed``.

        Pops the buffer for ``command_id`` and returns ``base_display`` merged
        with the coalesced ``stdout`` / ``stderr`` (capped at
        ``SANDBOX_OUTPUT_MAX_BYTES``) plus matching ``stdoutTruncated`` /
        ``stderrTruncated`` flags. If no chunks were buffered for that
        ``command_id`` (e.g. the command produced no output, or the started /
        completed events arrived without any deltas in between) the stdout /
        stderr fields are still present as empty strings so consumers can
        treat them as always-present.
        """
        buffer = self._buffers.pop(command_id, {"stdout": [], "stderr": []})
        combined_stdout = "".join(buffer["stdout"])
        combined_stderr = "".join(buffer["stderr"])

        merged: dict[str, Any] = dict(base_display or {})
        merged["stdout"] = cap_sandbox_output(combined_stdout, max_bytes=self._max_bytes)
        merged["stderr"] = cap_sandbox_output(combined_stderr, max_bytes=self._max_bytes)
        merged["stdoutTruncated"] = len(combined_stdout) > self._max_bytes
        merged["stderrTruncated"] = len(combined_stderr) > self._max_bytes
        return merged


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
        # Hosted tools (local_shell_call, web_search_call, file_search_call,
        # computer_call, code_interpreter_call, image_generation_call) carry
        # their identity in `raw_item.type` rather than `.name`. The
        # `function_call_output` item type, however, is a tool *output* (the
        # message we send back to the model) and has no name of its own — its
        # tool name lives on the matching `function_call` looked up by
        # `call_id`. Return None so the UI resolves the name from the paired
        # tool_call_started event instead of rendering "function_call_output".
        raw_type = _get(raw_item, "type")
        if raw_type == "function_call_output":
            return None
        name = raw_type
    if name is None:
        return None
    return str(name)


def _call_id(item: Any) -> str | None:
    raw_item = _get(item, "raw_item", {}) or {}
    call_id = _get(raw_item, "call_id")
    if call_id is None:
        call_id = _get(raw_item, "id")
    if call_id is None:
        return None
    return str(call_id)


SANDBOX_DELTA_EVENT_TYPES = frozenset(
    {"sandbox_stdout_delta", "sandbox_stderr_delta"},
)
SANDBOX_LIFECYCLE_EVENT_TYPES = frozenset(
    {"sandbox_command_started", "sandbox_command_completed"},
)


def extract_sandbox_event(event: Any) -> dict[str, Any] | None:
    """Return a structured view of a sandbox stream event, or ``None``.

    The Agents SDK exposes sandbox lifecycle and per-chunk delta events in
    several shapes depending on version (top-level ``type``, nested under
    ``data``, dict vs object). This helper normalizes those shapes into a
    flat dict the runner can switch on:

      ``{"type": "sandbox_command_started" | "sandbox_command_completed" |
                  "sandbox_stdout_delta" | "sandbox_stderr_delta",
        "command_id": str | None,
        "text": str,           # only for delta events
        "display": dict,       # base display payload for lifecycle events
        "raw": <jsonable>}``

    Returns ``None`` for any event that is not a sandbox event so callers
    can fall through to the rest of the normalization pipeline.
    """
    event_type = _get(event, "type")
    if event_type in SANDBOX_DELTA_EVENT_TYPES:
        text = _get(event, "delta")
        if text is None:
            text = _get(event, "text", "")
        return {
            "type": str(event_type),
            "command_id": _coerce_str(_get(event, "command_id")),
            "text": str(text or ""),
            "display": {},
            "raw": _as_jsonable(event),
        }
    if event_type in SANDBOX_LIFECYCLE_EVENT_TYPES:
        display = _get(event, "display") or {}
        if not isinstance(display, dict):
            display = {}
        command_id = _coerce_str(_get(event, "command_id")) or _coerce_str(
            display.get("commandId") if isinstance(display, dict) else None,
        )
        return {
            "type": str(event_type),
            "command_id": command_id,
            "text": "",
            "display": dict(display),
            "raw": _as_jsonable(event),
        }
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def normalize_stream_event(event: Any) -> dict[str, Any] | None:
    event_type = _get(event, "type")

    if event_type in SANDBOX_DELTA_EVENT_TYPES:
        # Per-chunk sandbox stdout / stderr deltas are NEVER persisted to the
        # durable ledger — the runner buffers them via SandboxOutputCoalescer
        # and merges the final text into the parent sandbox_command_completed
        # event's display payload.
        return None

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
        call_id = _call_id(item)
        # Omit `name` from display when we couldn't resolve one — emitting
        # `{"name": null}` causes the frontend to render a literal "name: null"
        # row instead of falling through to the unknown-tool view.
        tool_display: dict[str, Any] = {}
        if tool_name is not None:
            tool_display["name"] = tool_name
        # Emit `callId` so the frontend can pair tool_call_started with its
        # matching tool_call_completed event (for duration + name lookup).
        # The completed event's raw_item is a `function_call_output` with no
        # `name`, so the UI relies on this correlation to display the real
        # tool name from the started event.
        if call_id is not None:
            tool_display["callId"] = call_id
        raw = _as_jsonable(event)

        if name == "tool_called":
            return {
                "type": "tool_call_started",
                "title": "Tool call started",
                "summary": tool_name,
                "display": tool_display,
                "raw": raw,
            }

        if name == "tool_output":
            return {
                "type": "tool_call_completed",
                "title": "Tool call completed",
                "summary": tool_name,
                "display": tool_display,
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
