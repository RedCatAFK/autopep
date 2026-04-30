from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from julia_agent import db
from julia_agent.config import WorkerConfig
from julia_agent.live_runner import run_live_turn


def _make_config() -> WorkerConfig:
    return WorkerConfig(
        database_url="postgres://example",
        webhook_secret=None,
        dry_run=False,
        r2_bucket=None,
        r2_endpoint_url=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_region="auto",
        r2_public_base_url=None,
    )


class _FakeStream:
    def __init__(self, events: list[Any]):
        self._events = events

    async def stream_events(self):
        for event in self._events:
            yield event


def _build_stream_events(workspace_dir: Path) -> list[Any]:
    target_path = workspace_dir / "outputs" / "pdb" / "1ABC.cif"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("data_target\n", encoding="utf-8")

    text_delta = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="Hello "),
    )
    text_delta_two = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="world"),
    )
    tool_call = SimpleNamespace(
        type="run_item_stream_event",
        item=SimpleNamespace(
            type="tool_call_item",
            raw_item=SimpleNamespace(
                name="fetch_pdb",
                call_id="call_1",
                arguments='{"pdb_id":"1ABC","file_format":"cif"}',
            ),
        ),
    )
    tool_output = SimpleNamespace(
        type="run_item_stream_event",
        item=SimpleNamespace(
            type="tool_call_output_item",
            raw_item=SimpleNamespace(call_id="call_1", name="fetch_pdb"),
            output={"sandbox_path": "outputs/pdb/1ABC.cif"},
        ),
    )
    return [text_delta, text_delta_two, tool_call, tool_output]


@pytest.mark.asyncio
async def test_live_runner_streams_events_and_uploads_artifacts(monkeypatch, tmp_path):
    pytest.importorskip("pytest_asyncio")
    events: list[tuple] = []
    artifact_inserts: list[tuple] = []
    deltas: list[str] = []
    statuses: list[str] = []
    captured_workspace: dict[str, Path] = {}

    monkeypatch.setattr(
        db,
        "mark_run_status",
        lambda database_url, run_id, status: statuses.append(status),
    )
    monkeypatch.setattr(
        db,
        "insert_run_event",
        lambda database_url, run_id, event_type, message, sequence, metadata: events.append(
            (sequence, event_type, message, dict(metadata))
        ),
    )
    monkeypatch.setattr(
        db,
        "append_assistant_delta",
        lambda database_url, message_id, delta: deltas.append(delta),
    )
    monkeypatch.setattr(
        db,
        "insert_artifact",
        lambda *args, **kwargs: artifact_inserts.append((args, kwargs)),
    )

    def fake_build_agent(workspace, *, model=None):
        captured_workspace["path"] = Path(workspace)
        return SimpleNamespace(name="Julia")

    monkeypatch.setattr(
        "julia_agent.live_runner.build_julia_agent_with_tools", fake_build_agent
    )

    class FakeRunner:
        @staticmethod
        def run_streamed(agent, prompt, **_):
            workspace = captured_workspace["path"]
            return _FakeStream(_build_stream_events(workspace))

    fake_agents_module = SimpleNamespace(Runner=FakeRunner)
    monkeypatch.setitem(__import__("sys").modules, "agents", fake_agents_module)

    result = await run_live_turn(
        config=_make_config(),
        database_url="postgres://example",
        run_id="00000000-0000-0000-0000-000000000001",
        project_id="00000000-0000-0000-0000-0000000000aa",
        assistant_message_id="00000000-0000-0000-0000-0000000000bb",
        prompt="hello",
    )

    assert result == {
        "runId": "00000000-0000-0000-0000-000000000001",
        "status": "completed",
    }
    assert statuses == ["running", "completed"]
    assert deltas == ["Hello ", "world"]

    types_in_order = [event[1] for event in events]
    assert types_in_order[0] == "run_status"
    assert types_in_order[-1] == "run_status"
    assert "text_delta" in types_in_order
    assert "tool_call_started" in types_in_order
    assert "tool_call_completed" in types_in_order
    assert "artifact_created" in types_in_order

    sequences = [event[0] for event in events]
    assert sequences == sorted(sequences) and len(sequences) == len(set(sequences))

    artifact_event = next(event for event in events if event[1] == "artifact_created")
    artifact_metadata = artifact_event[3]
    assert artifact_metadata["filename"] == "1ABC.cif"
    assert artifact_metadata["source"] == "tool_result"
    assert artifact_metadata["r2Key"].startswith(
        "workspaces/00000000-0000-0000-0000-0000000000aa/runs/"
    )

    assert len(artifact_inserts) == 1


@pytest.mark.asyncio
async def test_live_runner_records_run_error_on_exception(monkeypatch, tmp_path):
    pytest.importorskip("pytest_asyncio")
    events: list[tuple] = []
    statuses: list[str] = []

    monkeypatch.setattr(
        db,
        "mark_run_status",
        lambda database_url, run_id, status: statuses.append(status),
    )
    monkeypatch.setattr(
        db,
        "insert_run_event",
        lambda database_url, run_id, event_type, message, sequence, metadata: events.append(
            (sequence, event_type, message)
        ),
    )
    monkeypatch.setattr(db, "append_assistant_delta", lambda *args, **kwargs: None)
    monkeypatch.setattr(db, "insert_artifact", lambda *args, **kwargs: None)

    monkeypatch.setattr(
        "julia_agent.live_runner.build_julia_agent_with_tools",
        lambda workspace, *, model=None: SimpleNamespace(name="Julia"),
    )

    class FailingRunner:
        @staticmethod
        def run_streamed(agent, prompt, **_):
            raise RuntimeError("boom")

    fake_agents_module = SimpleNamespace(Runner=FailingRunner)
    monkeypatch.setitem(__import__("sys").modules, "agents", fake_agents_module)

    with pytest.raises(RuntimeError, match="boom"):
        await run_live_turn(
            config=_make_config(),
            database_url="postgres://example",
            run_id="00000000-0000-0000-0000-000000000002",
            project_id="00000000-0000-0000-0000-0000000000cc",
            assistant_message_id="00000000-0000-0000-0000-0000000000dd",
            prompt="trigger failure",
        )

    assert statuses == ["running", "failed"]
    assert any(event[1] == "run_error" for event in events)
