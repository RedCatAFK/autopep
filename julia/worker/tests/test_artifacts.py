from pathlib import Path

from julia_agent.artifacts import (
    artifact_paths_from_tool_result,
    classify_artifact_kind,
    generate_r2_key,
    is_allowed_output_path,
    scan_allowed_outputs,
)


def test_allowed_output_path_requires_descendant() -> None:
    root = Path("/tmp/work/out")

    assert is_allowed_output_path(root / "report.json", [root])
    assert not is_allowed_output_path(Path("/tmp/work/other/report.json"), [root])
    assert not is_allowed_output_path(Path("/tmp/work/outside"), [root / "nested"])


def test_classify_artifact_kind_from_extension_and_name() -> None:
    assert classify_artifact_kind(Path("papers.json")) == "literature"
    assert classify_artifact_kind(Path("model.cif")) == "structure"
    assert classify_artifact_kind(Path("metrics.csv")) == "table"
    assert classify_artifact_kind(Path("notes.txt")) == "text"
    assert classify_artifact_kind(Path("plot.png")) == "image"
    assert classify_artifact_kind(Path("unknown.bin")) == "file"


def test_generate_r2_key_is_stable_and_namespaced() -> None:
    key = generate_r2_key("run_123", Path("/tmp/work/out/model.cif"))

    assert key == "runs/run_123/artifacts/model.cif"


def test_scan_allowed_outputs_returns_files_only(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    nested = allowed / "nested"
    nested.mkdir(parents=True)
    expected = allowed / "result.json"
    nested_expected = nested / "model.pdb"
    expected.write_text("{}", encoding="utf-8")
    nested_expected.write_text("ATOM", encoding="utf-8")
    (tmp_path / "ignored.json").write_text("{}", encoding="utf-8")

    assert scan_allowed_outputs([allowed]) == [expected, nested_expected]


def test_artifact_paths_from_tool_result_known_tool_fields() -> None:
    result = {
        "path": "/tmp/search.json",
        "output_path": "/tmp/proteina.cif",
        "artifact_path": "/tmp/chai.zip",
        "artifact_paths": ["/tmp/score.csv"],
        "files": [{"path": "/tmp/fetch.pdf"}, {"url": "https://example.test/nope"}],
    }

    assert artifact_paths_from_tool_result("search_pubmed_literature", result) == [
        Path("/tmp/search.json"),
        Path("/tmp/proteina.cif"),
        Path("/tmp/chai.zip"),
        Path("/tmp/score.csv"),
        Path("/tmp/fetch.pdf"),
    ]
    assert artifact_paths_from_tool_result("unknown_tool", result) == []
