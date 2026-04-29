import base64

import pytest
from pydantic import ValidationError

from protein_scoring_server.scorers.schemas import ScoreBatchRequest


PDB_TEXT = """\
ATOM      1  N   ALA A   1      11.104  13.207   9.447  1.00 20.00           N
ATOM      2  CA  ALA A   1      12.560  13.207   9.447  1.00 20.00           C
TER
ATOM      3  N   GLY B   1      15.104  13.207   9.447  1.00 20.00           N
ATOM      4  CA  GLY B   1      16.560  13.207   9.447  1.00 20.00           C
TER
END
"""


def structure_payload() -> dict:
    return {
        "format": "pdb",
        "content_base64": base64.b64encode(PDB_TEXT.encode("utf-8")).decode("ascii"),
        "chain_a": "A",
        "chain_b": "B",
    }


def item(item_id: str) -> dict:
    return {
        "id": item_id,
        "protein_a": {"name": f"{item_id}_a", "sequence": "ACDEFGHIK"},
        "protein_b": {"name": f"{item_id}_b", "sequence": "LMNPQRSTV"},
        "structure": structure_payload(),
    }


def test_schema_accepts_valid_batch_of_five_items() -> None:
    request = ScoreBatchRequest.model_validate(
        {
            "items": [item(f"pair_{index}") for index in range(5)],
            "options": {"run_dscript": True, "run_prodigy": True},
        }
    )

    assert [entry.id for entry in request.items] == [
        "pair_0",
        "pair_1",
        "pair_2",
        "pair_3",
        "pair_4",
    ]
    assert request.items[0].protein_a.sequence == "ACDEFGHIK"


def test_schema_normalizes_sequence_whitespace_and_case() -> None:
    request = ScoreBatchRequest.model_validate(
        {
            "items": [
                {
                    **item("pair_001"),
                    "protein_a": {"name": "a", "sequence": " acd efg\nhik "},
                }
            ]
        }
    )

    assert request.items[0].protein_a.sequence == "ACDEFGHIK"


def test_schema_rejects_duplicate_item_ids() -> None:
    with pytest.raises(ValidationError):
        ScoreBatchRequest.model_validate({"items": [item("same"), item("same")]})


def test_schema_rejects_invalid_amino_acid_codes() -> None:
    payload = item("bad_sequence")
    payload["protein_a"]["sequence"] = "ACDJO"

    with pytest.raises(ValidationError):
        ScoreBatchRequest.model_validate({"items": [payload]})
