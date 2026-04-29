from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents import function_tool

from autopep_agent.endpoint_clients import ChaiClient, ProteinaClient, ScoringClient
from autopep_agent.structure_utils import (
    build_fasta,
    encode_structure_base64,
    extract_pdb_sequences,
)


async def _generate_binder_candidates(
    target_structure: str,
    target_filename: str,
    target_input: str | None,
    hotspot_residues: list[str],
    binder_length_min: int,
    binder_length_max: int,
    proteina_base_url: str,
    proteina_api_key: str,
) -> dict[str, Any]:
    """Generate binder designs and extract binder-chain sequences.

    Args:
        target_structure: Target structure text accepted by Proteina.
        target_filename: Filename for the target structure.
        target_input: Optional target input selector.
        hotspot_residues: Target residues to bias the design.
        binder_length_min: Minimum binder length.
        binder_length_max: Maximum binder length.
        proteina_base_url: Proteina endpoint base URL.
        proteina_api_key: Proteina endpoint API key.
    """

    client = ProteinaClient(proteina_base_url, proteina_api_key)
    response = await client.design(
        target_structure=target_structure,
        target_filename=target_filename,
        target_input=target_input,
        hotspot_residues=list(hotspot_residues),
        binder_length=[binder_length_min, binder_length_max],
    )

    candidates = []
    for rank, pdb_record in enumerate(_extract_pdb_records(response), start=1):
        sequences = extract_pdb_sequences(pdb_record["pdb"])
        sequence = sequences.get("B") or next(iter(sequences.values()), "")
        candidates.append(
            {
                "rank": rank,
                "filename": pdb_record["filename"],
                "pdb": pdb_record["pdb"],
                "sequence": sequence,
            },
        )

    return {"raw": response, "candidates": candidates}


async def _fold_sequences_with_chai(
    sequence_candidates: list[dict[str, Any]],
    chai_base_url: str,
    chai_api_key: str,
) -> Any:
    """Fold sequence candidates with Chai.

    Args:
        sequence_candidates: Candidate dictionaries with id and sequence.
        chai_base_url: Chai endpoint base URL.
        chai_api_key: Chai endpoint API key.
    """

    fasta = build_fasta(sequence_candidates)
    client = ChaiClient(chai_base_url, chai_api_key)
    return await client.predict(fasta=fasta, num_diffn_samples=1)


async def _score_candidate_interactions(
    target_name: str,
    target_sequence: str,
    candidates: list[dict[str, Any]],
    scoring_base_url: str,
    scoring_api_key: str,
) -> Any:
    """Score target-candidate interactions.

    Args:
        target_name: Name for protein A.
        target_sequence: Sequence for protein A.
        candidates: Binder candidate dictionaries.
        scoring_base_url: Scoring endpoint base URL.
        scoring_api_key: Scoring endpoint API key.
    """

    items = [
        _build_scoring_item(target_name, target_sequence, candidate, index)
        for index, candidate in enumerate(candidates, start=1)
    ]
    client = ScoringClient(scoring_base_url, scoring_api_key)
    return await client.score_batch(items)


generate_binder_candidates = function_tool(
    _generate_binder_candidates,
    name_override="generate_binder_candidates",
    strict_mode=False,
)
fold_sequences_with_chai = function_tool(
    _fold_sequences_with_chai,
    name_override="fold_sequences_with_chai",
    strict_mode=False,
)
score_candidate_interactions = function_tool(
    _score_candidate_interactions,
    name_override="score_candidate_interactions",
    strict_mode=False,
)


def _extract_pdb_records(response: Any) -> list[dict[str, str]]:
    records = _response_records(response)
    pdb_records: list[dict[str, str]] = []

    for index, record in enumerate(records, start=1):
        filename = f"candidate-{index}.pdb"
        pdb_text: str | None = None

        if isinstance(record, str):
            pdb_text = record
        elif isinstance(record, Mapping):
            filename = str(
                record.get("filename")
                or record.get("name")
                or record.get("path")
                or filename,
            )
            raw_pdb = (
                record.get("pdb")
                or record.get("pdb_text")
                or record.get("structure")
                or record.get("content")
            )
            if isinstance(raw_pdb, str):
                pdb_text = raw_pdb

        if pdb_text is not None:
            pdb_records.append({"filename": filename, "pdb": pdb_text})

    return pdb_records


def _response_records(response: Any) -> list[Any]:
    if isinstance(response, Mapping):
        for key in ("pdbs", "pdb", "structures", "results", "outputs"):
            value = response.get(key)
            if value is None:
                continue
            return value if isinstance(value, list) else [value]
    if isinstance(response, list):
        return response
    return []


def _build_scoring_item(
    target_name: str,
    target_sequence: str,
    candidate: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    candidate_id = _candidate_id(candidate, index)
    item: dict[str, Any] = {
        "id": candidate_id,
        "protein_a": {"name": target_name, "sequence": target_sequence},
        "protein_b": {"name": candidate_id},
    }

    sequence = candidate.get("sequence")
    if sequence is not None:
        item["protein_b"]["sequence"] = str(sequence).strip().upper()

    structure_text = _candidate_structure_text(candidate)
    if structure_text:
        item["structure"] = {
            "format": "pdb",
            "content_base64": encode_structure_base64(structure_text),
            "chain_a": "A",
            "chain_b": "B",
        }

    return item


def _candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    for key in ("id", "filename", "name"):
        value = candidate.get(key)
        if value:
            return str(value)
    rank = candidate.get("rank")
    if rank:
        return f"candidate-{rank}"
    return f"candidate-{index}"


def _candidate_structure_text(candidate: Mapping[str, Any]) -> str | None:
    for key in ("pdb", "structure", "structure_text"):
        value = candidate.get(key)
        if isinstance(value, str):
            return value
    return None
