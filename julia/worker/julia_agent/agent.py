from __future__ import annotations

import json
import os
import sys
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
JULIA_FIREWORKS_DEEPSEEK_MODEL = "accounts/fireworks/models/deepseek-v4-pro"
JULIA_FIREWORKS_REASONING_EFFORT = "high"
JULIA_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
JULIA_OPENROUTER_DEEPSEEK_MODEL = "deepseek/deepseek-v4-pro"
JULIA_OPENROUTER_REASONING_EFFORT = "high"
JULIA_DEEPSEEK_PROVIDERS = {"fireworks", "openrouter"}
JULIA_DEFAULT_DEEPSEEK_PROVIDER = "openrouter"
JULIA_DEEPSEEK_TIMEOUT_SECONDS = 4 * 60 * 60
JULIA_DEFAULT_AGENT_MAX_TURNS = sys.maxsize

# SiliconFlow's DeepSeek thinking-mode endpoint rejects continuation requests
# unless `reasoning_content` is echoed back on every prior assistant message
# (provider error 20015). The OpenAI Agents SDK's chat-completions model does
# not preserve that field across turns, so multi-turn tool calls fail on
# SiliconFlow. Default-ignore it so OpenRouter routes to a permissive provider.
JULIA_DEFAULT_OPENROUTER_PROVIDER_IGNORE: tuple[str, ...] = ("SiliconFlow",)

JULIA_AGENT_INSTRUCTIONS = """\
You are Julia, a protein-design assistant running through the OpenAI Agents SDK
inside a per-run Modal worker workspace.

Operate only inside this run's workspace directory. The workspace is a fresh
temporary folder for this run; tool outputs go under outputs/ subdirectories
(outputs/literature, outputs/pdb, outputs/proteina_runs, outputs/chai_runs,
outputs/scoring_runs, outputs/tool_logs). Use workspace-relative paths returned
by tools when chaining calls.

You can create files, run bash/Python, search PMC, search/fetch RCSB PDB
structures, call Proteina-Complexa, fold sequences or target+binder complexes
with Chai-1, and score candidates with the interaction and quality scorers.

Use this workflow whenever the user requests binder protein generation, e.g.
"generate a protein that binds to X" or "design binders for X":
1. Run literature_search to identify the target, relevant binding/interface
   biology, known ligands/complexes, and any useful hotspot residues.
2. Run search_pdb for target structures and target-bound complexes, not only
   apo target structures. Some PDB entries already have bound protein or
   peptide binders/partners; prefer relevant structures with attached binders
   because an existing binder can seed Proteina warm-start generation.
3. Choose promising structures or chains using the literature context,
   structural relevance, method, resolution, chain lengths, and bound
   partners/ligands when available.
4. Fetch the selected PDB target or target-complex structure with fetch_pdb using
   file_format="cif". Use CIF/mmCIF for fetched target structures unless a
   downstream tool explicitly requires PDB.
5. Inspect files with execute_bash or execute_python to confirm chains, target
   sequence, residue numbering, candidate inputs, and whether a bound binder or
   partner chain is present.
6. Almost always prefer a warm start when PDB search finds an existing bound
   binder/partner for the target. Use execute_python to prepare a clean
   warm_start_path from the existing binder geometry. Cold start is mainly a
   fallback so the workflow still runs when no suitable binder exists, the PDB
   only has small-molecule ligands, or warm-start preparation fails. For clean
   binder-only CIF/mmCIF seeds, omit warm_start_chain. When the warm-start file
   has multiple chains, pass warm_start_chain as the binder or partner chain to
   seed from. Do not infer mmCIF chain IDs with fixed-width PDB columns. For
   Proteina-generated complexes with target chains A/B and binder chain C, pass
   warm_start_chain="C" unless inspection shows a different binder chain.
7. Run run_proteina with num_candidates=3. Pass warm_start_path whenever a
   suitable prepared existing binder seed is available. For hotspot_residues,
   use Proteina format only: chain ID immediately followed by residue number, e.g.
   ["A41", "A145", "A166"]. Do not include residue names or separators;
   wrong examples are "A:HIS41", "A:CYS145", and "A:GLU166".
8. Fold each of the 3 Proteina candidates with run_chai as target+binder
   complexes. Use target_sequence and binder_sequence from run_proteina
   outputs when available. Run the 3 Chai folds in parallel when the tool
   runner permits parallel calls.
9. Run run_scorers on each folded candidate, using the best Chai complex
   structure path for each candidate when available. Run the 3 scoring jobs in
   parallel when the tool runner permits parallel calls.
10. Report ranked results with candidate file paths, Chai output paths, scorer
   output paths, and a clear split between literature/PDB evidence and
   computed model/scoring output.

Use concrete file paths from tool outputs. Prefer CIF/mmCIF files for Proteina
target inputs and Chai CIF/PDB outputs for scoring. Do not claim wet-lab
validation, clinical efficacy, safety, or therapeutic readiness.

Keep replies concise, but show enough detail that the user can see the next
useful command or output file.
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
    model_name = (
        os.getenv("FIREWORKS_DEEPSEEK_MODEL") or JULIA_FIREWORKS_DEEPSEEK_MODEL
    ).strip()
    if not (api_key and model_name):
        return None
    base_url = (
        os.getenv("FIREWORKS_BASE_URL") or JULIA_FIREWORKS_BASE_URL
    ).strip().rstrip("/")
    reasoning_effort = (
        os.getenv("FIREWORKS_REASONING_EFFORT") or JULIA_FIREWORKS_REASONING_EFFORT
    ).strip()

    import httpx
    from agents import ModelSettings, OpenAIChatCompletionsModel
    from openai import AsyncOpenAI
    from openai.types.shared import Reasoning

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=httpx.Timeout(timeout=JULIA_DEEPSEEK_TIMEOUT_SECONDS, connect=30.0),
    )
    model = OpenAIChatCompletionsModel(model=model_name, openai_client=client)
    settings = ModelSettings(reasoning=Reasoning(effort=reasoning_effort))  # type: ignore[arg-type]
    return model, settings


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
    reasoning_effort = (
        os.getenv("OPENROUTER_REASONING_EFFORT") or JULIA_OPENROUTER_REASONING_EFFORT
    ).strip()

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
    ignore_raw = os.getenv("OPENROUTER_PROVIDER_IGNORE")
    if ignore_raw is None or not ignore_raw.strip():
        ignore = list(JULIA_DEFAULT_OPENROUTER_PROVIDER_IGNORE)
    else:
        ignore = [item.strip() for item in ignore_raw.split(",") if item.strip()]
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


def _agent_max_turns() -> int:
    """Max turns the Agents-SDK runner is allowed for one streamed turn.

    Mirrors autopep2's `_agent_max_turns`. Defaults to ``sys.maxsize`` so the
    8-step protein-design workflow is never truncated; override with
    ``JULIA_MAX_AGENT_TURNS`` (positive int).
    """
    configured = os.getenv("JULIA_MAX_AGENT_TURNS", "").strip()
    if not configured:
        return JULIA_DEFAULT_AGENT_MAX_TURNS
    try:
        parsed = int(configured)
    except ValueError:
        return JULIA_DEFAULT_AGENT_MAX_TURNS
    return JULIA_DEFAULT_AGENT_MAX_TURNS if parsed <= 0 else parsed


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
