import subprocess

from protein_scoring_server.scorers.prodigy_scorer import ProdigyScorer


PDB_TEXT = """\
ATOM      1  N   ALA A   1      11.104  13.207   9.447  1.00 20.00           N
ATOM      2  CA  ALA A   1      12.560  13.207   9.447  1.00 20.00           C
TER
ATOM      3  N   GLY B   1      15.104  13.207   9.447  1.00 20.00           N
ATOM      4  CA  GLY B   1      16.560  13.207   9.447  1.00 20.00           C
TER
END
"""


class CapturingProdigyScorer(ProdigyScorer):
    def __init__(self) -> None:
        super().__init__()
        self._loaded = True
        self._available = True
        self.command_seen: list[str] | None = None

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.command_seen = command
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Predicted binding affinity (kcal.mol-1): -8.4\n",
            stderr="",
        )


def test_prodigy_input_path_precedes_selection_arguments(tmp_path) -> None:
    structure_path = tmp_path / "complex.pdb"
    structure_path.write_text(PDB_TEXT, encoding="utf-8")
    scorer = CapturingProdigyScorer()

    result = scorer.score_structure(
        "pair_001",
        structure_path,
        chain_a="A",
        chain_b="B",
    )

    assert result.available is True
    assert scorer.command_seen is not None
    assert scorer.command_seen.index(str(structure_path)) < scorer.command_seen.index(
        "--selection"
    )
    assert scorer.command_seen[-2:] == ["A", "B"]
