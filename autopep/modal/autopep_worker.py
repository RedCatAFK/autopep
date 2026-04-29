from __future__ import annotations

import os
import re
import shlex
import subprocess
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
SANDBOX_TIMEOUT_SECONDS = 60 * 60
SANDBOX_IDLE_TIMEOUT_SECONDS = 5 * 60
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

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "bash",
        "ca-certificates",
        "curl",
        "git",
        "nodejs",
        "npm",
        "unzip",
    )
    .pip_install("fastapi[standard]", "requests")
    .run_commands(
        "curl -fsSL https://bun.sh/install | bash",
        "ln -sf /root/.bun/bin/bun /usr/local/bin/bun",
        "bun install -g @openai/codex",
        "ln -sf /root/.bun/bin/codex /usr/local/bin/codex",
        "git clone --depth=1 https://github.com/openai/plugins.git /tmp/openai-plugins",
        "mkdir -p /opt/life-science-research",
        "cp -R /tmp/openai-plugins/plugins/life-science-research/. /opt/life-science-research/",
        "mkdir -p /root/.codex/plugins/cache/openai-curated/life-science-research/6807e4de",
        "cp -R /opt/life-science-research/. /root/.codex/plugins/cache/openai-curated/life-science-research/6807e4de/",
        "rm -rf /tmp/openai-plugins",
    )
    .add_local_dir(
        REPO_ROOT,
        remote_path=APP_DIR,
        copy=True,
        ignore=[
            ".env",
            ".env.*",
            ".git",
            ".next",
            ".turbo",
            ".worktrees",
            "node_modules",
        ],
    )
    .workdir(APP_DIR)
    .run_commands("bun install --frozen-lockfile")
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


def _sandbox_command(run_id: str, project_id: str) -> str:
    codex_prompt = (
        "You are the Autopep target-structure retrieval worker. "
        "Read AUTOPEP_HARNESS_INPUT for projectId, runId, prompt, and topK. "
        "Use the life-science-research plugin mounted at /opt/life-science-research, "
        "with the same plugin mirrored under /root/.codex/plugins/cache/openai-curated/life-science-research/6807e4de. "
        "search RCSB/PubMed literature as needed, select top relevant structures, "
        "persist progress/candidates/artifacts to Neon, upload CIF artifacts to R2, "
        "and finish only when at least one CIF artifact is ready for downstream Proteina use."
    )
    default_codex_command = (
        'mkdir -p /root/.codex && '
        'if [ -n "${OPENAI_API_KEY:-}" ]; then '
        'printenv OPENAI_API_KEY | codex login --with-api-key >/tmp/codex-login.log 2>&1 || '
        '{ sed -E "s/(sk-[A-Za-z0-9_-]+)/<redacted>/g" /tmp/codex-login.log >&2; exit 1; }; '
        "fi && "
        'codex exec -c preferred_auth_method=\\"apikey\\" '
        '--model "${AUTOPEP_CODEX_MODEL:-gpt-5.5}" '
        "--dangerously-bypass-approvals-and-sandbox --skip-git-repo-check "
        '--cd /app "$AUTOPEP_CODEX_TASK_PROMPT"'
    )

    return "\n".join(
        [
            "set -euo pipefail",
            f"mkdir -p {shlex.quote(WORKSPACE_DIR)}/{shlex.quote(project_id)}",
            'export PATH="/root/.bun/bin:$PATH"',
            f"export AUTOPEP_PROJECT_WORKSPACE={shlex.quote(WORKSPACE_DIR)}/{shlex.quote(project_id)}",
            "export AUTOPEP_LIFE_SCIENCE_PLUGIN_PATH=/opt/life-science-research",
            f"export AUTOPEP_CODEX_TASK_PROMPT={shlex.quote(codex_prompt)}",
            'export AUTOPEP_AGENT_MODE="${AUTOPEP_AGENT_MODE:-codex}"',
            'export AUTOPEP_CODEX_MODEL="${AUTOPEP_CODEX_MODEL:-gpt-5.5}"',
            'if [ -z "${AUTOPEP_CODEX_COMMAND:-}" ]; then',
            f"  export AUTOPEP_CODEX_COMMAND={shlex.quote(default_codex_command)}",
            "fi",
            f"bun run worker:cif --run-id {shlex.quote(run_id)}",
            f"sync {shlex.quote(WORKSPACE_DIR)} || true",
        ]
    )


@app.function(
    image=sandbox_image,
    secrets=[runtime_secret],
    timeout=SANDBOX_TIMEOUT_SECONDS,
    volumes={WORKSPACE_DIR: workspace_volume},
    cpu=0.125,
    memory=512,
)
def launch_autopep_sandbox(run_id: str, project_id: str) -> str | None:
    command = _sandbox_command(run_id=run_id, project_id=project_id)
    process = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=APP_DIR,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )

    if process.stdout:
        for line in process.stdout:
            print(line, end="", flush=True)

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Autopep worker exited with code {return_code}.")

    return run_id


@app.function(image=control_image, secrets=[webhook_secret], timeout=120)
@modal.fastapi_endpoint(method="POST", docs=False, label="start-run")
async def start_run(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    _require_bearer(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise _http_error(status_code=422, detail="Expected a JSON object.")

    run_id = _require_uuid(payload, "runId")
    project_id = _require_uuid(payload, "projectId")
    function_call = launch_autopep_sandbox.spawn(
        run_id=run_id,
        project_id=project_id,
    )
    return JSONResponse(
        content={
            "accepted": True,
            "functionCallId": function_call.object_id,
        },
        status_code=202,
    )
