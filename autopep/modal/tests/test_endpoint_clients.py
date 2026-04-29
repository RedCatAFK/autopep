from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from autopep_agent.endpoint_clients import ChaiClient, ProteinaClient, ScoringClient


def _request_json(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content.decode("utf-8"))


@pytest.mark.asyncio
@respx.mock
async def test_proteina_design_posts_target_payload_with_api_key() -> None:
    route = respx.post("https://proteina.example/run/design").mock(
        return_value=httpx.Response(200, json={"pdbs": ["designed-model.pdb"]}),
    )
    client = ProteinaClient("https://proteina.example/run/", "proteina-key")

    result = await client.design(
        target_structure="data_target",
        target_filename="target.cif",
        target_input="A",
        hotspot_residues=["A:42", "A:73"],
        binder_length=[60, 120],
    )

    assert result["pdbs"] == ["designed-model.pdb"]
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "proteina-key"
    assert request.headers["content-type"] == "application/json"
    assert _request_json(request) == {
        "action": "design-cif",
        "target": {
            "structure": "data_target",
            "filename": "target.cif",
            "target_input": "A",
            "hotspot_residues": ["A:42", "A:73"],
            "binder_length": [60, 120],
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_chai_predict_posts_fasta_and_sampling_options() -> None:
    route = respx.post("https://chai.example/run/predict").mock(
        return_value=httpx.Response(
            200,
            json={"cifs": ["prediction.cif"], "mean_plddt": 88.4},
        ),
    )
    client = ChaiClient("https://chai.example/run/", "chai-key")

    result = await client.predict(">protein_a\nACDE\n>protein_b\nFGHI", num_diffn_samples=4)

    assert result["cifs"] == ["prediction.cif"]
    assert result["mean_plddt"] == 88.4
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "chai-key"
    assert request.headers["content-type"] == "application/json"
    assert _request_json(request) == {
        "fasta": ">protein_a\nACDE\n>protein_b\nFGHI",
        "num_trunk_recycles": 3,
        "num_diffn_timesteps": 200,
        "num_diffn_samples": 4,
        "seed": 42,
        "include_pdb": False,
        "include_viewer_html": False,
    }


@pytest.mark.asyncio
@respx.mock
async def test_scoring_score_batch_posts_items_options_and_api_key() -> None:
    route = respx.post("https://scoring.example/run/score_batch").mock(
        return_value=httpx.Response(200, json={"aggregate_label": "high-confidence"}),
    )
    client = ScoringClient("https://scoring.example/run/", "scoring-key")
    items = [
        {
            "id": "pair-1",
            "protein_a": {"name": "3CLpro", "sequence": "MSTNPKPQR"},
            "protein_b": {"name": "binder-1", "sequence": "GGHAA"},
            "structure": {
                "format": "cif",
                "content_base64": "Q0lGX0RBVEE=",
                "chain_a": "A",
                "chain_b": "B",
            },
        },
        {
            "id": "pair-2",
            "protein_a": {"name": "target", "sequence": "ACDE"},
            "protein_b": {"name": "binder-2", "sequence": "FGHI"},
        },
    ]

    result = await client.score_batch(items)

    assert result["aggregate_label"] == "high-confidence"
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "scoring-key"
    assert request.headers["content-type"] == "application/json"
    assert _request_json(request) == {
        "items": items,
        "options": {
            "run_dscript": True,
            "run_prodigy": True,
            "temperature_celsius": 25.0,
            "fail_fast": False,
        },
    }
