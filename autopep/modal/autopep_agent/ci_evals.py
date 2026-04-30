from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


Event = Mapping[str, Any]

REQUIRED_ORCHESTRATION_TOOLS: tuple[str, ...] = (
    "literature_search",
    "pdb_search",
    "pdb_fetch",
    "proteina_design",
    "chai_fold_complex",
    "score_candidates",
)


@dataclass(frozen=True)
class TraceEvalResult:
    """Result of the cheap CI orchestration trace eval.

    The eval is intentionally ledger-shaped: it consumes the same event fields
    persisted in ``agent_events`` so we can run it against deterministic
    fixtures in CI now and production traces later.
    """

    passed: bool
    failures: tuple[str, ...]
    metrics: Mapping[str, Any]


def _display(event: Event) -> Mapping[str, Any]:
    display = event.get("display") or event.get("displayJson") or {}
    return display if isinstance(display, Mapping) else {}


def _event_type(event: Event) -> str:
    return str(event.get("type") or "")


def _call_id(event: Event) -> str | None:
    display = _display(event)
    call_id = display.get("callId") or display.get("call_id") or display.get(
        "toolCallId",
    )
    return str(call_id) if call_id else None


def _tool_name(event: Event) -> str | None:
    display = _display(event)
    name = display.get("name")
    return str(name) if name else None


def _first_index_after(
    events: Sequence[Event],
    start: int,
    *,
    event_type: str,
    call_id: str | None = None,
    tool_name: str | None = None,
) -> int | None:
    for index in range(start + 1, len(events)):
        event = events[index]
        if _event_type(event) != event_type:
            continue
        if call_id is not None and _call_id(event) == call_id:
            return index
        if call_id is None and tool_name is not None and _tool_name(event) == tool_name:
            return index
    return None


def _indexes_for_tool(
    events: Sequence[Event],
    tool_name: str,
) -> tuple[int | None, int | None]:
    start_idx = next(
        (
            index
            for index, event in enumerate(events)
            if _event_type(event) == "tool_call_started"
            and _tool_name(event) == tool_name
        ),
        None,
    )
    if start_idx is None:
        return None, None

    call_id = _call_id(events[start_idx])
    completed_idx = _first_index_after(
        events,
        start_idx,
        event_type="tool_call_completed",
        call_id=call_id,
        tool_name=tool_name,
    )
    return start_idx, completed_idx


def evaluate_orchestration_trace(
    events: Sequence[Event],
    *,
    required_tools: Sequence[str] = REQUIRED_ORCHESTRATION_TOOLS,
) -> TraceEvalResult:
    """Evaluate a single run's orchestration ledger for CI suitability.

    This is not a biological-quality eval. It verifies that a run has the
    minimum deterministic shape expected from Autopep's binder loop:
    lifecycle events, ordered tool calls, tool completions, persisted
    artifacts/candidates, and a final assistant response after scoring.
    """

    failures: list[str] = []
    event_types = [_event_type(event) for event in events]

    if not events:
        return TraceEvalResult(
            passed=False,
            failures=("trace is empty",),
            metrics={"event_count": 0},
        )

    if "run_started" not in event_types:
        failures.append("missing run_started event")
    if "run_completed" not in event_types:
        failures.append("missing run_completed event")
    if "run_failed" in event_types:
        failures.append("trace contains run_failed event")

    tool_positions: dict[str, dict[str, int | None]] = {}
    previous_start: int | None = None
    for tool in required_tools:
        start_idx, completed_idx = _indexes_for_tool(events, tool)
        tool_positions[tool] = {"started": start_idx, "completed": completed_idx}

        if start_idx is None:
            failures.append(f"missing tool_call_started for {tool}")
            continue
        if completed_idx is None:
            failures.append(f"missing tool_call_completed for {tool}")
        if previous_start is not None and start_idx < previous_start:
            failures.append(f"{tool} started before the prior required tool")
        previous_start = start_idx

    score_completed_idx = tool_positions.get("score_candidates", {}).get("completed")
    assistant_idx = next(
        (
            index
            for index, event in enumerate(events)
            if _event_type(event) == "assistant_message_completed"
        ),
        None,
    )
    if assistant_idx is None:
        failures.append("missing assistant_message_completed event")
    elif score_completed_idx is not None and assistant_idx < score_completed_idx:
        failures.append("assistant message completed before score_candidates finished")

    artifact_count = event_types.count("artifact_created")
    candidate_count = event_types.count("candidate_ranked")
    if artifact_count == 0:
        failures.append("no artifact_created events")
    if candidate_count == 0:
        failures.append("no candidate_ranked events")

    metrics: dict[str, Any] = {
        "event_count": len(events),
        "artifact_count": artifact_count,
        "candidate_count": candidate_count,
        "required_tools_completed": sum(
            1
            for positions in tool_positions.values()
            if positions["started"] is not None and positions["completed"] is not None
        ),
        "required_tool_count": len(tuple(required_tools)),
        "tool_positions": tool_positions,
    }
    return TraceEvalResult(
        passed=not failures,
        failures=tuple(failures),
        metrics=metrics,
    )


def assert_orchestration_trace_passes(events: Sequence[Event]) -> TraceEvalResult:
    result = evaluate_orchestration_trace(events)
    if not result.passed:
        details = "\n".join(f"- {failure}" for failure in result.failures)
        raise AssertionError(f"Autopep CI orchestration eval failed:\n{details}")
    return result


def build_deterministic_ci_trace() -> list[dict[str, Any]]:
    """Return the mocked full-loop trace used by the PR CI eval.

    The event shape mirrors ``agent_events`` rows but uses plain dicts so the
    check has no DB, Modal, R2, or model dependency.
    """

    events: list[dict[str, Any]] = [
        {"type": "run_started", "display": {"taskKind": "chat"}},
    ]
    for tool in REQUIRED_ORCHESTRATION_TOOLS:
        call_id = f"call-{tool}"
        events.append(
            {
                "type": "tool_call_started",
                "display": {"name": tool, "callId": call_id},
            },
        )
        if tool == "pdb_fetch":
            events.append(
                {
                    "type": "artifact_created",
                    "display": {
                        "artifactId": "artifact-pdb-6lu7",
                        "kind": "pdb",
                        "pdbId": "6LU7",
                    },
                },
            )
        if tool == "proteina_design":
            events.extend(
                [
                    {
                        "type": "artifact_created",
                        "display": {
                            "artifactId": "artifact-proteina-candidate-1",
                            "kind": "proteina_result",
                        },
                    },
                    {
                        "type": "candidate_ranked",
                        "display": {
                            "candidateId": "candidate-1",
                            "rank": 1,
                            "source": "proteina_complexa",
                        },
                    },
                ],
            )
        if tool == "chai_fold_complex":
            events.append(
                {
                    "type": "artifact_created",
                    "display": {
                        "artifactId": "artifact-chai-candidate-1",
                        "kind": "chai_result",
                    },
                },
            )
        events.append(
            {
                "type": "tool_call_completed",
                # Production completed events may not carry the tool name; the
                # eval must pair them via callId just like the UI does.
                "display": {"callId": call_id},
            },
        )
    events.extend(
        [
            {
                "type": "assistant_message_completed",
                "display": {
                    "text": (
                        "Top candidate: candidate-1 against PDB 6LU7; "
                        "scores include D-SCRIPT 0.84 and Prodigy -9.6 kcal/mol."
                    ),
                },
            },
            {"type": "run_completed", "display": {}},
        ],
    )
    return events


def main() -> int:
    result = assert_orchestration_trace_passes(build_deterministic_ci_trace())
    print("Autopep CI orchestration eval passed")
    print(f"events={result.metrics['event_count']}")
    print(
        "required_tools="
        f"{result.metrics['required_tools_completed']}/"
        f"{result.metrics['required_tool_count']}",
    )
    print(f"artifacts={result.metrics['artifact_count']}")
    print(f"candidates={result.metrics['candidate_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
