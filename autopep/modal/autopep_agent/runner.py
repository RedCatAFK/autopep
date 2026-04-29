from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

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
    get_run_context,
    mark_run_completed,
    mark_run_failed,
)
from autopep_agent.events import EventWriter
from autopep_agent.streaming import normalize_stream_event


SANDBOX_APP_NAME = "autopep-agent-runtime"
SANDBOX_TIMEOUT_SECONDS = 60 * 60


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


def build_agent_instructions(enabled_recipes: list[str] | None = None) -> str:
    recipe_bodies = [recipe.strip() for recipe in enabled_recipes or [] if recipe.strip()]
    recipes_text = "\n\n".join(f"Recipe:\n{recipe}" for recipe in recipe_bodies)

    sections = [
        "You are Autopep, an agent for protein binder design and analysis.",
        (
            "Use life-science-research discipline: cite uncertainty, prefer primary "
            "biomedical evidence, and distinguish literature evidence from model output."
        ),
        (
            "MVP one-loop workflow: perform literature research, search PDB structures, "
            "prepare the target, call generate_binder_candidates, call "
            "fold_sequences_with_chai, call score_candidate_interactions, then provide "
            "a ranked summary."
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
        tools=[
            generate_binder_candidates,
            fold_sequences_with_chai,
            score_candidate_interactions,
        ],
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
) -> str:
    return "\n".join(
        [
            f"Run ID: {run_id}",
            f"Workspace ID: {workspace_id}",
            f"Thread ID: {thread_id}",
            f"Task kind: {task_kind}",
            "",
            "User prompt:",
            prompt,
        ],
    )


def _summarize_error(error: BaseException) -> str:
    summary = str(error).strip() or error.__class__.__name__
    return summary[:1400]


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


async def _append_failure_event(
    writer: EventWriter,
    *,
    run_id: str,
    error_summary: str,
) -> None:
    try:
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


async def execute_run(run_id: str, thread_id: str, workspace_id: str) -> None:
    config = WorkerConfig.from_env()
    writer = EventWriter(config.database_url)

    try:
        run_context = await get_run_context(
            config.database_url,
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        task_kind = choose_task_kind(run_context.prompt)
        await writer.append_event(
            run_id=run_id,
            event_type="run_started",
            title="Run started",
            summary=f"Autopep started {task_kind}.",
            display={"taskKind": task_kind},
        )

        agent = build_autopep_agent(run_context.enabled_recipes)
        run_config = _build_run_config(
            model=run_context.model or config.default_model,
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        streamed_run = await _maybe_await(
            Runner.run_streamed(
                agent,
                input=_build_runner_input(
                    prompt=run_context.prompt,
                    run_id=run_id,
                    task_kind=task_kind,
                    thread_id=thread_id,
                    workspace_id=workspace_id,
                ),
                run_config=run_config,
            ),
        )

        async for event in _stream_events(streamed_run):
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

        await writer.append_event(
            run_id=run_id,
            event_type="run_completed",
            title="Run completed",
            summary="Autopep completed the streamed agent run.",
        )
        await mark_run_completed(config.database_url, run_id)
    except Exception as exc:
        error_summary = _summarize_error(exc)
        await _append_failure_event(
            writer,
            run_id=run_id,
            error_summary=error_summary,
        )
        await _mark_failure(
            config.database_url,
            run_id=run_id,
            error_summary=error_summary,
        )
        raise
