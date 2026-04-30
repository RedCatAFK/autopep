from julia_agent.events import (
    normalize_run_error,
    normalize_run_status,
    normalize_text_delta,
    normalize_tool_call_completed,
    normalize_tool_call_started,
)


def test_normalize_text_delta_uses_string_payload() -> None:
    assert normalize_text_delta("run_1", "hello") == {
        "runId": "run_1",
        "type": "text_delta",
        "payload": {"text": "hello"},
    }


def test_normalize_tool_events_include_name_and_payload() -> None:
    started = normalize_tool_call_started("run_1", "search", {"query": "bace1"})
    completed = normalize_tool_call_completed("run_1", "search", {"path": "/tmp/out.json"})

    assert started == {
        "runId": "run_1",
        "type": "tool_call_started",
        "payload": {"name": "search", "input": {"query": "bace1"}},
    }
    assert completed == {
        "runId": "run_1",
        "type": "tool_call_completed",
        "payload": {"name": "search", "result": {"path": "/tmp/out.json"}},
    }


def test_normalize_status_and_error_payloads() -> None:
    assert normalize_run_status("run_1", "running") == {
        "runId": "run_1",
        "type": "run_status",
        "payload": {"status": "running"},
    }
    assert normalize_run_error("run_1", RuntimeError("blocked")) == {
        "runId": "run_1",
        "type": "run_error",
        "payload": {"message": "blocked", "code": "RuntimeError"},
    }
