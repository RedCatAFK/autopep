from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from julia_agent import db
from julia_agent.config import WorkerConfig
from julia_agent.events import normalize_run_status, normalize_text_delta

app = FastAPI(title="Julia Worker")


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

    payload = await request.json()
    run_id = payload.get("runId") or payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise HTTPException(status_code=400, detail="runId is required")

    if config.dry_run or payload.get("dryRun") is True:
        if not config.database_url:
            raise HTTPException(status_code=503, detail="DATABASE_URL is required for dry run")
        return run_dry_run(config.database_url, run_id)

    raise HTTPException(status_code=501, detail="Live Julia worker run is not implemented")


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def run_dry_run(database_url: str, run_id: str) -> dict[str, Any]:
    db.load_run_context(database_url, run_id)
    db.mark_run_status(database_url, run_id, "running")

    started = normalize_run_status(run_id, "running")
    db.insert_run_event(database_url, run_id, started["type"], started["payload"])

    delta = "Dry run completed."
    text_delta = normalize_text_delta(run_id, delta)
    db.append_assistant_delta(database_url, run_id, delta)
    db.insert_run_event(database_url, run_id, text_delta["type"], text_delta["payload"])

    completed = normalize_run_status(run_id, "completed")
    db.insert_run_event(database_url, run_id, completed["type"], completed["payload"])
    db.mark_run_status(database_url, run_id, "completed")

    return {"runId": run_id, "status": "completed", "dryRun": True}
