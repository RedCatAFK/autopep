from julia_agent import db
from julia_agent.main import WorkerStartPayload, run_dry_run


def test_dry_run_writes_ordered_events_message_and_artifact(monkeypatch) -> None:
    calls: list[tuple] = []

    monkeypatch.setattr(
        db,
        "load_run_context",
        lambda database_url, run_id: {
            "id": run_id,
            "project_id": "project_1",
            "metadata": {"assistantMessageId": "message_1"},
        },
    )
    monkeypatch.setattr(
        db,
        "mark_run_status",
        lambda database_url, run_id, status: calls.append(("status", status)),
    )
    monkeypatch.setattr(
        db,
        "insert_run_event",
        lambda database_url, run_id, event_type, message, sequence, metadata: calls.append(
            ("event", sequence, event_type, message, metadata)
        ),
    )
    monkeypatch.setattr(
        db,
        "append_assistant_delta",
        lambda database_url, assistant_message_id, delta: calls.append(
            ("assistant", assistant_message_id, delta)
        ),
    )
    monkeypatch.setattr(
        db,
        "insert_artifact",
        lambda database_url, project_id, run_id, kind, filename, r2_key, content_type, size_bytes, metadata: calls.append(
            (
                "artifact",
                project_id,
                run_id,
                kind,
                filename,
                r2_key,
                content_type,
                size_bytes,
                metadata,
            )
        ),
    )

    payload = WorkerStartPayload(
        runId="run_1",
        projectId="project_1",
        threadId="thread_1",
        assistantMessageId="message_1",
        dryRun=True,
    )

    result = run_dry_run("postgres://example", payload)

    assert result == {"runId": "run_1", "status": "completed", "dryRun": True}
    assert calls[0] == ("status", "running")
    assert calls[-1] == ("status", "completed")
    assert [call[1] for call in calls if call[0] == "event"] == [2, 3, 4, 5, 6]
    assert ("assistant", "message_1", "Dry run completed.") in calls
    artifact_call = next(call for call in calls if call[0] == "artifact")
    assert artifact_call[1:6] == (
        "project_1",
        "run_1",
        "json",
        "julia-dry-run-summary.json",
        "dry-run/run_1/julia-dry-run-summary.json",
    )
    assert artifact_call[-1]["dryRun"] is True
    assert artifact_call[-1]["source"] == "tool_result"
