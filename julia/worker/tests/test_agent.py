import json
from pathlib import Path

import pytest

from julia_agent.agent import (
    JULIA_AGENT_INSTRUCTIONS,
    JULIA_DEFAULT_OPENROUTER_PROVIDER_IGNORE,
    _openrouter_provider_preferences,
    build_julia_agent,
    build_manifest,
    build_sandbox_run_config,
)


def test_agent_instructions_cover_julia_runtime_requirements() -> None:
    instructions = JULIA_AGENT_INSTRUCTIONS.lower()
    # Whitespace-normalised view so checks survive prose line wraps.
    flattened = " ".join(instructions.split())

    assert "julia" in instructions
    assert "openai agents sdk" in instructions
    assert "literature_search" in instructions
    assert "search_pdb" in instructions
    assert "fetch_pdb" in instructions
    assert "run_proteina" in instructions
    assert "run_chai" in instructions
    assert "run_scorers" in instructions
    assert "warm start" in flattened
    assert "warm_start_chain" in instructions
    assert "cif" in instructions
    assert "mmcif" in instructions
    assert "in parallel" in instructions
    assert "concise" in instructions
    assert "wet-lab validation" in flattened
    assert "therapeutic readiness" in flattened
    # Hotspot format examples and counter-examples must both be present.
    assert '"a41"' in instructions
    assert '"a:his41"' in instructions


def test_manifest_includes_context_artifacts_and_output_placeholders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeManifest:
        def __init__(self, **kwargs):
            self.entries = kwargs["entries"]

    class FakeFile:
        def __init__(self, **kwargs):
            self.content = kwargs["content"]

    monkeypatch.setattr(
        "julia_agent.agent._load_sandbox_imports",
        lambda: {"Manifest": FakeManifest, "File": FakeFile},
    )

    artifact = tmp_path / "target.cif"
    artifact.write_bytes(b"data_target")

    manifest = build_manifest(
        {"runId": "run_1", "prompt": "design a binder"},
        artifact_paths=[artifact],
        output_dirs=["outputs/structures", "outputs/reports"],
    )

    assert json.loads(manifest.entries["inputs/context.json"].content) == {
        "runId": "run_1",
        "prompt": "design a binder",
    }
    assert manifest.entries["inputs/artifacts/target.cif"].content == b"data_target"
    assert manifest.entries["outputs/structures/.keep"].content == b""
    assert manifest.entries["outputs/reports/.keep"].content == b""


def test_build_agent_reports_missing_sandbox_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_imports():
        raise ImportError("No module named agents.extensions.sandbox")

    monkeypatch.setattr("julia_agent.agent._load_sandbox_imports", missing_imports)

    with pytest.raises(RuntimeError, match="Modal sandbox extension"):
        build_julia_agent()


def test_build_agent_and_run_config_use_lazy_sandbox_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = {}

    class FakeManifest:
        def __init__(self, **kwargs):
            self.entries = kwargs["entries"]

    class FakeFile:
        def __init__(self, **kwargs):
            self.content = kwargs["content"]
            self.is_dir = kwargs.get("is_dir", False)

    class FakeSandboxAgent:
        def __init__(self, **kwargs):
            created["agent"] = kwargs

    class FakeSandboxRunConfig:
        def __init__(self, **kwargs):
            created["sandbox"] = kwargs

    class FakeModalSandboxClient:
        def __init__(self, **kwargs):
            created["client"] = kwargs

    class FakeModalSandboxClientOptions:
        def __init__(self, **kwargs):
            created["options"] = kwargs

    class FakeRunConfig:
        def __init__(self, **kwargs):
            created["run_config"] = kwargs

    monkeypatch.setattr(
        "julia_agent.agent._load_sandbox_imports",
        lambda: {
            "Manifest": FakeManifest,
            "File": FakeFile,
            "SandboxAgent": FakeSandboxAgent,
            "SandboxRunConfig": FakeSandboxRunConfig,
            "ModalSandboxClient": FakeModalSandboxClient,
            "ModalSandboxClientOptions": FakeModalSandboxClientOptions,
            "RunConfig": FakeRunConfig,
        },
    )

    agent = build_julia_agent(model="gpt-test")
    run_config = build_sandbox_run_config(app_name="julia-agent-worker", timeout=123)

    assert agent is not None
    assert run_config is not None
    assert created["agent"]["name"] == "Julia"
    assert created["agent"]["model"] == "gpt-test"
    assert "concise" in created["agent"]["instructions"].lower()
    assert created["options"]["app_name"] == "julia-agent-worker"
    assert created["options"]["timeout"] == 123
    assert created["run_config"]["sandbox"] is not None


def test_openrouter_provider_preferences_default_ignores_siliconflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SiliconFlow's DeepSeek thinking endpoint rejects multi-turn tool calls
    # because the Agents SDK does not echo reasoning_content back. The default
    # ignore list must keep that provider out of the pool.
    for var in (
        "OPENROUTER_PROVIDER_ORDER",
        "OPENROUTER_PROVIDER_ONLY",
        "OPENROUTER_PROVIDER_IGNORE",
        "OPENROUTER_ALLOW_FALLBACKS",
        "OPENROUTER_REQUIRE_PARAMETERS",
    ):
        monkeypatch.delenv(var, raising=False)

    prefs = _openrouter_provider_preferences()

    assert prefs["ignore"] == list(JULIA_DEFAULT_OPENROUTER_PROVIDER_IGNORE)
    assert "SiliconFlow" in prefs["ignore"]


def test_openrouter_provider_preferences_env_overrides_default_ignore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_PROVIDER_IGNORE", "Foo, Bar")
    monkeypatch.delenv("OPENROUTER_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("OPENROUTER_PROVIDER_ONLY", raising=False)

    prefs = _openrouter_provider_preferences()

    assert prefs["ignore"] == ["Foo", "Bar"]
