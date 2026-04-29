from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from autopep_agent import runner as runner_mod
from autopep_agent.db import AgentRunContext, AttachmentRow
from autopep_agent.run_context import get_tool_run_context
from autopep_agent.runner import (
    build_agent_instructions,
    build_autopep_agent,
    build_sandbox_config,
    choose_task_kind,
    execute_run,
)


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


def _tool_names(tools: list[object]) -> set[str]:
    return {str(getattr(tool, "name", "")) for tool in tools}


def test_choose_task_kind_routes_branch_design_prompt() -> None:
    assert (
        choose_task_kind("Generate a protein that binds to 3CL-protease")
        == "branch_design"
    )


def test_choose_task_kind_routes_general_explanation_to_chat() -> None:
    assert choose_task_kind("Explain this residue selection") == "chat"


def test_build_agent_instructions_mentions_workflow_tools_and_recipes() -> None:
    recipe = "Use PDB and bioRxiv first."

    instructions = build_agent_instructions(enabled_recipes=[recipe])

    assert "life-science-research" in instructions
    assert "generate_binder_candidates" in instructions
    assert "fold_sequences_with_chai" in instructions
    assert "score_candidate_interactions" in instructions
    assert recipe in instructions


def test_build_autopep_agent_includes_biology_tools() -> None:
    agent = build_autopep_agent(enabled_recipes=[])

    assert agent.name == "Autopep"
    assert {
        "generate_binder_candidates",
        "fold_sequences_with_chai",
        "score_candidate_interactions",
    }.issubset(_tool_names(agent.tools))


@pytest.mark.asyncio
async def test_execute_run_routes_branch_design_to_demo_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)
    runner_double, _streamed = _wire_fake_runner(monkeypatch)

    async def fake_get_run_context(*_args: Any, **_kwargs: Any) -> AgentRunContext:
        return AgentRunContext(
            prompt="Generate a protein that binds to 3CL-protease",
            model=None,
            task_kind="branch_design",
            enabled_recipes=["run the demo recipe"],
        )

    async def fake_claim_run(*_args: Any, **_kwargs: Any) -> bool:
        return True

    demo_calls: list[dict[str, Any]] = []

    async def fake_execute_demo_one_loop(**kwargs: Any) -> dict[str, Any]:
        demo_calls.append(kwargs)
        assert get_tool_run_context().run_id == "r-demo"
        await kwargs["writer"].append_event(
            run_id=kwargs["run_id"],
            event_type="assistant_message_completed",
            title="MVP loop complete",
        )
        return {"candidate_count": 1}

    completed: list[str] = []

    async def fake_mark_completed(_url: str, run_id: str) -> None:
        completed.append(run_id)

    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "execute_demo_one_loop", fake_execute_demo_one_loop)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)

    await execute_run(run_id="r-demo", thread_id="t1", workspace_id="w1")

    assert len(demo_calls) == 1
    assert demo_calls[0]["run_id"] == "r-demo"
    assert [event["type"] for event in writer.events] == [
        "run_started",
        "assistant_message_completed",
        "run_completed",
    ]
    runner_double.run_streamed.assert_not_called()
    assert completed == ["r-demo"]


def test_build_sandbox_config_returns_usable_object_without_network() -> None:
    sandbox_config = build_sandbox_config()

    assert sandbox_config is not None


# --- execute_run integration tests with fake DB / EventWriter / Runner ---


class _FakeEventWriter:
    """Captures append_event calls in order. Mirrors real EventWriter signature."""

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
                "run_id": run_id,
                "type": event_type,
                "title": title,
                "summary": summary,
                "display": display,
                "raw": raw,
            },
        )


class _FakeStreamedRun:
    """Stand-in for the SDK's streamed-run object with a sync iterator of events."""

    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []

    def stream_events(self) -> Any:
        return iter(self._events)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_RUNTIME_ENV.items():
        monkeypatch.setenv(key, value)


def _wire_fake_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    streamed: _FakeStreamedRun | None = None,
) -> tuple[MagicMock, _FakeStreamedRun]:
    streamed_run = streamed or _FakeStreamedRun([])
    runner_double = MagicMock()
    runner_double.run_streamed = MagicMock(return_value=streamed_run)
    monkeypatch.setattr(runner_mod, "Runner", runner_double)
    # Avoid building real RunConfig (with sandbox) which may pull network.
    monkeypatch.setattr(
        runner_mod,
        "_build_run_config",
        lambda **_kwargs: object(),
    )
    return runner_double, streamed_run


def _stub_get_run_attachments(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[AttachmentRow] | None = None,
) -> list[AttachmentRow]:
    """Replace ``runner_mod.get_run_attachments`` with an in-memory stub.

    The default returns an empty list so existing happy-path tests do not
    accidentally hit a real database when execute_run starts looking up
    attachments. Pass ``rows`` to drive the new attachment-mounting test.
    """

    fixed = list(rows or [])

    async def _fake_get_run_attachments(
        _database_url: str,
        *,
        run_id: str,
    ) -> list[AttachmentRow]:
        return fixed

    monkeypatch.setattr(runner_mod, "get_run_attachments", _fake_get_run_attachments)
    return fixed


def _wire_fake_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> _FakeEventWriter:
    captured: dict[str, _FakeEventWriter] = {}

    def make_writer(database_url: str) -> _FakeEventWriter:
        # Return the same writer for every construction so tests can assert
        # against a single events list even when the failure path constructs a
        # second writer from raw env.
        if "writer" not in captured:
            captured["writer"] = _FakeEventWriter(database_url)
        return captured["writer"]

    monkeypatch.setattr(runner_mod, "EventWriter", make_writer)
    # Pre-create on first call by triggering construction explicitly so the
    # caller can grab it; lazy creation via make_writer also works.
    return captured.setdefault("writer", _FakeEventWriter(""))


@pytest.mark.asyncio
async def test_execute_run_uses_persisted_task_kind_not_prompt_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)
    _wire_fake_runner(monkeypatch)

    async def fake_get_run_context(
        _database_url: str,
        *,
        run_id: str,
        thread_id: str,
        workspace_id: str,
    ) -> AgentRunContext:
        # Prompt heuristic would route this to "branch_design" because of
        # "generate" + "bind" + "3cl"; the persisted task_kind is different.
        return AgentRunContext(
            prompt="Generate a protein that binds to 3CL-protease.",
            model=None,
            task_kind="prepare_structure",
            enabled_recipes=[],
        )

    async def fake_claim_run(_database_url: str, *, run_id: str) -> bool:
        return True

    completed_calls: list[str] = []

    async def fake_mark_completed(_database_url: str, run_id: str) -> None:
        completed_calls.append(run_id)

    async def fake_mark_failed(
        _database_url: str,
        run_id: str,
        error_summary: str,
    ) -> None:
        raise AssertionError("mark_run_failed should not be called on happy path")

    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(runner_mod, "mark_run_failed", fake_mark_failed)
    _stub_get_run_attachments(monkeypatch)

    spy_choose_task_kind = MagicMock(side_effect=lambda prompt: "branch_design")
    monkeypatch.setattr(runner_mod, "choose_task_kind", spy_choose_task_kind)

    await execute_run(run_id="r1", thread_id="t1", workspace_id="w1")

    started = next(e for e in writer.events if e["type"] == "run_started")
    assert started["display"] == {"taskKind": "prepare_structure"}
    assert "prepare_structure" in (started["summary"] or "")
    spy_choose_task_kind.assert_not_called()
    assert completed_calls == ["r1"]


@pytest.mark.asyncio
async def test_execute_run_bails_out_when_claim_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)
    runner_double, _streamed = _wire_fake_runner(monkeypatch)

    claim_calls: list[str] = []

    async def fake_claim_run(_database_url: str, *, run_id: str) -> bool:
        claim_calls.append(run_id)
        return False  # already claimed by an earlier Modal invocation

    async def must_not_be_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("must not run after a failed claim")

    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "get_run_context", must_not_be_called)
    monkeypatch.setattr(runner_mod, "mark_run_completed", must_not_be_called)
    monkeypatch.setattr(runner_mod, "mark_run_failed", must_not_be_called)

    await execute_run(run_id="r2", thread_id="t1", workspace_id="w1")

    assert claim_calls == ["r2"]
    assert writer.events == []
    runner_double.run_streamed.assert_not_called()


@pytest.mark.asyncio
async def test_execute_run_records_failure_when_config_loading_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DATABASE_URL is set in env, but we simulate a config-loading failure
    # (e.g. some other env var missing). The run should still be marked failed
    # using the raw DATABASE_URL fallback so it does not stay queued forever.
    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)

    def explode_from_env() -> Any:
        raise RuntimeError("Missing required environment variables: SOMETHING")

    monkeypatch.setattr(
        runner_mod.WorkerConfig,
        "from_env",
        classmethod(lambda cls: explode_from_env()),
    )

    failed_calls: list[tuple[str, str, str]] = []

    async def fake_mark_failed(
        database_url: str,
        run_id: str,
        error_summary: str,
    ) -> None:
        failed_calls.append((database_url, run_id, error_summary))

    async def fake_mark_completed(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("must not mark completed when config failed")

    async def fake_claim_run(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("must not claim when config failed")

    monkeypatch.setattr(runner_mod, "mark_run_failed", fake_mark_failed)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)

    with pytest.raises(RuntimeError, match="Missing required environment variables"):
        await execute_run(run_id="r3", thread_id="t1", workspace_id="w1")

    assert len(failed_calls) == 1
    db_url, run_id, summary = failed_calls[0]
    assert db_url == REQUIRED_RUNTIME_ENV["DATABASE_URL"]
    assert run_id == "r3"
    assert "Missing required environment variables" in summary
    failure_event = next(
        (event for event in writer.events if event["type"] == "run_failed"),
        None,
    )
    assert failure_event is not None
    assert "Missing required environment variables" in (failure_event["summary"] or "")


@pytest.mark.asyncio
async def test_sandbox_stdout_deltas_are_coalesced_into_completion() -> None:
    """The runner must NOT persist per-chunk sandbox_*_delta events.

    Drives a fake event stream through the runner's stream-handling helper
    and asserts that a `started`, three deltas, and a `completed` event
    collapse into exactly two ledger rows whose `display.stdout|stderr`
    contains the merged output.
    """
    writer = _FakeEventWriter("test-db")
    streamed = _FakeStreamedRun(
        [
            SimpleNamespace(
                type="sandbox_command_started",
                command_id="cmd-1",
                display={"command": "echo hi"},
            ),
            SimpleNamespace(
                type="sandbox_stdout_delta",
                command_id="cmd-1",
                delta="hello ",
            ),
            SimpleNamespace(
                type="sandbox_stdout_delta",
                command_id="cmd-1",
                delta="world",
            ),
            SimpleNamespace(
                type="sandbox_stderr_delta",
                command_id="cmd-1",
                delta="oops\n",
            ),
            SimpleNamespace(
                type="sandbox_command_completed",
                command_id="cmd-1",
                display={"exitCode": 0},
            ),
        ],
    )

    await runner_mod._append_normalized_stream_events(
        streamed,
        run_id="r-sandbox",
        writer=writer,
    )

    types = [event["type"] for event in writer.events]
    assert types == ["sandbox_command_started", "sandbox_command_completed"]
    completed = writer.events[1]
    assert completed["display"]["stdout"] == "hello world"
    assert completed["display"]["stderr"] == "oops\n"
    assert completed["display"]["stdoutTruncated"] is False
    assert completed["display"]["stderrTruncated"] is False
    assert completed["display"]["commandId"] == "cmd-1"
    assert completed["display"]["exitCode"] == 0


@pytest.mark.asyncio
async def test_sandbox_stdout_truncates_at_10kb_with_truncation_flag() -> None:
    writer = _FakeEventWriter("test-db")
    huge = "x" * 25_000  # ~25KB, well past the 10KB cap
    streamed = _FakeStreamedRun(
        [
            SimpleNamespace(
                type="sandbox_command_started",
                command_id="cmd-big",
                display={"command": "yes"},
            ),
            SimpleNamespace(
                type="sandbox_stdout_delta",
                command_id="cmd-big",
                delta=huge,
            ),
            SimpleNamespace(
                type="sandbox_command_completed",
                command_id="cmd-big",
                display={"exitCode": 0},
            ),
        ],
    )

    await runner_mod._append_normalized_stream_events(
        streamed,
        run_id="r-trunc",
        writer=writer,
    )

    completed = writer.events[-1]
    assert completed["type"] == "sandbox_command_completed"
    assert completed["display"]["stdoutTruncated"] is True
    assert len(completed["display"]["stdout"]) == 10_000
    assert completed["display"]["stdout"].endswith("…")


@pytest.mark.asyncio
async def test_response_completed_flushes_accumulated_assistant_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`response.completed` must flush the accumulated text via the webhook."""
    writer = _FakeEventWriter("test-db")
    streamed = _FakeStreamedRun(
        [
            {
                "type": "raw_response_event",
                "data": {"type": "response.output_text.delta", "delta": "Hel"},
            },
            {
                "type": "raw_response_event",
                "data": {"type": "response.output_text.delta", "delta": "lo!"},
            },
            {
                "type": "raw_response_event",
                "data": {"type": "response.completed"},
            },
        ],
    )

    flush_calls: list[tuple[str, str]] = []

    def fake_flush(run_id: str, thread_id: str) -> None:
        # Capture the buffered text BEFORE the runner pops it.
        captured = "".join(runner_mod.ASSISTANT_TEXT_BUFFERS.get(run_id, []))
        flush_calls.append((run_id, thread_id))
        # Drain the buffer so module state stays clean between tests.
        runner_mod.ASSISTANT_TEXT_BUFFERS.pop(run_id, None)
        assert captured == "Hello!"

    monkeypatch.setattr(runner_mod, "_flush_assistant_message", fake_flush)

    await runner_mod._append_normalized_stream_events(
        streamed,
        run_id="r-flush",
        writer=writer,
        thread_id="t-flush",
    )

    assert flush_calls == [("r-flush", "t-flush")]
    # Buffer should have been cleared.
    assert "r-flush" not in runner_mod.ASSISTANT_TEXT_BUFFERS


@pytest.mark.asyncio
async def test_flush_assistant_message_skips_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No webhook POST when AUTOPEP_NEXT_PUBLIC_URL or secret is missing."""
    runner_mod.ASSISTANT_TEXT_BUFFERS["r-noenv"] = ["partial"]
    monkeypatch.delenv("AUTOPEP_NEXT_PUBLIC_URL", raising=False)
    monkeypatch.delenv("AUTOPEP_MODAL_WEBHOOK_SECRET", raising=False)

    calls: list[Any] = []

    def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        raise AssertionError("urlopen must not be called when env is unset")

    monkeypatch.setattr(runner_mod.urllib.request, "urlopen", fake_urlopen)
    runner_mod._flush_assistant_message("r-noenv", "t-noenv")
    assert calls == []
    # The buffer should still be cleared.
    assert "r-noenv" not in runner_mod.ASSISTANT_TEXT_BUFFERS


@pytest.mark.asyncio
async def test_flush_assistant_message_swallows_webhook_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Webhook failures must not propagate and break the run."""
    import urllib.error as urllib_error

    runner_mod.ASSISTANT_TEXT_BUFFERS["r-err"] = ["text"]
    monkeypatch.setenv("AUTOPEP_NEXT_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("AUTOPEP_MODAL_WEBHOOK_SECRET", "secret")

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr(runner_mod.urllib.request, "urlopen", fake_urlopen)
    # Should not raise.
    runner_mod._flush_assistant_message("r-err", "t-err")


@pytest.mark.asyncio
async def test_attachments_are_downloaded_and_announced_to_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Attachment artifacts referenced by the run are mounted into ``inputs/``.

    The test drives ``execute_run`` end-to-end with stubbed DB / Runner /
    R2 download, then asserts:

      * ``inputs/`` under the redirected workspace volume contains the
        downloaded attachment file
      * the ``input`` string passed to ``Runner.run_streamed`` includes the
        sanitized on-volume path so the agent learns about the attachment
    """

    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)

    # Redirect the volume mount to the test tmp dir so we don't try to
    # write under the real "/autopep-workspaces" path on developer laptops.
    monkeypatch.setattr(runner_mod, "WORKSPACE_DIR", str(tmp_path))

    runner_double, _streamed = _wire_fake_runner(monkeypatch)

    async def fake_get_run_context(*_args: Any, **_kwargs: Any) -> AgentRunContext:
        return AgentRunContext(
            prompt="Use the attached spec.",
            model=None,
            task_kind="chat",
            enabled_recipes=[],
        )

    async def fake_claim_run(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def fake_mark_completed(_url: str, _run_id: str) -> None:
        return None

    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(
        runner_mod,
        "mark_run_failed",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not mark failed on happy path"),
        ),
    )

    _stub_get_run_attachments(
        monkeypatch,
        rows=[
            AttachmentRow(
                artifact_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                storage_key="workspaces/w-attach/uploads/notes.txt",
                # Names with weird chars must be sanitized before landing on disk.
                name="notes/../weird name.txt",
            ),
        ],
    )

    download_calls: list[dict[str, Any]] = []

    async def fake_download_object(
        *,
        bucket: str,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        key: str,
        dest_path: Any,
    ) -> None:
        download_calls.append(
            {
                "bucket": bucket,
                "account_id": account_id,
                "key": key,
                "dest_path": str(dest_path),
            },
        )
        # Simulate boto3 writing the bytes into the destination path.
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"hello attachment")

    monkeypatch.setattr(runner_mod, "r2_download_object", fake_download_object)

    await execute_run(run_id="r-attach", thread_id="t-attach", workspace_id="w-attach")

    # 1. The R2 download was invoked once with the attachment's storage key.
    assert len(download_calls) == 1
    assert download_calls[0]["key"] == "workspaces/w-attach/uploads/notes.txt"

    # 2. The file landed under {workspace_dir}/{workspace_id}/inputs/ with
    #    a sanitized basename (no ".." traversal, no spaces, no slashes).
    inputs_dir = tmp_path / "w-attach" / "inputs"
    listing = sorted(p.name for p in inputs_dir.iterdir())
    assert listing == ["weird_name.txt"]
    assert (inputs_dir / "weird_name.txt").read_bytes() == b"hello attachment"

    # 3. The system-style hint was prepended to the agent input so the model
    #    sees the on-volume path before it processes the user prompt.
    runner_double.run_streamed.assert_called_once()
    _agent_arg, *_ = runner_double.run_streamed.call_args.args
    agent_input = runner_double.run_streamed.call_args.kwargs["input"]
    expected_path = str(inputs_dir / "weird_name.txt")
    assert "Attached files available at:" in agent_input
    assert expected_path in agent_input
    # The prompt must still appear AFTER the attachment announcement so the
    # model encounters the file paths first.
    assert agent_input.index("Attached files available at:") < agent_input.index(
        "Use the attached spec.",
    )

    # 4. The runner emitted an ``attachments_mounted`` event for the ledger
    #    so operators can see in the trace which paths the agent received.
    mounted = next(
        (event for event in writer.events if event["type"] == "attachments_mounted"),
        None,
    )
    assert mounted is not None
    assert expected_path in (mounted["display"] or {}).get("paths", [])


@pytest.mark.asyncio
async def test_execute_run_happy_path_writes_normalized_events_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    writer = _wire_fake_writer(monkeypatch)

    # Stream events: one raw token delta, one completed tool call.
    streamed = _FakeStreamedRun(
        [
            {
                "type": "raw_response_event",
                "data": {"type": "response.output_text.delta", "delta": "hi"},
            },
            {
                "type": "run_item_stream_event",
                "name": "tool_output",
                "item": {"raw_item": {"name": "search_structures"}},
            },
        ],
    )
    _wire_fake_runner(monkeypatch, streamed=streamed)

    async def fake_get_run_context(*_args: Any, **_kwargs: Any) -> AgentRunContext:
        return AgentRunContext(
            prompt="hi",
            model="gpt-5.5",
            task_kind="chat",
            enabled_recipes=[],
        )

    async def fake_claim_run(*_args: Any, **_kwargs: Any) -> bool:
        return True

    completed: list[str] = []

    async def fake_mark_completed(_url: str, run_id: str) -> None:
        completed.append(run_id)

    monkeypatch.setattr(runner_mod, "get_run_context", fake_get_run_context)
    monkeypatch.setattr(runner_mod, "claim_run", fake_claim_run)
    monkeypatch.setattr(runner_mod, "mark_run_completed", fake_mark_completed)
    monkeypatch.setattr(
        runner_mod,
        "mark_run_failed",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not mark failed on happy path"),
        ),
    )
    _stub_get_run_attachments(monkeypatch)

    await execute_run(run_id="r4", thread_id="t1", workspace_id="w1")

    types = [event["type"] for event in writer.events]
    assert types[0] == "run_started"
    # Token deltas are no longer persisted to the agent_events ledger; they
    # are streamed directly via Modal SSE in Task 2.5.
    assert "assistant_token_delta" not in types
    assert "tool_call_completed" in types
    assert types[-1] == "run_completed"
    assert completed == ["r4"]
