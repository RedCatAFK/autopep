from __future__ import annotations

import inspect
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import modal
from agents import Agent, RunConfig, Runner

try:  # OpenAI Agents SDK sandbox APIs are version-sensitive.
    from agents.extensions.sandbox.modal import (
        ModalSandboxClient,
        ModalSandboxClientOptions,
    )
except Exception:  # pragma: no cover - exercised only with older SDK installs.
    ModalSandboxClient = None  # type: ignore[assignment]
    ModalSandboxClientOptions = None  # type: ignore[assignment]

try:
    from agents.sandbox import SandboxAgent, SandboxRunConfig
except Exception:  # pragma: no cover - exercised only with older SDK installs.
    SandboxAgent = None  # type: ignore[assignment]
    SandboxRunConfig = None  # type: ignore[assignment]

from autopep_agent.biology_tools import (
    fold_sequences_with_chai,
    generate_binder_candidates,
    score_candidate_interactions,
)
from autopep_agent.config import WorkerConfig
from autopep_agent.db import (
    AttachmentRow,
    claim_run,
    get_run_attachments,
    get_run_context,
    mark_run_completed,
    mark_run_failed,
)
from autopep_agent.demo_pipeline import execute_demo_one_loop
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import download_object as r2_download_object
from autopep_agent.research_tools import RESEARCH_TOOLS
from autopep_agent.run_context import (
    ToolRunContext,
    reset_tool_run_context,
    set_tool_run_context,
)
from autopep_agent.smoke_agent import (
    SMOKE_MODEL,
    build_ping_agent,
    build_sandbox_agent,
    build_tool_agent,
)
from autopep_agent.streaming import (
    SandboxOutputCoalescer,
    extract_sandbox_event,
    normalize_stream_event,
)


SANDBOX_APP_NAME = "autopep-agent-runtime"
SANDBOX_TIMEOUT_SECONDS = 60 * 60
SMOKE_TASK_KINDS = {"smoke_chat", "smoke_tool", "smoke_sandbox"}
OPENAI_PROMPT_BLOCKED_REASON = "openai_prompt_blocked"
OPENAI_PROMPT_BLOCKED_MESSAGE = "Message blocked by OpenAI."
OPENAI_PROMPT_BLOCKED_SUMMARY = "OpenAI blocked this message for safety reasons."

# Mount path of the ``autopep-workspaces`` Modal volume. Attachments are
# downloaded into ``{WORKSPACE_DIR}/{workspace_id}/inputs/`` so the agent
# (and any sandbox commands it spawns) can read them by absolute path.
WORKSPACE_DIR = "/autopep-workspaces"

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_attachment_filename(name: str) -> str:
    """Reduce ``name`` to a filesystem-safe basename.

    The artifact ``name`` flows from user uploads, so it can contain path
    separators, NUL bytes, or other characters that would let a malicious
    upload escape the workspace's ``inputs/`` directory or clobber a sibling
    file. We:

      * take only the basename (drop directory components)
      * replace anything outside ``[A-Za-z0-9._-]`` with ``_``
      * collapse leading dots so the file cannot become hidden / dotfile
      * fall back to a deterministic placeholder if nothing remains
    """

    base = os.path.basename(name).strip()
    cleaned = _FILENAME_SAFE_RE.sub("_", base).lstrip(".")
    return cleaned or "attachment"


async def _download_attachments_to_inputs(
    attachments: list[AttachmentRow],
    *,
    workspace_id: str,
    config: WorkerConfig,
) -> list[Path]:
    """Materialize ``attachments`` under the workspace volume's ``inputs/``.

    Each attachment is fetched from R2 once and written to
    ``/autopep-workspaces/{workspace_id}/inputs/{sanitized_filename}``. The
    returned list preserves input order so callers can format a stable
    "Attached files available at" announcement for the agent.

    On a filename collision (two artifacts sanitize to the same basename),
    later entries are disambiguated with the first 8 characters of their
    artifact id so neither attachment silently wins.
    """

    if not attachments:
        # Skip mkdir entirely on the no-attachments path so callers do not
        # need a writable workspace volume mounted just to invoke a chat run
        # without attachments (and so unit tests do not need to fake the
        # ``/autopep-workspaces`` mount path).
        return []

    inputs_dir = Path(WORKSPACE_DIR) / workspace_id / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    paths: list[Path] = []
    for attachment in attachments:
        safe_name = _sanitize_attachment_filename(attachment.name)
        if safe_name in used:
            stem, dot, ext = safe_name.partition(".")
            suffix = attachment.artifact_id[:8]
            safe_name = f"{stem}-{suffix}{dot}{ext}" if dot else f"{stem}-{suffix}"
        used.add(safe_name)
        dest = inputs_dir / safe_name
        await r2_download_object(
            bucket=config.r2_bucket,
            account_id=config.r2_account_id,
            access_key_id=config.r2_access_key_id,
            secret_access_key=config.r2_secret_access_key,
            key=attachment.storage_key,
            dest_path=dest,
        )
        paths.append(dest)
    return paths


def _format_attachments_system_message(paths: list[Path]) -> str:
    """Format the system-style hint that announces downloaded attachment paths."""

    bullet_lines = "\n".join(f"  {path}" for path in paths)
    return "Attached files available at:\n" + bullet_lines


def _token_queue_name(run_id: str) -> str:
    return f"autopep-tokens-{run_id}"


async def _push_token_delta(run_id: str, text: str) -> None:
    """Push a streaming assistant-token delta onto the per-run Modal Queue.

    Best-effort: the SSE consumer (run_stream endpoint) may not be connected,
    or Modal may be unreachable during local tests. Failures are swallowed so
    streaming side-channel issues never break the main run.
    """
    try:
        queue = modal.Queue.from_name(_token_queue_name(run_id), create_if_missing=True)
        await queue.put.aio({"type": "delta", "text": text})
    except Exception:
        pass


async def _push_token_done(run_id: str) -> None:
    """Push a `done` sentinel onto the per-run Modal Queue. Best-effort."""
    try:
        queue = modal.Queue.from_name(_token_queue_name(run_id), create_if_missing=True)
        await queue.put.aio({"type": "done"})
    except Exception:
        pass


# Per-run accumulator for assistant text deltas. Keyed by run_id so a single
# Modal worker process can serve multiple runs without cross-contamination.
# Cleared in `_flush_assistant_message` when the run completes; if a run
# fails before `response.completed`, the buffer is best-effort and may leak —
# acceptable because the buffer is cheap and bounded by run lifetime.
ASSISTANT_TEXT_BUFFERS: dict[str, list[str]] = {}


def _accumulate_assistant_text(run_id: str, text: str) -> None:
    """Append a token delta to the per-run assistant-text buffer."""
    ASSISTANT_TEXT_BUFFERS.setdefault(run_id, []).append(text)


def _flush_assistant_message(run_id: str, thread_id: str) -> None:
    """POST the accumulated assistant text to the Next.js webhook.

    Best-effort: if the webhook is unconfigured (local dev / smoke contexts)
    or unreachable, the run still succeeds. The webhook upserts a deterministic
    `messages` row keyed off (runId, role) so retries are idempotent.
    """
    text = "".join(ASSISTANT_TEXT_BUFFERS.pop(run_id, []))
    if not text:
        return
    secret = os.environ.get("AUTOPEP_MODAL_WEBHOOK_SECRET", "")
    base = os.environ.get("AUTOPEP_NEXT_PUBLIC_URL", "")
    if not secret or not base:
        # Local-dev / smoke / test contexts may not configure webhooks; skip
        # silently rather than failing the run.
        return
    body = json.dumps(
        {
            "content": text,
            "metadata": {},
            "role": "assistant",
            "runId": run_id,
            "threadId": thread_id,
        },
    ).encode("utf-8")
    url = f"{base.rstrip('/')}/api/agent/messages"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        # Best-effort: do not fail the run if the webhook is unreachable.
        pass


def _extract_raw_response_payload(event: Any) -> tuple[str | None, Any]:
    """Return ``(data_type, data)`` for a ``raw_response_event`` if applicable.

    Handles both attribute-style SDK objects and dict-style events. Returns
    ``(None, None)`` for any non-raw-response event.
    """
    event_type = getattr(event, "type", None)
    if event_type is None and isinstance(event, dict):
        event_type = event.get("type")
    if event_type != "raw_response_event":
        return None, None

    data = getattr(event, "data", None)
    if data is None and isinstance(event, dict):
        data = event.get("data")
    if data is None:
        return None, None

    data_type = getattr(data, "type", None)
    if data_type is None and isinstance(data, dict):
        data_type = data.get("type")
    return data_type, data


@dataclass(frozen=True)
class SandboxCompatibilityConfig:
    """Fallback used when the installed Agents SDK lacks native sandbox config."""

    client: Any | None = None
    options: Any | None = None
    unavailable_reason: str | None = None


def choose_task_kind(prompt: str) -> str:
    normalized = prompt.lower()
    has_design_intent = "generate" in normalized or "design" in normalized
    has_binding_intent = "bind" in normalized or "binder" in normalized
    mentions_protease = "3cl" in normalized or "protease" in normalized

    if has_design_intent and has_binding_intent and mentions_protease:
        return "branch_design"
    if "mutate" in normalized or "mutation" in normalized:
        return "mutate_structure"
    if "pdb" in normalized or "structure" in normalized:
        return "structure_search"
    return "chat"


AUTOPEP_TOOLS: list[object] = [
    *RESEARCH_TOOLS,
    generate_binder_candidates,
    fold_sequences_with_chai,
    score_candidate_interactions,
]


def _registered_tool_names(tools: list[object]) -> list[str]:
    return [
        str(name)
        for tool in tools
        if (name := getattr(tool, "name", None))
    ]


def _format_available_tools(tools: list[object]) -> str:
    return ", ".join(f"`{name}`" for name in _registered_tool_names(tools))


def build_agent_instructions(enabled_recipes: list[str] | None = None) -> str:
    recipe_bodies = [recipe.strip() for recipe in enabled_recipes or [] if recipe.strip()]
    recipes_text = "\n\n".join(f"Recipe:\n{recipe}" for recipe in recipe_bodies)

    sections = [
        "You are Autopep, an agent for protein binder design and analysis.",
        f"Available tools for this run: {_format_available_tools(AUTOPEP_TOOLS)}.",
        (
            "Use life-science-research discipline: cite uncertainty, prefer primary "
            "biomedical evidence, and distinguish literature evidence from model output."
        ),
        (
            "For general biomedical explanations, answer from established knowledge "
            "without calling tools. Use the literature tools when the user asks for "
            "live, recent, or source-backed literature evidence."
        ),
        (
            "For live literature requests, use `search_pubmed_literature` and "
            "`search_europe_pmc_literature` before answering. Do not say you lack "
            "live database access when these tools are available; if a source call "
            "fails, name the failed source and answer only from gathered evidence."
        ),
        (
            "For binder workflows, use `generate_binder_candidates`, "
            "`fold_sequences_with_chai`, and `score_candidate_interactions` only "
            "when the user supplies enough target structure or sequence context. "
            "If the task requires PDB/RCSB retrieval, target preparation, mutation, "
            "visualization, web search, shell execution, or arbitrary Python, state "
            "that the capability is not available in this runtime instead of "
            "inventing a tool call."
        ),
        (
            "When binder inputs are available, run this workflow: literature research "
            "when useful, call `generate_binder_candidates`, call "
            "`fold_sequences_with_chai` with the target sequence so Chai folds "
            "target-binder complexes, call `score_candidate_interactions`, then "
            "provide a ranked summary."
        ),
        (
            "Use computational screening language only. Do not claim wet-lab validation, "
            "clinical efficacy, safety, or therapeutic readiness."
        ),
        (
            "For binder tasks, explain target assumptions, requested hotspot residues, "
            "candidate sequence or structure identifiers, fold confidence, interaction "
            "scores, and practical next computational checks."
        ),
    ]

    if recipes_text:
        sections.append("Enabled recipes:\n" + recipes_text)

    return "\n\n".join(sections)


def build_autopep_agent(enabled_recipes: list[str] | None = None) -> Agent:
    return Agent(
        name="Autopep",
        instructions=build_agent_instructions(enabled_recipes),
        tools=AUTOPEP_TOOLS,
    )


def build_sandbox_config() -> Any:
    if (
        ModalSandboxClient is None
        or ModalSandboxClientOptions is None
        or SandboxRunConfig is None
    ):
        return SandboxCompatibilityConfig(
            unavailable_reason="Installed Agents SDK does not expose Modal sandbox APIs.",
        )

    try:
        options = ModalSandboxClientOptions(
            app_name=SANDBOX_APP_NAME,
            timeout=SANDBOX_TIMEOUT_SECONDS,
        )
    except TypeError:
        options = ModalSandboxClientOptions(app_name=SANDBOX_APP_NAME)

    client = ModalSandboxClient()

    try:
        return SandboxRunConfig(client=client, options=options)
    except TypeError:
        return SandboxCompatibilityConfig(
            client=client,
            options=options,
            unavailable_reason="Installed Agents SDK has an incompatible SandboxRunConfig.",
        )


def _run_config_supports_sandbox() -> bool:
    try:
        return "sandbox" in inspect.signature(RunConfig).parameters
    except (TypeError, ValueError):
        return False


def _build_run_config(
    *,
    model: str,
    run_id: str,
    thread_id: str,
    workspace_id: str,
) -> RunConfig:
    kwargs: dict[str, Any] = {
        "model": model,
        "workflow_name": "Autopep agent runtime",
        "group_id": thread_id,
        "trace_metadata": {
            "run_id": run_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
        },
    }
    sandbox_config = build_sandbox_config()
    if (
        _run_config_supports_sandbox()
        and SandboxRunConfig is not None
        and isinstance(sandbox_config, SandboxRunConfig)
    ):
        kwargs["sandbox"] = sandbox_config
    return RunConfig(**kwargs)


def _build_runner_input(
    *,
    prompt: str,
    run_id: str,
    task_kind: str,
    thread_id: str,
    workspace_id: str,
    attachment_paths: list[Path] | None = None,
) -> str:
    """Build the agent ``input`` string sent to ``Runner.run_streamed``.

    When ``attachment_paths`` is non-empty, prepend an "Attached files
    available at" block listing each on-volume path so the agent sees the
    files BEFORE it processes the user prompt. The Agents SDK accepts a
    plain string for ``input``, and the agent's ``instructions`` already
    define its persona, so the cheapest way to surface attachments is to
    extend the input itself with a system-style preamble.
    """

    sections: list[str] = [
        f"Run ID: {run_id}",
        f"Workspace ID: {workspace_id}",
        f"Thread ID: {thread_id}",
        f"Task kind: {task_kind}",
    ]
    if attachment_paths:
        sections.append("")
        sections.append(_format_attachments_system_message(attachment_paths))
    sections.extend(["", "User prompt:", prompt])
    return "\n".join(sections)


def _summarize_error(error: BaseException) -> str:
    summary = str(error).strip() or error.__class__.__name__
    return summary[:1400]


def _is_openai_prompt_block_summary(error_summary: str) -> bool:
    normalized = error_summary.lower()
    return "invalid prompt" in normalized and (
        "limited access to this content for safety reasons" in normalized
        or ("content" in normalized and "safety reasons" in normalized)
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _stream_events(streamed_run: Any) -> Any:
    stream_events = getattr(streamed_run, "stream_events", None)
    events = stream_events() if callable(stream_events) else stream_events
    if events is None:
        return

    if hasattr(events, "__aiter__"):
        async for event in events:
            yield event
        return

    for event in events:
        yield event


async def _append_normalized_stream_events(
    streamed_run: Any,
    *,
    run_id: str,
    writer: EventWriter,
    thread_id: str | None = None,
) -> None:
    coalescer = SandboxOutputCoalescer()
    async for event in _stream_events(streamed_run):
        # Side-channel: forward raw token deltas and the completion sentinel
        # to the per-run Modal Queue so the run_stream SSE endpoint can tail
        # them. normalize_stream_event already filters raw_response_event from
        # the durable ledger, so this is the only place that can see them.
        data_type, data = _extract_raw_response_payload(event)
        if data_type == "response.output_text.delta":
            delta = getattr(data, "delta", None)
            if delta is None and isinstance(data, dict):
                delta = data.get("delta", "")
            if delta:
                delta_text = str(delta)
                await _push_token_delta(run_id, delta_text)
                # Accumulate the same text into the per-run buffer so that
                # `response.completed` can POST the full assistant message
                # to the Next.js webhook for durable replay across reloads.
                _accumulate_assistant_text(run_id, delta_text)
        elif data_type == "response.completed":
            await _push_token_done(run_id)
            if thread_id is not None:
                try:
                    _flush_assistant_message(run_id, thread_id)
                except Exception:
                    # Persistence is best-effort; never fail the run if the
                    # webhook helper raises unexpectedly.
                    pass

        # Sandbox events are state-y: per-chunk stdout/stderr deltas must be
        # buffered in-memory and merged into the parent ``sandbox_command_
        # completed`` event so the ledger only ever sees one started + one
        # completed row per command. Delta events are dropped from the ledger
        # (normalize_stream_event also filters them defensively).
        sandbox_event = extract_sandbox_event(event)
        if sandbox_event is not None:
            command_id = sandbox_event["command_id"]
            sandbox_type = sandbox_event["type"]
            if sandbox_type == "sandbox_stdout_delta":
                if command_id:
                    coalescer.stdout_delta(command_id, sandbox_event["text"])
                continue
            if sandbox_type == "sandbox_stderr_delta":
                if command_id:
                    coalescer.stderr_delta(command_id, sandbox_event["text"])
                continue
            if sandbox_type == "sandbox_command_started":
                if command_id:
                    coalescer.start(command_id)
                base_display = dict(sandbox_event["display"])
                if command_id and "commandId" not in base_display:
                    base_display["commandId"] = command_id
                await writer.append_event(
                    run_id=run_id,
                    event_type=sandbox_type,
                    title="Sandbox command started",
                    summary=str(base_display.get("command") or "") or None,
                    display=base_display,
                    raw=sandbox_event["raw"],
                )
                continue
            if sandbox_type == "sandbox_command_completed":
                base_display = dict(sandbox_event["display"])
                if command_id and "commandId" not in base_display:
                    base_display["commandId"] = command_id
                enriched_display = (
                    coalescer.complete(command_id, base_display=base_display)
                    if command_id
                    else base_display
                )
                exit_code = base_display.get("exitCode")
                summary = (
                    f"exit code {exit_code}" if exit_code is not None else None
                )
                await writer.append_event(
                    run_id=run_id,
                    event_type=sandbox_type,
                    title="Sandbox command completed",
                    summary=summary,
                    display=enriched_display,
                    raw=sandbox_event["raw"],
                )
                continue

        normalized = normalize_stream_event(event)
        if normalized is None:
            continue
        await writer.append_event(
            run_id=run_id,
            event_type=normalized["type"],
            title=normalized["title"],
            summary=normalized.get("summary"),
            display=normalized.get("display"),
            raw=normalized.get("raw"),
        )


async def _append_failure_event(
    writer: EventWriter,
    *,
    run_id: str,
    error_summary: str,
    blocked_by_openai: bool = False,
    raw_error_summary: str | None = None,
) -> None:
    try:
        if blocked_by_openai:
            await writer.append_event(
                run_id=run_id,
                event_type="run_failed",
                title="Message blocked by OpenAI",
                summary=OPENAI_PROMPT_BLOCKED_SUMMARY,
                display={
                    "error": raw_error_summary or error_summary,
                    "message": OPENAI_PROMPT_BLOCKED_MESSAGE,
                    "provider": "openai",
                    "reason": OPENAI_PROMPT_BLOCKED_REASON,
                },
                raw={"error": raw_error_summary or error_summary},
            )
            return

        await writer.append_event(
            run_id=run_id,
            event_type="run_failed",
            title="Run failed",
            summary=error_summary,
            display={"error": error_summary},
        )
    except Exception:
        pass


async def _mark_failure(database_url: str, *, run_id: str, error_summary: str) -> None:
    try:
        await mark_run_failed(database_url, run_id, error_summary)
    except Exception:
        pass


async def _run_modal_sandbox_echo() -> dict[str, Any]:
    """Run the smoke sandbox command through the Agents SDK Modal sandbox client."""

    if ModalSandboxClient is None or ModalSandboxClientOptions is None:
        raise RuntimeError("Installed Agents SDK does not expose Modal sandbox APIs.")

    try:
        options = ModalSandboxClientOptions(
            app_name=SANDBOX_APP_NAME,
            sandbox_create_timeout_s=60,
            timeout=120,
        )
    except TypeError:
        options = ModalSandboxClientOptions(app_name=SANDBOX_APP_NAME)

    client = ModalSandboxClient()
    session = await client.create(options=options)
    try:
        async with session:
            result = await session.exec("echo sandbox-ok", timeout=30, shell=True)
    finally:
        await client.delete(session)

    stdout_bytes = getattr(result, "stdout", b"")
    stderr_bytes = getattr(result, "stderr", b"")
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    exit_code = int(getattr(result, "exit_code", 1))
    if exit_code != 0:
        raise RuntimeError(
            f"Smoke sandbox command exited {exit_code}: {stderr or stdout}",
        )
    return {
        "command": "echo sandbox-ok",
        "exit_code": exit_code,
        "stderr": stderr,
        "stdout": stdout,
    }


async def _execute_smoke_run(
    *,
    run_context: Any,
    run_id: str,
    thread_id: str,
    workspace_id: str,
    writer: EventWriter,
) -> None:
    if os.environ.get("AUTOPEP_ALLOW_SMOKE_RUNS") != "1":
        raise RuntimeError("Smoke runs require AUTOPEP_ALLOW_SMOKE_RUNS=1.")

    task_kind = run_context.task_kind
    # DB-created runs currently default to the production model. Smoke runs are
    # intentionally cheap, so only honor an explicitly persisted mini model.
    model = run_context.model if "mini" in str(run_context.model or "") else SMOKE_MODEL
    run_config = _build_run_config(
        model=model,
        run_id=run_id,
        thread_id=thread_id,
        workspace_id=workspace_id,
    )

    if task_kind == "smoke_chat":
        agent = build_ping_agent(model=model)
    elif task_kind == "smoke_tool":
        agent = build_tool_agent(model=model)
    elif task_kind == "smoke_sandbox":
        agent = build_sandbox_agent(model=model)
        # Single synthetic command id so the UI can correlate the
        # started / completed events for this smoke command. Per-chunk
        # stdout / stderr are coalesced into the completed event below
        # rather than persisted as their own ledger rows.
        command_id = f"smoke-{run_id}"
        coalescer = SandboxOutputCoalescer()
        coalescer.start(command_id)
        await writer.append_event(
            run_id=run_id,
            event_type="sandbox_command_started",
            title="Sandbox command started",
            summary="echo sandbox-ok",
            display={"commandId": command_id, "command": "echo sandbox-ok"},
            raw={
                "agent": getattr(agent, "name", "Autopep smoke sandbox"),
                "model": model,
                "runConfigBuilt": run_config is not None,
            },
        )
        sandbox_result = await _run_modal_sandbox_echo()
        # Feed the captured stdout / stderr through the coalescer as if they
        # had arrived as a single delta chunk each. The smoke path doesn't
        # actually stream chunks, but routing through the same helper keeps
        # the wire format identical to what the real Agents SDK sandbox
        # session will produce in production.
        if sandbox_result["stdout"]:
            coalescer.stdout_delta(command_id, sandbox_result["stdout"])
        if sandbox_result["stderr"]:
            coalescer.stderr_delta(command_id, sandbox_result["stderr"])
        completed_display = coalescer.complete(
            command_id,
            base_display={
                "commandId": command_id,
                "exitCode": sandbox_result["exit_code"],
            },
        )
        await writer.append_event(
            run_id=run_id,
            event_type="sandbox_command_completed",
            title="Sandbox command completed",
            summary=f"exit code {sandbox_result['exit_code']}",
            display=completed_display,
            raw=sandbox_result,
        )
        await writer.append_event(
            run_id=run_id,
            event_type="assistant_message_completed",
            title="Assistant message completed",
            summary=sandbox_result["stdout"].strip() or None,
            display={"text": sandbox_result["stdout"].strip()},
        )
        return
    else:  # Defensive guard if SMOKE_TASK_KINDS and routing drift.
        raise RuntimeError(f"Unsupported smoke task kind: {task_kind}")

    streamed_run = await _maybe_await(
        Runner.run_streamed(
            agent,
            input=run_context.prompt,
            run_config=run_config,
        ),
    )
    await _append_normalized_stream_events(
        streamed_run,
        run_id=run_id,
        writer=writer,
        thread_id=thread_id,
    )


async def execute_run(run_id: str, thread_id: str, workspace_id: str) -> None:
    """Execute one Autopep agent run end-to-end.

    Loads config inside the failure-handling block so that a missing non-DB env
    var still records a `run_failed` event when DATABASE_URL is reachable.
    Atomically claims the run from `queued` to `running` before any side
    effects so duplicate Modal invocations of the same `run_id` cannot execute
    concurrently or append duplicate events. Uses the persisted `task_kind`
    from the agent_run row instead of re-deriving from the prompt.
    """
    config: WorkerConfig | None = None
    writer: EventWriter | None = None
    database_url: str | None = None

    try:
        config = WorkerConfig.from_env()
        database_url = config.database_url
        writer = EventWriter(database_url)

        claimed = await claim_run(database_url, run_id=run_id)
        if not claimed:
            # Already running, completed, failed, or cancelled. Bail out
            # silently — this is a duplicate Modal invocation and any earlier
            # side-effects have already been recorded by the original caller.
            return

        run_context = await get_run_context(
            database_url,
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        task_kind = run_context.task_kind
        await writer.append_event(
            run_id=run_id,
            event_type="run_started",
            title="Run started",
            summary=f"Autopep started {task_kind}.",
            display={"taskKind": task_kind},
        )

        if task_kind in SMOKE_TASK_KINDS:
            await _execute_smoke_run(
                run_context=run_context,
                run_id=run_id,
                thread_id=thread_id,
                workspace_id=workspace_id,
                writer=writer,
            )
            await writer.append_event(
                run_id=run_id,
                event_type="run_completed",
                title="Run completed",
                summary="Autopep completed the smoke agent run.",
            )
            await mark_run_completed(database_url, run_id)
            return

        if task_kind == "branch_design":
            ctx_token = set_tool_run_context(
                ToolRunContext(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    database_url=database_url,
                    proteina_base_url=config.modal_proteina_url,
                    proteina_api_key=config.modal_proteina_api_key,
                    chai_base_url=config.modal_chai_url,
                    chai_api_key=config.modal_chai_api_key,
                    scoring_base_url=config.modal_protein_interaction_scoring_url,
                    scoring_api_key=config.modal_protein_interaction_scoring_api_key,
                ),
            )
            try:
                await execute_demo_one_loop(
                    config=config,
                    database_url=database_url,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    writer=writer,
                )
            finally:
                reset_tool_run_context(ctx_token)
            await writer.append_event(
                run_id=run_id,
                event_type="run_completed",
                title="Run completed",
                summary="Autopep completed the one-loop binder design workflow.",
            )
            await mark_run_completed(database_url, run_id)
            return

        # Fetch attachment artifacts referenced by the run's workspace and
        # download them into the workspace volume's ``inputs/`` directory
        # BEFORE the agent stream loop starts. The downloads run on a thread
        # via boto3 so they do not block the asyncio event loop. Failures
        # surface as run failures via the surrounding try/except.
        attachment_rows = await get_run_attachments(database_url, run_id=run_id)
        attachment_paths = await _download_attachments_to_inputs(
            attachment_rows,
            workspace_id=workspace_id,
            config=config,
        )
        if attachment_paths:
            await writer.append_event(
                run_id=run_id,
                event_type="attachments_mounted",
                title="Attachments mounted",
                summary=f"Mounted {len(attachment_paths)} attachment(s) into inputs/.",
                display={"paths": [str(path) for path in attachment_paths]},
            )

        agent = build_autopep_agent(run_context.enabled_recipes)
        run_config = _build_run_config(
            model=run_context.model or config.default_model,
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        # Install the per-run tool context BEFORE invoking Runner.run_streamed
        # so any tool the agent calls can read URLs / API keys / DB url /
        # workspace + run ids without the LLM ever seeing them. The matching
        # reset_tool_run_context in the finally block prevents the context
        # from leaking into a subsequent run that happens to share this
        # event loop / worker process.
        ctx_token = set_tool_run_context(
            ToolRunContext(
                workspace_id=workspace_id,
                run_id=run_id,
                database_url=database_url,
                proteina_base_url=config.modal_proteina_url,
                proteina_api_key=config.modal_proteina_api_key,
                chai_base_url=config.modal_chai_url,
                chai_api_key=config.modal_chai_api_key,
                scoring_base_url=config.modal_protein_interaction_scoring_url,
                scoring_api_key=config.modal_protein_interaction_scoring_api_key,
            ),
        )
        try:
            streamed_run = await _maybe_await(
                Runner.run_streamed(
                    agent,
                    input=_build_runner_input(
                        prompt=run_context.prompt,
                        run_id=run_id,
                        task_kind=task_kind,
                        thread_id=thread_id,
                        workspace_id=workspace_id,
                        attachment_paths=attachment_paths,
                    ),
                    run_config=run_config,
                ),
            )
            await _append_normalized_stream_events(
                streamed_run,
                run_id=run_id,
                writer=writer,
                thread_id=thread_id,
            )
        finally:
            reset_tool_run_context(ctx_token)

        await writer.append_event(
            run_id=run_id,
            event_type="run_completed",
            title="Run completed",
            summary="Autopep completed the streamed agent run.",
        )
        await mark_run_completed(database_url, run_id)
    except Exception as exc:
        raw_error_summary = _summarize_error(exc)
        blocked_by_openai = _is_openai_prompt_block_summary(raw_error_summary)
        error_summary = (
            OPENAI_PROMPT_BLOCKED_SUMMARY if blocked_by_openai else raw_error_summary
        )

        # Best-effort failure recording. If config loading itself failed before
        # we got `database_url`, fall back to the raw env var so the run still
        # gets marked failed when DATABASE_URL is set but other vars are not.
        failure_db_url = database_url or os.environ.get("DATABASE_URL")
        failure_writer = writer
        if failure_writer is None and failure_db_url is not None:
            failure_writer = EventWriter(failure_db_url)

        if failure_writer is not None:
            await _append_failure_event(
                failure_writer,
                run_id=run_id,
                error_summary=error_summary,
                blocked_by_openai=blocked_by_openai,
                raw_error_summary=raw_error_summary,
            )
        if failure_db_url is not None:
            await _mark_failure(
                failure_db_url,
                run_id=run_id,
                error_summary=error_summary,
            )
        if blocked_by_openai:
            await _push_token_done(run_id)
            return
        raise
