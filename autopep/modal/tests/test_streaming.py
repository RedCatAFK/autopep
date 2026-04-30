from __future__ import annotations

from types import SimpleNamespace

from autopep_agent.streaming import (
    SANDBOX_OUTPUT_MAX_BYTES,
    SandboxOutputCoalescer,
    cap_sandbox_output,
    extract_sandbox_event,
    normalize_stream_event,
)


def test_normalize_stream_event_drops_token_deltas() -> None:
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="hello"),
    )

    assert normalize_stream_event(event) is None


def test_normalize_stream_event_drops_response_created() -> None:
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.created"),
    )

    assert normalize_stream_event(event) is None


def test_normalize_stream_event_drops_response_completed() -> None:
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.completed"),
    )

    assert normalize_stream_event(event) is None


def test_normalize_message_output_event() -> None:
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="message_output_created",
        item=SimpleNamespace(raw_item={"type": "message", "content": "pong"}),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "assistant_message_completed"
    assert normalized["title"] == "Assistant message completed"


def test_normalize_tool_call_event() -> None:
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(
            type="tool_call_item",
            raw_item={"name": "search_structures"},
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_started"
    assert normalized["title"] == "Tool call started"
    assert normalized["display"]["name"] == "search_structures"


def test_normalize_stream_event_drops_agent_updated() -> None:
    event = SimpleNamespace(
        type="agent_updated_stream_event",
        new_agent=SimpleNamespace(name="Autopep structure agent"),
    )

    assert normalize_stream_event(event) is None


def test_normalize_hosted_tool_call_uses_raw_item_type() -> None:
    # Hosted tools (local_shell, web_search, file_search, computer,
    # code_interpreter, image_generation) do not carry a `.name` on the raw
    # item and never set `tool_origin`. Fall back to `raw_item.type`.
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(
            type="tool_call_item",
            raw_item={
                "type": "local_shell_call",
                "id": "call-shell-1",
                "action": {"command": ["echo", "hi"]},
            },
            tool_origin=None,
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_started"
    assert normalized["display"]["name"] == "local_shell_call"


def test_normalize_unknown_tool_call_omits_null_name() -> None:
    # If we genuinely cannot resolve a tool name, omit it from display rather
    # than serialising `{"name": null}` (which the UI renders as "name: null").
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(
            type="tool_call_item",
            raw_item={},
            tool_origin=None,
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_started"
    assert "name" not in normalized["display"]


def test_normalize_tool_output_event() -> None:
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_output",
        item=SimpleNamespace(
            raw_item={
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "{}",
            },
            tool_origin=SimpleNamespace(agent_tool_name="search_structures"),
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_completed"
    assert normalized["title"] == "Tool call completed"
    assert normalized["display"]["name"] == "search_structures"


def test_normalize_tool_output_event_without_tool_origin_omits_name() -> None:
    # Regression: when the SDK item has no tool_origin (the production shape
    # for function tool outputs), `raw_item.type == "function_call_output"`
    # must NOT be used as the tool name. Returning the literal item type as a
    # name caused every completed tool card in the UI to render as
    # "function_call_output". The name should be omitted so the UI resolves
    # it from the matching tool_call_started event via callId.
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_output",
        item=SimpleNamespace(
            raw_item={
                "type": "function_call_output",
                "call_id": "call-42",
                "output": "{}",
            },
            tool_origin=None,
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_completed"
    assert "name" not in normalized["display"]
    assert normalized["display"]["callId"] == "call-42"


def test_normalize_tool_call_started_emits_call_id() -> None:
    # The UI pairs tool_call_started with tool_call_completed via `callId`
    # to compute duration and (when the completed event has no name) resolve
    # the tool name. Without callId on the started event, the UI cannot pair
    # them and the started event vanishes from the timeline.
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(
            type="tool_call_item",
            raw_item={
                "type": "function_call",
                "name": "search_structures",
                "call_id": "call-99",
            },
        ),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "tool_call_started"
    assert normalized["display"]["name"] == "search_structures"
    assert normalized["display"]["callId"] == "call-99"


def test_normalize_reasoning_item_event() -> None:
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="reasoning_item_created",
        item=SimpleNamespace(raw_item={"id": "reasoning-1"}),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "reasoning_step"
    assert normalized["title"] == "Reasoning step"
    assert normalized["display"] == {}


def test_unknown_event_returns_none() -> None:
    event = SimpleNamespace(type="unknown_event")

    assert normalize_stream_event(event) is None


def test_normalize_stream_event_drops_sandbox_stdout_delta() -> None:
    event = SimpleNamespace(
        type="sandbox_stdout_delta",
        command_id="cmd-1",
        delta="hello",
    )

    assert normalize_stream_event(event) is None


def test_normalize_stream_event_drops_sandbox_stderr_delta() -> None:
    event = SimpleNamespace(
        type="sandbox_stderr_delta",
        command_id="cmd-1",
        delta="oops",
    )

    assert normalize_stream_event(event) is None


def test_extract_sandbox_event_returns_none_for_non_sandbox_events() -> None:
    event = SimpleNamespace(type="raw_response_event")
    assert extract_sandbox_event(event) is None


def test_extract_sandbox_event_normalizes_started_lifecycle_event() -> None:
    event = SimpleNamespace(
        type="sandbox_command_started",
        command_id="cmd-1",
        display={"command": "ls -la", "commandId": "cmd-1"},
    )

    extracted = extract_sandbox_event(event)

    assert extracted is not None
    assert extracted["type"] == "sandbox_command_started"
    assert extracted["command_id"] == "cmd-1"
    assert extracted["display"] == {"command": "ls -la", "commandId": "cmd-1"}


def test_extract_sandbox_event_reads_command_id_from_display() -> None:
    event = SimpleNamespace(
        type="sandbox_command_completed",
        display={"commandId": "cmd-2", "exitCode": 0},
    )

    extracted = extract_sandbox_event(event)

    assert extracted is not None
    assert extracted["command_id"] == "cmd-2"


def test_cap_sandbox_output_returns_text_unchanged_under_cap() -> None:
    text = "hello world"

    assert cap_sandbox_output(text, max_bytes=20) == text


def test_cap_sandbox_output_truncates_with_ellipsis_marker() -> None:
    text = "abcdefghij"

    capped = cap_sandbox_output(text, max_bytes=5)

    assert capped.endswith("…")
    assert len(capped) == 5
    assert capped == "abcd…"


def test_sandbox_output_coalescer_merges_chunks_into_completion_display() -> None:
    coalescer = SandboxOutputCoalescer()
    coalescer.start("cmd-1")
    coalescer.stdout_delta("cmd-1", "hello ")
    coalescer.stdout_delta("cmd-1", "world")
    coalescer.stderr_delta("cmd-1", "oops\n")

    enriched = coalescer.complete(
        "cmd-1",
        base_display={"commandId": "cmd-1", "exitCode": 0},
    )

    assert enriched == {
        "commandId": "cmd-1",
        "exitCode": 0,
        "stdout": "hello world",
        "stderr": "oops\n",
        "stdoutTruncated": False,
        "stderrTruncated": False,
    }


def test_sandbox_output_coalescer_returns_empty_strings_when_no_chunks() -> None:
    coalescer = SandboxOutputCoalescer()
    coalescer.start("cmd-1")

    enriched = coalescer.complete("cmd-1", base_display={"commandId": "cmd-1"})

    assert enriched["stdout"] == ""
    assert enriched["stderr"] == ""
    assert enriched["stdoutTruncated"] is False
    assert enriched["stderrTruncated"] is False


def test_sandbox_output_coalescer_truncates_stdout_at_default_cap() -> None:
    coalescer = SandboxOutputCoalescer()
    coalescer.start("cmd-1")
    long_chunk = "a" * (SANDBOX_OUTPUT_MAX_BYTES + 500)
    coalescer.stdout_delta("cmd-1", long_chunk)

    enriched = coalescer.complete("cmd-1")

    assert enriched["stdoutTruncated"] is True
    assert len(enriched["stdout"]) == SANDBOX_OUTPUT_MAX_BYTES
    assert enriched["stdout"].endswith("…")
    assert enriched["stderrTruncated"] is False


def test_sandbox_output_coalescer_isolates_buffers_per_command_id() -> None:
    coalescer = SandboxOutputCoalescer()
    coalescer.start("cmd-1")
    coalescer.start("cmd-2")
    coalescer.stdout_delta("cmd-1", "from-1")
    coalescer.stdout_delta("cmd-2", "from-2")

    enriched_1 = coalescer.complete("cmd-1")
    enriched_2 = coalescer.complete("cmd-2")

    assert enriched_1["stdout"] == "from-1"
    assert enriched_2["stdout"] == "from-2"


def test_sandbox_output_coalescer_pop_is_idempotent_for_unknown_command() -> None:
    # Defensive: a completed event with a never-buffered command_id should
    # still produce an empty-but-present stdout/stderr payload rather than
    # crashing.
    coalescer = SandboxOutputCoalescer()

    enriched = coalescer.complete("never-started", base_display={"exitCode": 1})

    assert enriched == {
        "exitCode": 1,
        "stdout": "",
        "stderr": "",
        "stdoutTruncated": False,
        "stderrTruncated": False,
    }


def test_raw_event_uses_jsonable_model_dump() -> None:
    class FallbackValue:
        def __repr__(self) -> str:
            return "<fallback-value>"

    class DumpableEvent:
        type = "run_item_stream_event"
        name = "tool_called"
        item = SimpleNamespace(
            type="tool_call_item",
            raw_item={"name": "search_structures"},
        )

        def model_dump(self) -> dict[str, object]:
            return {
                "type": self.type,
                "name": self.name,
                "item": {
                    "type": "tool_call_item",
                    "raw_item": {"name": "search_structures"},
                    "items": ("a", FallbackValue()),
                },
            }

    normalized = normalize_stream_event(DumpableEvent())

    assert normalized is not None
    assert normalized["raw"] == {
        "type": "run_item_stream_event",
        "name": "tool_called",
        "item": {
            "type": "tool_call_item",
            "raw_item": {"name": "search_structures"},
            "items": ["a", "<fallback-value>"],
        },
    }
