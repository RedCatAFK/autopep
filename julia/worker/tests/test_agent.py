import json
from pathlib import Path

import pytest

from julia_agent.agent import (
    JULIA_AGENT_INSTRUCTIONS,
    build_julia_agent,
    build_manifest,
    build_sandbox_run_config,
)


def test_agent_instructions_cover_julia_runtime_requirements() -> None:
    instructions = JULIA_AGENT_INSTRUCTIONS.lower()

    assert "general chat" in instructions
    assert "autopep2" in instructions
    assert "single-pass" in instructions
    assert "warm start" in instructions
    assert "cif" in instructions
    assert "mmcif" in instructions
    assert "concise" in instructions
    assert "wet-lab validation" in instructions
    assert "therapeutic readiness" in instructions


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
