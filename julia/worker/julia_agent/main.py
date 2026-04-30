from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from julia_agent.agent import run_julia_agent
from julia_agent import db
from julia_agent.config import WorkerConfig
from julia_agent.events import normalize_run_error, normalize_run_status, normalize_text_delta

app = FastAPI(title="Julia Worker")


class WorkerStartPayload(BaseModel):
    run_id: str = Field(alias="runId")
    project_id: str = Field(alias="projectId")
    thread_id: str = Field(alias="threadId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    content: str | None = None
    context_reference_ids: list[str] = Field(default_factory=list, alias="contextReferenceIds")
    dry_run: bool = Field(default=False, alias="dryRun")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs/start")
async def start_run(
    request: Request, x_julia_signature: str | None = Header(default=None)
) -> dict[str, Any]:
    body = await request.body()
    config = WorkerConfig.from_env()
    if not verify_signature(body, x_julia_signature, config.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Julia worker signature")

    payload = WorkerStartPayload.model_validate(await request.json())

    if config.dry_run or payload.dry_run:
        if not config.database_url:
            raise HTTPException(status_code=503, detail="DATABASE_URL is required for dry run")
        return run_dry_run(config.database_url, payload)

    if os.getenv("JULIA_WORKER_ALLOW_LIVE_RUNS") != "1":
        raise HTTPException(
            status_code=501,
            detail=(
                "Live Julia worker runs are disabled. Set "
                "JULIA_WORKER_ALLOW_LIVE_RUNS=1 to enable the SandboxAgent runner."
            ),
        )
    if not config.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is required for live run")
    return await run_live_run(config.database_url, payload)


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def run_dry_run(database_url: str, payload: WorkerStartPayload) -> dict[str, Any]:
    run_context = db.load_run_context(database_url, payload.run_id) or {}
    project_id = _string_or_default(run_context.get("project_id"), payload.project_id)
    assistant_message_id = _string_or_default(
        _metadata_value(run_context, "assistantMessageId"),
        payload.assistant_message_id,
    )

    db.mark_run_status(database_url, payload.run_id, "running")
    try:
        _insert_event(
            database_url,
            payload.run_id,
            2,
            normalize_run_status(payload.run_id, "running"),
        )

        tool_started = {
            "runId": payload.run_id,
            "type": "tool_call_started",
            "payload": {"name": "dry_run_artifact", "input": {"dryRun": True}},
        }
        _insert_event(
            database_url, payload.run_id, 3, tool_started, "dry_run_artifact started"
        )

        delta = "Dry run completed."
        text_delta = normalize_text_delta(payload.run_id, delta)
        db.append_assistant_delta(database_url, assistant_message_id, delta)
        _insert_event(database_url, payload.run_id, 4, text_delta, delta)

        artifact_filename = "julia-dry-run-summary.json"
        artifact_key = f"dry-run/{payload.run_id}/{artifact_filename}"
        artifact_metadata = {
            "dryRun": True,
            "source": "tool_result",
            "threadId": payload.thread_id,
            "assistantMessageId": assistant_message_id,
            "r2Skipped": True,
        }
        db.insert_artifact(
            database_url,
            project_id,
            payload.run_id,
            "json",
            artifact_filename,
            artifact_key,
            "application/json",
            None,
            artifact_metadata,
        )
        tool_completed = {
            "runId": payload.run_id,
            "type": "tool_call_completed",
            "payload": {
                "name": "dry_run_artifact",
                "result": {
                    "filename": artifact_filename,
                    "r2Key": artifact_key,
                    "dryRun": True,
                },
                "artifacts": [
                    {
                        "filename": artifact_filename,
                        "r2Key": artifact_key,
                        "source": "tool_result",
                        "dryRun": True,
                    }
                ],
            },
        }
        _insert_event(
            database_url,
            payload.run_id,
            5,
            tool_completed,
            "dry_run_artifact completed",
        )

        completed = normalize_run_status(payload.run_id, "completed")
        _insert_event(database_url, payload.run_id, 6, completed, "completed")
        db.mark_run_status(database_url, payload.run_id, "completed")
    except Exception as error:
        _insert_event(
            database_url,
            payload.run_id,
            99,
            normalize_run_error(payload.run_id, error),
            str(error),
        )
        db.mark_run_status(database_url, payload.run_id, "failed")
        raise

    return {"runId": payload.run_id, "status": "completed", "dryRun": True}


async def run_live_run(database_url: str, payload: WorkerStartPayload) -> dict[str, Any]:
    run_context = db.load_run_context(database_url, payload.run_id) or {}
    assistant_message_id = _string_or_default(
        _metadata_value(run_context, "assistantMessageId"),
        payload.assistant_message_id,
    )
    prompt = payload.content or ""
    context = {
        "runId": payload.run_id,
        "projectId": payload.project_id,
        "threadId": payload.thread_id,
        "assistantMessageId": assistant_message_id,
        "contextReferenceIds": payload.context_reference_ids,
        "run": run_context,
    }

    db.mark_run_status(database_url, payload.run_id, "running")
    try:
        _insert_event(
            database_url,
            payload.run_id,
            2,
            normalize_run_status(payload.run_id, "running"),
        )
        output = await run_julia_agent(prompt, context=context)
        if output:
            db.append_assistant_delta(database_url, assistant_message_id, output)
            _insert_event(
                database_url,
                payload.run_id,
                3,
                normalize_text_delta(payload.run_id, output),
                output,
            )

        completed = normalize_run_status(payload.run_id, "completed")
        _insert_event(database_url, payload.run_id, 4, completed, "completed")
        db.mark_run_status(database_url, payload.run_id, "completed")
    except Exception as error:
        _insert_event(
            database_url,
            payload.run_id,
            99,
            normalize_run_error(payload.run_id, error),
            str(error),
        )
        db.mark_run_status(database_url, payload.run_id, "failed")
        raise

    return {"runId": payload.run_id, "status": "completed", "dryRun": False}


def _insert_event(
    database_url: str,
    run_id: str,
    sequence: int,
    event: dict[str, Any],
    message: str | None = None,
) -> None:
    metadata = dict(event["payload"])
    if event["type"] == "text_delta":
        text = metadata.get("text")
        if isinstance(text, str):
            metadata["delta"] = text
    db.insert_run_event(database_url, run_id, event["type"], message, sequence, metadata)


def _metadata_value(run_context: dict[str, Any], key: str) -> Any:
    metadata = run_context.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default
