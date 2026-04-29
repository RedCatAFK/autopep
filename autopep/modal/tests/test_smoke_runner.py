from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from autopep_agent import runner as runner_mod
from autopep_agent.db import AgentRunContext


REQUIRED_RUNTIME_ENV = {
    "DATABASE_URL": "postgresql://test:test@db.example/autopep",
    "R2_BUCKET": "autopep-test",
    "R2_ACCOUNT_ID": "account",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "MODAL_PROTEINA_URL": "https://proteina.example/run",
    "MODAL_PROTEINA_API_KEY": "p",
    "MODAL_CHAI_URL": "https://chai.example/run",
    "MODAL_CHAI_API_KEY": "c",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL": "https://score.example/run",
    "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY": "s",
    "OPENAI_API_KEY": "openai-test",
}


class _FakeEventWriter:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.events: list[dict[str, Any]] = []

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        title: str,
        summary: str | None = None,
        display: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "display": display,
                "raw": raw,
                "run_id": run_id,
                "summary": summary,
                "title": title,
                "type": event_type,
            },
        )


class _FakeStreamedRun:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []

    def stream_events(self) -> Any:
        return iter(self._events)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_RUNTIME_ENV.items():
        monkeypatch.setenv(key, value)


def _wire_writer(monkeypatch: pytest.MonkeyPatch) -> _FakeEventWriter:
    writer = _FakeEventWriter(REQUIRED_RUNTIME_ENV["DATABASE_URL"])
    monkeypatch.setattr(runner_mod, "EventWriter", lambda _database_url: writer)
    return writer


def _wire_run_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: str | None,
    task_kind: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    claimed: list[str] = []
    completed: list[str] = []
    failed: list[tuple[str, str]] = []

    async def fake_claim_run(_database_url: str, *, run_id: str) -> bool:
        claimed.append(run_id)
        return True

    async def fake_get_run_context(*_args: Any, **_kwargs: Any) -> AgentRunContext:
        return AgentRunContext(
            prompt="ping",
            model=model,
            task_kind=task_kind,
            enabled_recipes=["must not reach biology agent"],
        )

    async def fake_mark_completed(_database_url: str, run_id: str) -> None:
        completed.append(run_id)

    async def fake_mark_failed(
        _database_url: str,
        run_id: str,
        error_summary: str,
    ) -> None:
        failed.append((run_id, error_summary))

    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(runner_mod, "mark_run_failed", fake_mark_failed)
    return completed, failed


def _wire_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[Any] | None = None,
) -> MagicMock:
    runner_double = MagicMock()
    runner_double.run_streamed = MagicMock(return_value=_FakeStreamedRun(events))
    monkeypatch.setattr(runner_mod, "Runner", runner_double)
    return runner_double


def _wire_sandbox_client(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            calls.append("start")
            return self

        async def __aexit__(self, *_args: Any) -> None:
            calls.append("close")

        async def exec(
            self,
            command: str,
            *,
            shell: bool,
            timeout: int,
        ) -> SimpleNamespace:
            calls.append(f"exec:{command}:{shell}:{timeout}")
            return SimpleNamespace(stdout=b"sandbox-ok\n", stderr=b"", exit_code=0)

    class FakeClient:
        async def create(self, *, options: Any) -> FakeSession:
            calls.append(f"create:{getattr(options, 'app_name', '')}")
            return FakeSession()

        async def delete(self, session: FakeSession) -> FakeSession:
            calls.append("delete")
            return session

    class FakeOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    monkeypatch.setattr(runner_mod, "ModalSandboxClient", FakeClient)
    monkeypatch.setattr(runner_mod, "ModalSandboxClientOptions", FakeOptions)
    return calls


@pytest.mark.asyncio
async def test_smoke_run_disabled_records_failure_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("AUTOPEP_ALLOW_SMOKE_RUNS", raising=False)
    writer = _wire_writer(monkeypatch)
    _completed, failed = _wire_run_context(
        monkeypatch,
        model=None,
        task_kind="smoke_chat",
    )
    runner_double = _wire_runner(monkeypatch)

    with pytest.raises(RuntimeError, match="AUTOPEP_ALLOW_SMOKE_RUNS=1"):
        await runner_mod.execute_run("run-smoke-disabled", "thread-1", "workspace-1")

    assert [event["type"] for event in writer.events] == [
        "run_started",
        "run_failed",
    ]
    assert failed == [
        (
            "run-smoke-disabled",
            "Smoke runs require AUTOPEP_ALLOW_SMOKE_RUNS=1.",
        ),
    ]
    runner_double.run_streamed.assert_not_called()


@pytest.mark.asyncio
async def test_smoke_chat_routes_to_ping_agent_and_uses_default_mini_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AUTOPEP_ALLOW_SMOKE_RUNS", "1")
    writer = _wire_writer(monkeypatch)
    completed, failed = _wire_run_context(
        monkeypatch,
        model=None,
        task_kind="smoke_chat",
    )
    runner_double = _wire_runner(
        monkeypatch,
        events=[
            {
                "type": "raw_response_event",
                "data": {"type": "response.output_text.delta", "delta": "pong"},
            },
            {
                "type": "raw_response_event",
                "data": {"type": "response.completed"},
            },
        ],
    )
    run_configs: list[dict[str, Any]] = []

    monkeypatch.setattr(
        runner_mod,
        "_build_run_config",
        lambda **kwargs: run_configs.append(kwargs) or {"run_config": kwargs},
    )

    await runner_mod.execute_run("run-smoke-chat", "thread-1", "workspace-1")

    agent = runner_double.run_streamed.call_args.args[0]
    assert agent.name == "Autopep smoke ping"
    assert agent.model == "gpt-5.4-mini"
    assert run_configs[0]["model"] == "gpt-5.4-mini"
    assert "generate_binder_candidates" not in {
        getattr(tool, "name", "") for tool in getattr(agent, "tools", [])
    }
    # Token deltas and raw response lifecycle events are no longer persisted
    # to the agent_events ledger — they will be streamed via Modal SSE in
    # Task 2.5. Only the run lifecycle events should be appended here.
    assert [event["type"] for event in writer.events] == [
        "run_started",
        "run_completed",
    ]
    assert completed == ["run-smoke-chat"]
    assert failed == []


@pytest.mark.asyncio
async def test_smoke_tool_routes_to_tool_agent_with_explicit_mini_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AUTOPEP_ALLOW_SMOKE_RUNS", "1")
    _wire_writer(monkeypatch)
    completed, failed = _wire_run_context(
        monkeypatch,
        model="gpt-5.5-mini",
        task_kind="smoke_tool",
    )
    runner_double = _wire_runner(
        monkeypatch,
        events=[
            {
                "type": "run_item_stream_event",
                "name": "tool_called",
                "item": {"raw_item": {"name": "smoke_now"}},
            },
            {
                "type": "run_item_stream_event",
                "name": "tool_output",
                "item": {
                    "raw_item": {
                        "type": "function_call_output",
                        "output": "now-ok",
                    },
                    "tool_origin": {"agent_tool_name": "smoke_now"},
                },
            },
            {
                "type": "raw_response_event",
                "data": {"type": "response.output_text.delta", "delta": "now-ok"},
            },
            {
                "type": "raw_response_event",
                "data": {"type": "response.completed"},
            },
        ],
    )
    run_configs: list[dict[str, Any]] = []

    monkeypatch.setattr(
        runner_mod,
        "_build_run_config",
        lambda **kwargs: run_configs.append(kwargs) or {"run_config": kwargs},
    )

    await runner_mod.execute_run("run-smoke-tool", "thread-1", "workspace-1")

    agent = runner_double.run_streamed.call_args.args[0]
    assert agent.name == "Autopep smoke tool"
    assert agent.model == "gpt-5.5-mini"
    assert {"smoke_now"} == {
        getattr(tool, "name", "") for tool in getattr(agent, "tools", [])
    }
    assert run_configs[0]["model"] == "gpt-5.5-mini"
    assert completed == ["run-smoke-tool"]
    assert failed == []


@pytest.mark.asyncio
async def test_smoke_run_overrides_persisted_production_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AUTOPEP_ALLOW_SMOKE_RUNS", "1")
    _wire_writer(monkeypatch)
    _completed, _failed = _wire_run_context(
        monkeypatch,
        model="gpt-5.4",
        task_kind="smoke_chat",
    )
    runner_double = _wire_runner(
        monkeypatch,
        events=[
            {
                "type": "raw_response_event",
                "data": {"type": "response.completed"},
            },
        ],
    )

    await runner_mod.execute_run("run-smoke-default", "thread-1", "workspace-1")

    agent = runner_double.run_streamed.call_args.args[0]
    assert agent.model == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_smoke_sandbox_emits_sandbox_events_without_biology_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AUTOPEP_ALLOW_SMOKE_RUNS", "1")
    writer = _wire_writer(monkeypatch)
    completed, failed = _wire_run_context(
        monkeypatch,
        model=None,
        task_kind="smoke_sandbox",
    )
    runner_double = _wire_runner(monkeypatch)
    built_configs: list[dict[str, Any]] = []

    monkeypatch.setattr(
        runner_mod,
        "_build_run_config",
        lambda **kwargs: built_configs.append(kwargs) or {"run_config": kwargs},
    )
    sandbox_calls = _wire_sandbox_client(monkeypatch)

    await runner_mod.execute_run("run-smoke-sandbox", "thread-1", "workspace-1")

    assert [event["type"] for event in writer.events] == [
        "run_started",
        "sandbox_command_started",
        "sandbox_stdout_delta",
        "sandbox_command_completed",
        "assistant_message_completed",
        "run_completed",
    ]
    assert writer.events[2]["display"] == {"delta": "sandbox-ok\n"}
    assert built_configs[0]["model"] == "gpt-5.4-mini"
    assert sandbox_calls == [
        "create:autopep-agent-runtime",
        "start",
        "exec:echo sandbox-ok:True:30",
        "close",
        "delete",
    ]
    runner_double.run_streamed.assert_not_called()
    assert completed == ["run-smoke-sandbox"]
    assert failed == []
