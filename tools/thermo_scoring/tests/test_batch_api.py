import base64
import json

from fastapi.testclient import TestClient

from protein_scoring_server.scorers import MockDScriptScorer, MockProdigyScorer
from protein_scoring_server.server import BatchScoringService, create_app


PDB_TEXT = """\
ATOM      1  N   ALA A   1      11.104  13.207   9.447  1.00 20.00           N
ATOM      2  CA  ALA A   1      12.560  13.207   9.447  1.00 20.00           C
TER
ATOM      3  N   GLY B   1      15.104  13.207   9.447  1.00 20.00           N
ATOM      4  CA  GLY B   1      16.560  13.207   9.447  1.00 20.00           C
TER
END
"""


def structure_payload(content_base64: str | None = None) -> dict:
    return {
        "format": "pdb",
        "content_base64": content_base64
        or base64.b64encode(PDB_TEXT.encode("utf-8")).decode("ascii"),
        "chain_a": "A",
        "chain_b": "B",
    }


def item(
    item_id: str,
    *,
    include_sequence_a: bool = True,
    include_sequence_b: bool = True,
    include_structure: bool = True,
    structure_content_base64: str | None = None,
) -> dict:
    protein_a = {"name": f"{item_id}_a"}
    protein_b = {"name": f"{item_id}_b"}
    if include_sequence_a:
        protein_a["sequence"] = "ACDEFGHIK"
    if include_sequence_b:
        protein_b["sequence"] = "LMNPQRSTV"

    payload = {
        "id": item_id,
        "protein_a": protein_a,
        "protein_b": protein_b,
    }
    if include_structure:
        payload["structure"] = structure_payload(structure_content_base64)
    return payload


def client(
    *,
    dscript_scores: dict[str, float] | None = None,
    prodigy_scores: dict[str, float] | None = None,
) -> TestClient:
    service = BatchScoringService(
        dscript_scorer=MockDScriptScorer(score_by_id=dscript_scores),
        prodigy_scorer=MockProdigyScorer(delta_g_by_id=prodigy_scores),
    )
    test_client = TestClient(create_app(service=service, load_on_startup=False))
    test_client.headers.update({"x-api-key": "password123"})
    return test_client


def test_api_key_is_required() -> None:
    service = BatchScoringService(
        dscript_scorer=MockDScriptScorer(),
        prodigy_scorer=MockProdigyScorer(),
    )
    unauthorized_client = TestClient(create_app(service=service, load_on_startup=False))

    response = unauthorized_client.get("/health")

    assert response.status_code == 401


def test_response_preserves_item_ids_and_ordering() -> None:
    ids = ["pair_3", "pair_1", "pair_4", "pair_0", "pair_2"]
    response = client().post(
        "/score_batch",
        json={"items": [item(item_id) for item_id in ids]},
    )

    assert response.status_code == 200
    body = response.json()
    assert [result["id"] for result in body["results"]] == ids
    assert body["batch_summary"] == {
        "submitted": 5,
        "succeeded": 5,
        "partial": 0,
        "failed": 0,
    }


def test_missing_structure_returns_dscript_and_prodigy_unavailable() -> None:
    response = client().post(
        "/score_batch",
        json={"items": [item("sequence_only", include_structure=False)]},
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "partial"
    assert result["scores"]["dscript"]["available"] is True
    assert result["scores"]["prodigy"]["available"] is False
    assert "prodigy:" in result["errors"][0]


def test_missing_sequence_is_extracted_from_structure_when_possible() -> None:
    response = client().post(
        "/score_batch",
        json={"items": [item("structure_only", include_sequence_a=False)]},
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "ok"
    assert result["scores"]["dscript"]["available"] is True
    assert result["scores"]["prodigy"]["available"] is True
    assert any("extracted sequence from structure chain A" in warning for warning in result["warnings"])


def test_missing_sequence_without_structure_still_returns_dscript_unavailable() -> None:
    response = client().post(
        "/score_batch",
        json={
            "items": [
                item(
                    "no_sequence_no_structure",
                    include_sequence_a=False,
                    include_structure=False,
                )
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["scores"]["dscript"]["available"] is False
    assert result["scores"]["prodigy"]["available"] is False


def test_invalid_base64_is_reported_as_item_level_prodigy_error() -> None:
    response = client().post(
        "/score_batch",
        json={
            "items": [
                item(
                    "bad_structure",
                    structure_content_base64="not-base64",
                )
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "partial"
    assert result["scores"]["dscript"]["available"] is True
    assert result["scores"]["prodigy"]["available"] is False
    assert any("base64" in error for error in result["errors"])


def test_aggregate_labels_are_computed_from_mock_scores() -> None:
    response = client(
        dscript_scores={
            "likely": 0.85,
            "possible": 0.55,
            "unlikely": 0.2,
        },
        prodigy_scores={
            "likely": -8.0,
            "possible": -4.0,
            "unlikely": -3.0,
        },
    ).post(
        "/score_batch",
        json={
            "items": [
                item("likely"),
                item("possible"),
                item("unlikely"),
            ]
        },
    )

    assert response.status_code == 200
    labels = {
        result["id"]: result["aggregate"]["label"]
        for result in response.json()["results"]
    }
    assert labels == {
        "likely": "likely_binder",
        "possible": "possible_binder",
        "unlikely": "unlikely_binder",
    }


def test_missing_chain_ids_are_inferred_from_structure() -> None:
    payload = item("infer_chains", include_sequence_a=False, include_sequence_b=False)
    payload["structure"].pop("chain_a")
    payload["structure"].pop("chain_b")

    response = client().post("/score_batch", json={"items": [payload]})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "ok"
    assert result["scores"]["dscript"]["available"] is True
    assert result["scores"]["prodigy"]["available"] is True
    assert any("inferred A and B" in warning for warning in result["warnings"])


def test_multipart_upload_scores_pdb_without_embedded_base64_or_sequences() -> None:
    payload = {
        "items": [
            {
                "id": "uploaded_pair",
                "protein_a": {"name": "uploaded_a"},
                "protein_b": {"name": "uploaded_b"},
                "structure": {"chain_a": "A", "chain_b": "B"},
            }
        ]
    }

    response = client().post(
        "/score_batch_upload",
        data={"payload": json.dumps(payload)},
        files={
            "uploaded_pair": (
                "uploaded_pair.pdb",
                PDB_TEXT.encode("utf-8"),
                "chemical/x-pdb",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["id"] == "uploaded_pair"
    assert result["status"] == "ok"
    assert result["scores"]["dscript"]["available"] is True
    assert result["scores"]["prodigy"]["available"] is True
    assert any("protein_a.sequence was missing" in warning for warning in result["warnings"])
