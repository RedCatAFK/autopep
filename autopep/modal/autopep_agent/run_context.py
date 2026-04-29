from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRunContext:
    """Per-run secrets + identifiers that biology tools need at call time.

    The LLM never sees these values. The runner builds a ``ToolRunContext``
    from ``WorkerConfig`` at the start of each agent run and stashes it in a
    ``ContextVar`` so tool implementations can pull URLs and API keys without
    accepting them as function arguments (which would leak into tool-call
    traces and the JSON schema the model receives).
    """

    workspace_id: str
    run_id: str
    database_url: str
    proteina_base_url: str
    proteina_api_key: str
    chai_base_url: str
    chai_api_key: str
    scoring_base_url: str
    scoring_api_key: str


_tool_run_context_var: ContextVar[ToolRunContext | None] = ContextVar(
    "autopep_tool_run_context",
    default=None,
)


def set_tool_run_context(ctx: ToolRunContext) -> None:
    """Install ``ctx`` as the current tool run context.

    Each Modal function call uses its own asyncio event loop; the ContextVar
    is scoped to that loop, so it is safe to leave the context set for the
    lifetime of a run.
    """

    _tool_run_context_var.set(ctx)


def get_tool_run_context() -> ToolRunContext:
    """Return the current ``ToolRunContext``.

    Raises ``RuntimeError`` if no context has been set — biology tools rely on
    this fail-fast behavior because running them without a context would mean
    silently calling endpoints with no credentials.
    """

    ctx = _tool_run_context_var.get()
    if ctx is None:
        raise RuntimeError(
            "ToolRunContext is not set. The runner must call "
            "set_tool_run_context(ctx) before invoking biology tools.",
        )
    return ctx
