from pathlib import Path

import pytest

from julia_agent.artifacts import artifact_paths_from_tool_result, scan_allowed_outputs
from julia_agent.tools import (
    output_roots,
    relative_to_workspace,
    safe_workspace_path,
    tool_path,
)


def test_safe_workspace_path_keeps_paths_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    resolved = safe_workspace_path(workspace, "inputs/target.cif")

    assert resolved == workspace.resolve() / "inputs" / "target.cif"


@pytest.mark.parametrize("unsafe", ["../outside.txt", "/tmp/outside.txt", "outputs/../../x"])
def test_safe_workspace_path_rejects_unsafe_paths(tmp_path: Path, unsafe: str) -> None:
    workspace = tmp_path / "workspace"

    with pytest.raises(ValueError, match="inside workspace"):
        safe_workspace_path(workspace, unsafe)


def test_tool_path_targets_expected_output_directories(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    assert relative_to_workspace(tool_path(workspace, "literature", "pmc.json"), workspace) == (
        "outputs/literature/pmc.json"
    )
    assert relative_to_workspace(tool_path(workspace, "pdb", "1ABC.cif"), workspace) == (
        "outputs/pdb/1ABC.cif"
    )
    assert relative_to_workspace(tool_path(workspace, "proteina_runs", "run/response.json"), workspace) == (
        "outputs/proteina_runs/run/response.json"
    )
    assert relative_to_workspace(tool_path(workspace, "chai_runs", "run/input.fasta"), workspace) == (
        "outputs/chai_runs/run/input.fasta"
    )
    assert relative_to_workspace(tool_path(workspace, "scoring_runs", "run/summary.json"), workspace) == (
        "outputs/scoring_runs/run/summary.json"
    )
    assert relative_to_workspace(tool_path(workspace, "tool_logs", "run.stdout.txt"), workspace) == (
        "outputs/tool_logs/run.stdout.txt"
    )


def test_artifact_extraction_from_representative_tool_results() -> None:
    results = [
        (
            "literature_search",
            {"sandbox_path": "outputs/literature/pmc.json"},
            [Path("outputs/literature/pmc.json")],
        ),
        (
            "search_pdb",
            {"sandbox_path": "outputs/pdb/search.json"},
            [Path("outputs/pdb/search.json")],
        ),
        (
            "fetch_pdb",
            {"sandbox_path": "outputs/pdb/1ABC.cif"},
            [Path("outputs/pdb/1ABC.cif")],
        ),
        (
            "run_proteina",
            {
                "response_path": "outputs/proteina_runs/r/response.json",
                "candidates": [{"sandbox_path": "outputs/proteina_runs/r/candidate_1.pdb"}],
            },
            [
                Path("outputs/proteina_runs/r/response.json"),
                Path("outputs/proteina_runs/r/candidate_1.pdb"),
            ],
        ),
        (
            "run_chai",
            {
                "input_fasta_path": "outputs/chai_runs/r/input.fasta",
                "response_path": "outputs/chai_runs/r/response.json",
                "structures": [
                    {
                        "cif_path": "outputs/chai_runs/r/rank_1.cif",
                        "pdb_path": "outputs/chai_runs/r/rank_1.pdb",
                    }
                ],
            },
            [
                Path("outputs/chai_runs/r/input.fasta"),
                Path("outputs/chai_runs/r/response.json"),
                Path("outputs/chai_runs/r/rank_1.cif"),
                Path("outputs/chai_runs/r/rank_1.pdb"),
            ],
        ),
        (
            "run_scorers",
            {
                "interaction_response_path": "outputs/scoring_runs/r/interaction_response.json",
                "quality_response_path": "outputs/scoring_runs/r/quality_response.json",
                "summary_path": "outputs/scoring_runs/r/summary.json",
            },
            [
                Path("outputs/scoring_runs/r/interaction_response.json"),
                Path("outputs/scoring_runs/r/quality_response.json"),
                Path("outputs/scoring_runs/r/summary.json"),
            ],
        ),
    ]

    for tool_name, result, expected in results:
        assert artifact_paths_from_tool_result(tool_name, result) == expected


def test_allowed_final_scan_ignores_inputs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    input_file = workspace / "inputs" / "target.cif"
    output_file = workspace / "outputs" / "pdb" / "target.cif"
    input_file.parent.mkdir(parents=True)
    output_file.parent.mkdir(parents=True)
    input_file.write_text("input", encoding="utf-8")
    output_file.write_text("output", encoding="utf-8")

    assert scan_allowed_outputs(output_roots(workspace)) == [output_file]
