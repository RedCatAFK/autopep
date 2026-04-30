from __future__ import annotations

from autopep_agent.ci_evals import (
    REQUIRED_ORCHESTRATION_TOOLS,
    assert_orchestration_trace_passes,
    build_deterministic_ci_trace,
    evaluate_orchestration_trace,
)


def test_deterministic_ci_trace_passes() -> None:
    result = assert_orchestration_trace_passes(build_deterministic_ci_trace())

    assert result.metrics["required_tools_completed"] == len(
        REQUIRED_ORCHESTRATION_TOOLS,
    )
    assert result.metrics["artifact_count"] == 3
    assert result.metrics["candidate_count"] == 1


def test_trace_eval_pairs_tool_completions_by_call_id() -> None:
    result = evaluate_orchestration_trace(build_deterministic_ci_trace())

    assert result.passed is True
    for positions in result.metrics["tool_positions"].values():
        assert positions["completed"] is not None


def test_trace_eval_fails_when_required_tool_is_missing() -> None:
    events = [
        event
        for event in build_deterministic_ci_trace()
        if event.get("display", {}).get("name") != "pdb_fetch"
        and event.get("display", {}).get("callId") != "call-pdb_fetch"
    ]

    result = evaluate_orchestration_trace(events)

    assert result.passed is False
    assert "missing tool_call_started for pdb_fetch" in result.failures


def test_trace_eval_fails_when_assistant_answers_before_scoring() -> None:
    events = build_deterministic_ci_trace()
    assistant = next(
        event
        for event in events
        if event["type"] == "assistant_message_completed"
    )
    events.remove(assistant)
    score_start_idx = next(
        index
        for index, event in enumerate(events)
        if event.get("display", {}).get("name") == "score_candidates"
    )
    events.insert(score_start_idx, assistant)

    result = evaluate_orchestration_trace(events)

    assert result.passed is False
    assert (
        "assistant message completed before score_candidates finished"
        in result.failures
    )
