from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import Request
import modal


APP_NAME = "autopep-sandbox-worker"
APP_DIR = "/app"
WORKSPACE_DIR = "/autopep-workspaces"
WORKSPACE_VOLUME_NAME = "autopep-workspaces"
RUNTIME_SECRET_NAME = "autopep-runtime"
WEBHOOK_SECRET_NAME = "autopep-webhook"
AGENT_TIMEOUT_SECONDS = 60 * 60
START_RUN_TIMEOUT_SECONDS = 120
RUN_STREAM_TIMEOUT_SECONDS = AGENT_TIMEOUT_SECONDS
REPO_ROOT = Path(__file__).resolve().parents[1]

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

app = modal.App(APP_NAME)
workspace_volume = modal.Volume.from_name(
    WORKSPACE_VOLUME_NAME,
    create_if_missing=True,
)
runtime_secret = modal.Secret.from_name(RUNTIME_SECRET_NAME)
webhook_secret = modal.Secret.from_name(WEBHOOK_SECRET_NAME)
control_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi[standard]",
)

worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("modal/requirements.txt")
    .add_local_dir(
        str(REPO_ROOT / "modal" / "autopep_agent"),
        remote_path=f"{APP_DIR}/autopep_agent",
        copy=True,
    )
    .workdir(APP_DIR)
)


def _http_error(status_code: int, detail: str) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail=detail)


def _require_bearer(request: Any) -> None:
    expected = os.environ.get("AUTOPEP_MODAL_WEBHOOK_SECRET")
    provided = request.headers.get("authorization", "")

    if not expected:
        raise _http_error(
            status_code=500,
            detail="Modal webhook secret is not configured.",
        )

    if provided != f"Bearer {expected}":
        raise _http_error(status_code=401, detail="Unauthorized.")


def _require_uuid(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise _http_error(status_code=422, detail=f"{key} must be a UUID.")
    return value


@app.function(
    image=worker_image,
    secrets=[runtime_secret],
    timeout=AGENT_TIMEOUT_SECONDS,
    volumes={WORKSPACE_DIR: workspace_volume},
    cpu=1,
    memory=2048,
)
def run_autopep_agent(workspace_id: str, thread_id: str, run_id: str) -> None:
    import asyncio

    from autopep_agent.runner import execute_run

    asyncio.run(
        execute_run(
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
        )
    )


@app.function(
    image=control_image,
    secrets=[webhook_secret],
    timeout=START_RUN_TIMEOUT_SECONDS,
)
@modal.fastapi_endpoint(method="POST", docs=False, label="start-run")
async def start_run(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    _require_bearer(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise _http_error(status_code=400, detail="Invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise _http_error(status_code=422, detail="Expected a JSON object.")

    workspace_id = _require_uuid(payload, "workspaceId")
    thread_id = _require_uuid(payload, "threadId")
    run_id = _require_uuid(payload, "runId")

    function_call = run_autopep_agent.spawn(
        workspace_id=workspace_id,
        thread_id=thread_id,
        run_id=run_id,
    )
    return JSONResponse(
        content={
            "accepted": True,
            "functionCallId": function_call.object_id,
        },
        status_code=202,
    )


@app.function(
    image=control_image,
    secrets=[webhook_secret],
    timeout=RUN_STREAM_TIMEOUT_SECONDS,
)
@modal.fastapi_endpoint(method="GET", docs=False, label="run-stream")
async def run_stream(request: Request) -> Any:
    """Tail a per-run Modal Queue and forward token deltas as SSE.

    Auth here is a temporary shared-secret check against
    AUTOPEP_MODAL_WEBHOOK_SECRET. Task 2.6 will replace this with a signed
    JWT minted by the Next.js server. Until then, callers pass the secret
    via the `token` query parameter (EventSource cannot set Authorization
    headers).
    """
    import json
    import queue as _queue

    from fastapi.responses import StreamingResponse

    run_id = request.query_params.get("runId", "")
    token = request.query_params.get("token", "")
    if not run_id or not token:
        raise _http_error(status_code=400, detail="runId and token are required.")

    expected = os.environ.get("AUTOPEP_MODAL_WEBHOOK_SECRET", "")
    if not expected or token != expected:
        raise _http_error(status_code=401, detail="Unauthorized.")

    if not UUID_RE.match(run_id):
        raise _http_error(status_code=422, detail="runId must be a UUID.")

    token_queue = modal.Queue.from_name(
        f"autopep-tokens-{run_id}",
        create_if_missing=True,
    )

    async def gen():
        # Initial keep-alive so the client confirms the connection is live.
        yield ": connected\n\n"
        while True:
            try:
                msg = await token_queue.get.aio(timeout=15)
            except (_queue.Empty, TimeoutError):
                # No tokens within the polling window: emit a heartbeat to
                # keep proxies / EventSource readers from timing out.
                yield ": keep-alive\n\n"
                continue
            except Exception:
                # Any other transport-level hiccup: heartbeat and retry.
                yield ": keep-alive\n\n"
                continue

            if msg is None:
                yield ": keep-alive\n\n"
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            if msg_type == "done":
                yield "event: done\ndata: {}\n\n"
                return
            if msg_type == "delta":
                payload = json.dumps({"text": msg.get("text", "")})
                yield f"event: delta\ndata: {payload}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
