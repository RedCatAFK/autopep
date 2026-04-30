from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_DIRS = (
    "outputs/literature",
    "outputs/pdb",
    "outputs/proteina_runs",
    "outputs/chai_runs",
    "outputs/scoring_runs",
    "outputs/tool_logs",
)

JULIA_AGENT_INSTRUCTIONS = """\
You are Julia, a concise protein-design assistant.

General chat is allowed. Answer direct scientific or workflow questions briefly when
no tool-backed run is needed.

For binder generation requests, follow the autopep2 single-pass workflow: clarify
only blockers, use the provided target context, generate candidates once, fold or
score as available, and summarize the best next action. Prefer warm starts when a
compatible prior run, target, binder, or intermediate artifact is available.

Use CIF or mmCIF files for protein targets whenever structure context is needed.
Keep replies concise and focused on evidence, assumptions, and generated artifacts.

Do not claim wet-lab validation, efficacy, safety, or therapeutic readiness. Treat
designs as computational hypotheses that require experimental validation.
"""


def build_manifest(
    context: dict[str, Any],
    *,
    artifact_paths: list[Path | str] | None = None,
    output_dirs: list[str] | tuple[str, ...] = DEFAULT_OUTPUT_DIRS,
):
    imports = _load_sandbox_imports()
    manifest_cls = imports["Manifest"]
    file_cls = imports["File"]

    entries: dict[str, Any] = {
        "inputs/context.json": file_cls(
            content=json.dumps(context, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
    }

    for artifact_path in artifact_paths or []:
        path = Path(artifact_path)
        entries[f"inputs/artifacts/{path.name}"] = file_cls(content=path.read_bytes())

    for output_dir in output_dirs:
        normalized = output_dir.strip("/")
        if normalized:
            entries[f"{normalized}/.keep"] = file_cls(content=b"")

    return manifest_cls(entries=entries)


def build_julia_agent(*, model: str | None = None, manifest=None):
    imports = _load_sandbox_imports_or_runtime_error()
    sandbox_agent_cls = imports["SandboxAgent"]

    return sandbox_agent_cls(
        name="Julia",
        instructions=JULIA_AGENT_INSTRUCTIONS,
        model=model or os.getenv("OPENAI_DEFAULT_MODEL"),
        default_manifest=manifest,
    )


def build_sandbox_run_config(
    *,
    manifest=None,
    app_name: str = "julia-agent-worker",
    timeout: int = 900,
):
    imports = _load_sandbox_imports_or_runtime_error()
    run_config_cls = imports["RunConfig"]
    sandbox_run_config_cls = imports["SandboxRunConfig"]
    modal_client_cls = imports["ModalSandboxClient"]
    modal_options_cls = imports["ModalSandboxClientOptions"]

    sandbox_config = sandbox_run_config_cls(
        client=modal_client_cls(),
        options=modal_options_cls(app_name=app_name, timeout=timeout),
        manifest=manifest,
    )
    return run_config_cls(sandbox=sandbox_config)


async def run_julia_agent(
    prompt: str,
    *,
    context: dict[str, Any],
    artifact_paths: list[Path | str] | None = None,
    max_turns: int = 10,
) -> str:
    imports = _load_sandbox_imports_or_runtime_error()
    runner = imports["Runner"]
    manifest = build_manifest(context, artifact_paths=artifact_paths)
    agent = build_julia_agent(manifest=manifest)
    run_config = build_sandbox_run_config(manifest=manifest)

    result = await runner.run(
        agent,
        input=prompt,
        max_turns=max_turns,
        run_config=run_config,
    )
    return str(getattr(result, "final_output", result))


def _load_sandbox_imports_or_runtime_error() -> dict[str, Any]:
    try:
        return _load_sandbox_imports()
    except ImportError as error:
        raise RuntimeError(
            "OpenAI Agents Modal sandbox extension is unavailable. Install a package "
            "version that provides agents.sandbox and agents.extensions.sandbox before "
            "enabling live Julia worker runs."
        ) from error


def _load_sandbox_imports() -> dict[str, Any]:
    from agents import Runner
    from agents.extensions.sandbox import ModalSandboxClient, ModalSandboxClientOptions
    from agents.run import RunConfig
    from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
    from agents.sandbox.entries import File

    return {
        "Runner": Runner,
        "RunConfig": RunConfig,
        "Manifest": Manifest,
        "SandboxAgent": SandboxAgent,
        "SandboxRunConfig": SandboxRunConfig,
        "File": File,
        "ModalSandboxClient": ModalSandboxClient,
        "ModalSandboxClientOptions": ModalSandboxClientOptions,
    }
