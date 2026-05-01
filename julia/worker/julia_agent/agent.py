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

JULIA_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
JULIA_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
JULIA_OPENROUTER_DEEPSEEK_MODEL = "deepseek/deepseek-v4-pro"
JULIA_DEEPSEEK_PROVIDERS = {"fireworks", "openrouter"}
JULIA_DEFAULT_DEEPSEEK_PROVIDER = "openrouter"
JULIA_DEEPSEEK_TIMEOUT_SECONDS = 4 * 60 * 60

JULIA_AGENT_INSTRUCTIONS = """\
You are Julia, a concise protein-design assistant.

General chat is allowed. Answer direct scientific or workflow questions briefly when
no tool-backed run is needed.

For binder generation requests ("generate a protein that binds X", "design binders
for X"), follow the autopep2 single-pass workflow:

1. literature_search to identify the target, binding/interface biology, known
   complexes, and useful hotspot residues.
2. search_pdb for target structures and target-bound complexes. Prefer entries
   with attached binders/partners because an existing binder seeds Proteina warm
   starts.
3. fetch_pdb (file_format="cif") for the chosen target or target-complex.
4. Inspect chains/sequences to confirm target and any bound binder chain. When
   useful, prepare a clean warm_start_path from the binder geometry.
5. run_proteina with num_candidates=3. Always pass an explicit `target_input`
   like "A1-150" describing the target residue range; Proteina rejects targets
   with insertion codes when target_input is missing. Use literature_search
   and chain inspection to choose a tight, biologically meaningful range.
   Prefer a warm start (warm_start_path) when an existing bound binder/partner
   is available. hotspot_residues use Proteina format: chain ID immediately
   followed by residue number, e.g. ["A41", "A145", "A166"]. Cold start is
   the fallback when no suitable bound binder exists.
6. run_chai for each Proteina candidate as a target+binder complex, using the
   target_sequence and binder_sequence Proteina returned.
7. run_scorers on each folded candidate, using the best Chai complex structure
   path.
8. Report ranked results with paths to generated artifacts.

Use CIF or mmCIF for protein targets whenever structure context is needed.
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
    """Build a SandboxAgent Manifest. Kept for unit tests; the live worker uses
    a regular Agent over a per-run workspace dir instead of a SandboxAgent."""
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
    """Test-shim retained for unit coverage; the live worker uses
    `build_julia_agent_with_tools` instead."""
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
    """Test-shim retained for unit coverage; live runs do not use SandboxRunConfig."""
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


def build_julia_agent_with_tools(workspace_dir: Path | str, *, model: Any = None):
    """Build a regular Agents-SDK Agent with all Julia tools bound to a per-run workspace.

    The live worker runs each request in its own temp workspace dir; the tools close
    over that path so model-supplied arguments stay confined to it.
    """
    from agents import Agent

    from julia_agent.tools_registry import build_julia_tools

    if model is not None:
        resolved_model: Any = model
        model_settings = None
    else:
        resolved_model, model_settings = _default_julia_model()

    agent_kwargs: dict[str, Any] = {
        "name": "Julia",
        "instructions": JULIA_AGENT_INSTRUCTIONS,
        "model": resolved_model,
        "tools": build_julia_tools(workspace_dir),
    }
    if model_settings is not None:
        agent_kwargs["model_settings"] = model_settings
    return Agent(**agent_kwargs)


def _default_julia_model() -> tuple[Any, Any]:
    """Pick the model the live worker should use.

    Defaults to OpenRouter-hosted DeepSeek (set OPENROUTER_API_KEY). Override
    with JULIA_DEEPSEEK_PROVIDER=fireworks to route through Fireworks instead.
    Falls back to OPENAI_DEFAULT_MODEL when the chosen provider's credentials
    are not configured. Returns ``(model, model_settings)``; ``model_settings``
    is ``None`` for plain string models or when no extra body is needed.
    """
    provider = (
        os.getenv("JULIA_DEEPSEEK_PROVIDER") or JULIA_DEFAULT_DEEPSEEK_PROVIDER
    ).strip().lower()
    if provider == "openrouter":
        result = _build_openrouter_deepseek_model()
        if result is not None:
            return result
    elif provider == "fireworks":
        result = _build_fireworks_deepseek_model()
        if result is not None:
            return result
    return os.getenv("OPENAI_DEFAULT_MODEL"), None


def _build_fireworks_deepseek_model() -> tuple[Any, Any] | None:
    api_key = os.getenv("FIREWORKS_API_KEY")
    model_name = os.getenv("FIREWORKS_DEEPSEEK_MODEL")
    if not (api_key and model_name):
        return None
    from agents import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=(os.getenv("FIREWORKS_BASE_URL") or JULIA_FIREWORKS_BASE_URL)
        .strip()
        .rstrip("/"),
    )
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client), None


def _build_openrouter_deepseek_model() -> tuple[Any, Any] | None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None
    model_name = (
        os.getenv("OPENROUTER_DEEPSEEK_MODEL") or JULIA_OPENROUTER_DEEPSEEK_MODEL
    ).strip()
    if not model_name:
        return None
    base_url = (
        os.getenv("OPENROUTER_BASE_URL") or JULIA_OPENROUTER_BASE_URL
    ).strip().rstrip("/")
    reasoning_effort = (os.getenv("OPENROUTER_REASONING_EFFORT") or "").strip()

    import httpx
    from agents import ModelSettings, OpenAIChatCompletionsModel
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=_openrouter_default_headers(),
        timeout=httpx.Timeout(timeout=JULIA_DEEPSEEK_TIMEOUT_SECONDS, connect=30.0),
    )
    extra_body: dict[str, Any] = {}
    if reasoning_effort:
        extra_body["reasoning"] = {"effort": reasoning_effort}
    provider_prefs = _openrouter_provider_preferences()
    if provider_prefs:
        extra_body["provider"] = provider_prefs
    model = OpenAIChatCompletionsModel(model=model_name, openai_client=client)
    settings = ModelSettings(extra_body=extra_body or None)
    return model, settings


def _openrouter_default_headers() -> dict[str, str]:
    headers = {
        "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_TITLE", "julia"),
    }
    referer = (
        os.getenv("OPENROUTER_HTTP_REFERER")
        or os.getenv("OPENROUTER_SITE_URL")
        or ""
    ).strip()
    if referer:
        headers["HTTP-Referer"] = referer
    return headers


def _openrouter_provider_preferences() -> dict[str, Any]:
    provider: dict[str, Any] = {}
    order = _csv_env("OPENROUTER_PROVIDER_ORDER")
    only = _csv_env("OPENROUTER_PROVIDER_ONLY")
    ignore = _csv_env("OPENROUTER_PROVIDER_IGNORE")
    allow_fallbacks = _bool_env("OPENROUTER_ALLOW_FALLBACKS")
    require_parameters = _bool_env("OPENROUTER_REQUIRE_PARAMETERS", default=True)

    if order:
        provider["order"] = order
    if only:
        provider["only"] = only
    if ignore:
        provider["ignore"] = ignore
    if allow_fallbacks is not None:
        provider["allow_fallbacks"] = allow_fallbacks
    if require_parameters is not None:
        provider["require_parameters"] = require_parameters
    return provider


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_env(name: str, *, default: bool | None = None) -> bool | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


async def run_julia_agent(
    prompt: str,
    *,
    context: dict[str, Any],
    artifact_paths: list[Path | str] | None = None,
    max_turns: int = 10,
) -> str:
    """Legacy non-streaming live entrypoint. Retained for ad-hoc smoke tests; the
    production live path is `live_runner.run_live_turn`."""
    from agents import Runner

    from julia_agent.tools import ensure_workspace_layout

    workspace = Path(context.get("workspace_dir", ".")).resolve()
    ensure_workspace_layout(workspace)
    agent = build_julia_agent_with_tools(workspace)
    result = await Runner.run(agent, input=prompt, max_turns=max_turns)
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
