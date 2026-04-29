from __future__ import annotations

from agents import Agent, function_tool

try:
    from agents.sandbox import SandboxAgent
except Exception:  # pragma: no cover - version-sensitive SDK surface.
    SandboxAgent = None  # type: ignore[assignment]


SMOKE_MODEL = "gpt-5.4-mini"


@function_tool
def smoke_now() -> str:
    return "now-ok"


def build_ping_agent(model: str = SMOKE_MODEL) -> Agent:
    return Agent(
        name="Autopep smoke ping",
        instructions="Reply exactly pong and nothing else.",
        model=model,
    )


def build_tool_agent(model: str = SMOKE_MODEL) -> Agent:
    return Agent(
        name="Autopep smoke tool",
        instructions=(
            "Call smoke_now exactly once. Reply with exactly the returned value "
            "and nothing else."
        ),
        model=model,
        tools=[smoke_now],
    )


def build_sandbox_agent(model: str = SMOKE_MODEL) -> Agent:
    agent_cls = SandboxAgent or Agent
    return agent_cls(
        name="Autopep smoke sandbox",
        instructions=(
            "Exercise the configured sandbox by running a minimal command that "
            "prints sandbox-ok, then reply exactly sandbox-ok."
        ),
        model=model,
    )
