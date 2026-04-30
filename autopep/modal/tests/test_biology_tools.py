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
        quality_scorers_base_url="https://quality.example/run",
        quality_scorers_api_key="quality-key",
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
    # New names take effect; the old aliases keep pointing at the same tool
    # so runner.py keeps working until the merge step.
    assert biology_tools.proteina_design.name == "proteina_design"
    assert callable(biology_tools.proteina_design.on_invoke_tool)
    assert (
        biology_tools.proteina_design.params_json_schema["properties"][
            "binder_length_min"
        ]["type"]
        == "integer"
    )
    assert (
        biology_tools.proteina_design.params_json_schema["properties"][
            "binder_length_max"
        ]["type"]
        == "integer"
    )
    assert (
        biology_tools.proteina_design.params_json_schema["properties"][
            "target_pdb_path"
        ]["type"]
        == "string"
    )

    assert biology_tools.chai_fold_complex.name == "chai_fold_complex"
    assert callable(biology_tools.chai_fold_complex.on_invoke_tool)
    assert (
        "candidate_ids"
        in biology_tools.chai_fold_complex.params_json_schema["properties"]
    )

    assert (
        biology_tools.score_candidate_interactions.name
        == "score_candidate_interactions"
    )
    assert callable(biology_tools.score_candidate_interactions.on_invoke_tool)
    assert "candidates" in biology_tools.score_candidate_interactions.params_json_schema[
        "properties"
    ]

    # Aliases share the same function_tool object so runner.py imports of
    # the old names keep working until the runner merge step lands.
    assert biology_tools.generate_binder_candidates is biology_tools.proteina_design
    assert biology_tools.fold_sequences_with_chai is biology_tools.chai_fold_complex


@pytest.mark.asyncio
async def test_proteina_design_reads_target_from_r2_and_passes_warm_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    target_pdb_path = "/workspace/runs/r1/inputs/target.pdb"
    warm_start_path = "/workspace/runs/r1/seeds/seed.pdb"
    warm_start_text = "WARM_START_PDB"

    fetched_keys: list[str] = []

    async def _fake_get(*, key: str, **_kwargs: Any) -> bytes:
        fetched_keys.append(key)
        if key.endswith("/seeds/seed.pdb"):
            return warm_start_text.encode("utf-8")
        return PDB_TEXT.encode("utf-8")

    monkeypatch.setattr(biology_tools, "r2_get_object", _fake_get)

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
            warm_start_structure: str | None = None,
            warm_start_filename: str | None = None,
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
                    "warm_start_structure": warm_start_structure,
                    "warm_start_filename": warm_start_filename,
                },
            )
            return response

    monkeypatch.setattr(biology_tools, "ProteinaClient", FakeProteinaClient)

    result = await biology_tools._proteina_design(
        target_pdb_path=target_pdb_path,
        hotspot_residues=["A:42"],
        binder_length_min=55,
        binder_length_max=88,
        warm_start_structure_path=warm_start_path,
    )

    # We requested both the target and the warm-start blob from R2 using
    # workspace-prefixed storage keys.
    assert fetched_keys == [
        "workspaces/w1/runs/r1/inputs/target.pdb",
        "workspaces/w1/runs/r1/seeds/seed.pdb",
    ]

    assert calls == [
        {
            "base_url": "https://proteina.example/run",
            "api_key": "proteina-key",
            "target_structure": PDB_TEXT,
            "target_filename": "target.pdb",
            # PDB has chains A (1 residue) and B (1 residue); first chain is A
            # → ``A1-1`` selector.
            "target_input": "A1-1",
            "hotspot_residues": ["A:42"],
            "binder_length": [55, 88],
            "warm_start_structure": warm_start_text,
            "warm_start_filename": "seed.pdb",
        },
    ]
    assert result["num_candidates"] == 1
    candidate = result["candidates"][0]
    assert candidate["sequence"] == "G"
    assert candidate["target_sequence"] == "A"
    assert candidate["chain_sequences"] == {"A": "A", "B": "G"}
    assert candidate["rank"] == 1


@pytest.mark.asyncio
async def test_chai_fold_complex_runs_one_complex_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    async def _fake_load(
        _url: str, *, workspace_id: str, candidate_ids: list[str],
    ) -> list[dict[str, Any]]:
        assert workspace_id == "w1"
        rows = {
            "cand-1": {
                "id": "cand-1",
                "sequence": "GG",
                "target_sequence": "AAAA",
            },
            "cand-2": {
                "id": "cand-2",
                "sequence": "WW",
                "target_sequence": "AAAA",
            },
        }
        return [rows[cid] for cid in candidate_ids if cid in rows]

    monkeypatch.setattr(biology_tools, "load_candidates_by_id", _fake_load)

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

    result = await biology_tools._chai_fold_complex(
        candidate_ids=["cand-1", "cand-2"],
        target_name="target",
    )

    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert sorted(c["candidate_id"] for c in result["candidates"]) == [
        "cand-1",
        "cand-2",
    ]
    assert all(c["ok"] for c in result["candidates"])
    # Both candidates resulted in their own Chai call. Order may vary because
    # gather() doesn't guarantee call order, so sort by fasta.
    fastas = sorted(call["fasta"] for call in calls)
    assert fastas == [
        ">protein|name=target\nAAAA\n>protein|name=candidate-cand-1\nGG\n",
        ">protein|name=target\nAAAA\n>protein|name=candidate-cand-2\nWW\n",
    ]


@pytest.mark.asyncio
async def test_chai_fold_complex_uses_explicit_target_sequence_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_run_context()
    _disable_persistence(monkeypatch)

    async def _fake_load(
        _url: str, *, workspace_id: str, candidate_ids: list[str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "cand-1",
                "sequence": "GG",
                # No stored target_sequence — caller must supply one.
                "target_sequence": None,
            },
        ]

    monkeypatch.setattr(biology_tools, "load_candidates_by_id", _fake_load)

    calls: list[dict[str, Any]] = []

    class FakeChaiClient:
        def __init__(self, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

        async def predict(
            self,
            fasta: str,
            num_diffn_samples: int = 1,
        ) -> dict[str, Any]:
            calls.append({"fasta": fasta})
            return {"cifs": ["prediction.cif"]}

    monkeypatch.setattr(biology_tools, "ChaiClient", FakeChaiClient)

    result = await biology_tools._chai_fold_complex(
        candidate_ids=["cand-1"],
        target_sequence=" aaaa ",
        target_name="target",
    )

    assert result["succeeded"] == 1
    assert calls == [
        {"fasta": ">protein|name=target\nAAAA\n>protein|name=candidate-cand-1\nGG\n"},
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
