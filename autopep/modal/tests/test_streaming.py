from __future__ import annotations

from types import SimpleNamespace

from autopep_agent.streaming import normalize_stream_event


def test_normalize_text_delta_event() -> None:
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="hello"),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "assistant_token_delta"
    assert normalized["display"]["delta"] == "hello"


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


def test_normalize_agent_update() -> None:
    event = SimpleNamespace(
        type="agent_updated_stream_event",
        new_agent=SimpleNamespace(name="Autopep structure agent"),
    )

    normalized = normalize_stream_event(event)

    assert normalized is not None
    assert normalized["type"] == "agent_changed"
    assert normalized["summary"] == "Autopep structure agent"


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


def test_raw_event_uses_jsonable_model_dump() -> None:
    class FallbackValue:
        def __repr__(self) -> str:
            return "<fallback-value>"

    class DumpableEvent:
        type = "raw_response_event"
        data = SimpleNamespace(type="response.output_text.delta", delta="hello")

        def model_dump(self) -> dict[str, object]:
            return {
                "type": self.type,
                "data": {
                    "type": self.data.type,
                    "delta": self.data.delta,
                    "items": ("a", FallbackValue()),
                },
            }

    normalized = normalize_stream_event(DumpableEvent())

    assert normalized is not None
    assert normalized["raw"] == {
        "type": "raw_response_event",
        "data": {
            "type": "response.output_text.delta",
            "delta": "hello",
            "items": ["a", "<fallback-value>"],
        },
    }
