from __future__ import annotations

from typing import Any

import pytest

from autopep_agent import biology_tools
from autopep_agent.run_context import ToolRunContext, set_tool_run_context
from autopep_agent.structure_utils import encode_structure_base64


def _install_test_run_context() -> ToolRunContext:
    """Install a fresh ``ToolRunContext`` for biology tools to read.

    Tests use this to provide URLs / API keys that the tool implementations
    need but the LLM never sees.
    """

    ctx = ToolRunContext(
        workspace_id="w1",
        run_id="r1",
        database_url="postgresql://test:test@db.example/autopep",
        proteina_base_url="https://proteina.example/run",
        proteina_api_key="proteina-key",
        chai_base_url="https://chai.example/run",
        chai_api_key="chai-key",
        scoring_base_url="https://scoring.example/run",
        scoring_api_key="scoring-key",
    )
    set_tool_run_context(ctx)
    return ctx


async def _stub_db_helper(*_args: Any, **_kwargs: Any) -> str:
    return "stub-id"


async def _stub_void_helper(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _stub_r2_put(*_args: Any, **_kwargs: Any) -> str:
    return "deadbeef" * 8


def _disable_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub all persistence calls so existing biology unit tests don't need DB."""

    monkeypatch.setattr(biology_tools, "create_model_inference", _stub_db_helper)
    monkeypatch.setattr(biology_tools, "complete_model_inference", _stub_void_helper)
    monkeypatch.setattr(biology_tools, "create_artifact", _stub_db_helper)
    monkeypatch.setattr(biology_tools, "create_candidate", _stub_db_helper)
    monkeypatch.setattr(
        biology_tools, "insert_candidate_scores", _stub_void_helper,
    )
    monkeypatch.setattr(
        biology_tools, "update_candidate_fold_artifact", _stub_void_helper,
    )
    monkeypatch.setattr(biology_tools, "r2_put_object", _stub_r2_put)

    class _FakeWriter:
        def __init__(self, _url: str) -> None:
            pass

        async def append_event(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(biology_tools, "EventWriter", _FakeWriter)
    monkeypatch.setattr(
        biology_tools,
        "_r2_config_from_env",
        lambda: {
            "bucket": "b",
            "account_id": "a",
            "access_key_id": "ak",
            "secret_access_key": "sk",
        },
    )


def _atom_line(serial: int, atom: str, residue: str, chain: str, number: int) -> str:
    return (
        f"ATOM  {serial:5d} {atom:<4} {residue:>3} {chain}{number:4d}"
        "      11.104  13.207  14.329  1.00 20.00           C"
    )


PDB_TEXT = "\n".join(
    [
        _atom_line(1, "N", "ALA", "A", 1),
        _atom_line(2, "CA", "ALA", "A", 1),
        _atom_line(3, "N", "GLY", "B", 2),
        _atom_line(4, "CA", "GLY", "B", 2),
    ],
)


def test_exported_biology_tools_are_agents_sdk_function_tools() -> None:
    assert biology_tools.generate_binder_candidates.name == "generate_binder_candidates"
    assert callable(biology_tools.generate_binder_candidates.on_invoke_tool)
    assert (
        biology_tools.generate_binder_candidates.params_json_schema["properties"][
            "binder_length_min"
        ]["type"]
        == "integer"
    )
    assert (
        biology_tools.generate_binder_candidates.params_json_schema["properties"][
            "binder_length_max"
        ]["type"]
        == "integer"
    )

    assert biology_tools.fold_sequences_with_chai.name == "fold_sequences_with_chai"
    assert callable(biology_tools.fold_sequences_with_chai.on_invoke_tool)
    assert "sequence_candidates" in biology_tools.fold_sequences_with_chai.params_json_schema[
        "properties"
    ]

    assert (
        biology_tools.score_candidate_interactions.name
        == "score_candidate_interactions"
    )
    assert callable(biology_tools.score_candidate_interactions.on_invoke_tool)
    assert "candidates" in biology_tools.score_candidate_interactions.params_json_schema[
        "properties"
    ]


@pytest.mark.asyncio
async def test_generate_binder_candidates_sends_length_range_and_extracts_chain_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    calls: list[dict[str, Any]] = []
    response = {"pdbs": [{"filename": "design-1.pdb", "pdb": PDB_TEXT}]}

    class FakeProteinaClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def design(
            self,
            *,
            target_structure: str,
            target_filename: str,
            target_input: str | None,
            hotspot_residues: list[str],
            binder_length: list[int],
        ) -> dict[str, Any]:
            calls.append(
                {
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "target_structure": target_structure,
                    "target_filename": target_filename,
                    "target_input": target_input,
                    "hotspot_residues": hotspot_residues,
                    "binder_length": binder_length,
                },
            )
            return response

    monkeypatch.setattr(biology_tools, "ProteinaClient", FakeProteinaClient)

    result = await biology_tools._generate_binder_candidates(
        target_structure="target-pdb",
        target_filename="target.pdb",
        target_input="A",
        hotspot_residues=["A:42"],
        binder_length_min=55,
        binder_length_max=88,
    )

    assert calls == [
        {
            "base_url": "https://proteina.example/run",
            "api_key": "proteina-key",
            "target_structure": "target-pdb",
            "target_filename": "target.pdb",
            "target_input": "A",
            "hotspot_residues": ["A:42"],
            "binder_length": [55, 88],
        },
    ]
    assert result["raw"] == response
    assert result["candidates"][0]["filename"] == "design-1.pdb"
    assert result["candidates"][0]["pdb"] == PDB_TEXT
    assert result["candidates"][0]["sequence"] == "G"
    assert result["candidates"][0]["target_sequence"] == "A"
    assert result["candidates"][0]["chain_sequences"] == {"A": "A", "B": "G"}
    assert result["candidates"][0]["rank"] == 1


@pytest.mark.asyncio
async def test_fold_sequences_with_chai_uses_candidate_fasta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    calls: list[dict[str, Any]] = []
    response = {"cifs": ["prediction.cif"]}

    class FakeChaiClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def predict(
            self,
            fasta: str,
            num_diffn_samples: int = 1,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "fasta": fasta,
                    "num_diffn_samples": num_diffn_samples,
                },
            )
            return response

    monkeypatch.setattr(biology_tools, "ChaiClient", FakeChaiClient)

    result = await biology_tools._fold_sequences_with_chai(
        sequence_candidates=[{"id": "candidate-1", "sequence": " acde "}],
    )

    assert result == response
    assert calls == [
        {
            "base_url": "https://chai.example/run",
            "api_key": "chai-key",
            "fasta": ">protein|name=candidate-1\nACDE\n",
            "num_diffn_samples": 1,
        },
    ]


@pytest.mark.asyncio
async def test_fold_sequences_with_chai_uses_target_binder_fasta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    calls: list[dict[str, Any]] = []
    response = {"cifs": ["prediction.cif"]}

    class FakeChaiClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def predict(
            self,
            fasta: str,
            num_diffn_samples: int = 1,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "fasta": fasta,
                    "num_diffn_samples": num_diffn_samples,
                },
            )
            return response

    monkeypatch.setattr(biology_tools, "ChaiClient", FakeChaiClient)

    result = await biology_tools._fold_sequences_with_chai(
        target_sequence=" aaaa ",
        target_name="target",
        sequence_candidates=[
            {
                "candidate_id": "db-candidate-1",
                "id": "candidate-1",
                "sequence": " gg ",
            },
        ],
    )

    assert result == {"results": [{"candidate_id": "db-candidate-1", "raw": response}]}
    assert calls == [
        {
            "base_url": "https://chai.example/run",
            "api_key": "chai-key",
            "fasta": ">protein|name=target\nAAAA\n>protein|name=candidate-1\nGG\n",
            "num_diffn_samples": 1,
        },
    ]


@pytest.mark.asyncio
async def test_score_candidate_interactions_sends_valid_scoring_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    calls: list[dict[str, Any]] = []
    response = {"aggregate_label": "high-confidence"}

    class FakeScoringClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def score_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append(
                {
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "items": items,
                },
            )
            return response

    monkeypatch.setattr(biology_tools, "ScoringClient", FakeScoringClient)

    result = await biology_tools._score_candidate_interactions(
        target_name="target",
        target_sequence="AAAA",
        candidates=[
            {
                "id": "candidate-1",
                "sequence": "GG",
                "pdb": PDB_TEXT,
            },
        ],
    )

    assert result == response
    assert calls == [
        {
            "base_url": "https://scoring.example/run",
            "api_key": "scoring-key",
            "items": [
                {
                    "id": "candidate-1",
                    "protein_a": {"name": "target", "sequence": "AAAA"},
                    "protein_b": {"name": "candidate-1", "sequence": "GG"},
                    "structure": {
                        "format": "pdb",
                        "content_base64": encode_structure_base64(PDB_TEXT),
                        "chain_a": "A",
                        "chain_b": "B",
                    },
                },
            ],
        },
    ]
