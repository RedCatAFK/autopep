from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from autopep_agent.biology_tools import (
    _fold_sequences_with_chai,
    _generate_binder_candidates,
    _score_candidate_interactions,
)
from autopep_agent.config import WorkerConfig
from autopep_agent.db import create_artifact
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import put_object as r2_put_object
from autopep_agent.structure_utils import extract_pdb_sequences


TARGET_PDB_ID = "6LU7"
TARGET_CHAIN_ID = "A"
TARGET_NAME = "SARS-CoV-2 3CL-protease 6LU7 chain A"
TARGET_PDB_URL = f"https://files.rcsb.org/download/{TARGET_PDB_ID}.pdb"
PDB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
HOTSPOT_RESIDUES = ["A41", "A145", "A163", "A166", "A189"]
BINDER_LENGTH_MIN = 60
BINDER_LENGTH_MAX = 90
MAX_CANDIDATES_TO_FOLD_AND_SCORE = 2


DEMO_RECIPE_NAME = "One-loop 3CL-protease binder demo"
DEMO_RECIPE_BODY = """\
When the user asks to generate a protein binder for 3CL-protease:
1. Search preprint/literature evidence for SARS-CoV-2 Mpro / 3CLpro context.
2. Run a filtered PDB search for SARS-CoV-2 3C-like proteinase structures.
3. Select a high-confidence experimental target structure, defaulting to 6LU7 chain A when appropriate.
4. Call Proteina-Complexa to generate binder candidates.
5. Fold generated candidates with Chai-1.
6. Score target-candidate interactions with the protein interaction scoring endpoint.
7. Pick the strongest candidate for the MVP and stop after this one loop.
"""


async def execute_demo_one_loop(
    *,
    config: WorkerConfig,
    database_url: str,
    run_id: str,
    workspace_id: str,
    writer: EventWriter,
) -> dict[str, Any]:
    """Run the MVP backend demo loop for 3CL-protease binder design."""

    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_started",
        title="Search literature",
        summary="Searching preprints and literature for SARS-CoV-2 3CL-protease context.",
        display={"source": "Europe PMC", "query": _literature_query()},
    )
    literature = await _search_literature()
    literature_artifact_id = await _persist_json_artifact(
        config=config,
        database_url=database_url,
        run_id=run_id,
        workspace_id=workspace_id,
        kind="literature_snapshot",
        name="3cl-protease-literature.json",
        payload=literature,
    )
    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_completed",
        title="Literature evidence captured",
        summary=f"Captured {len(literature.get('results', []))} evidence records.",
        display={
            "artifactId": literature_artifact_id,
            "hitCount": literature.get("hitCount"),
        },
    )

    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_started",
        title="Search PDB",
        summary="Searching RCSB for filtered SARS-CoV-2 3C-like proteinase structures.",
        display={"source": "RCSB", "target": TARGET_NAME},
    )
    pdb_search = await _search_pdb()
    pdb_artifact_id = await _persist_json_artifact(
        config=config,
        database_url=database_url,
        run_id=run_id,
        workspace_id=workspace_id,
        kind="pdb_metadata",
        name="3cl-protease-pdb-search.json",
        payload=pdb_search,
    )
    selected_pdb_id = _select_pdb_id(pdb_search)
    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_completed",
        title="PDB target selected",
        summary=f"Selected {selected_pdb_id} chain {TARGET_CHAIN_ID}.",
        display={
            "artifactId": pdb_artifact_id,
            "candidateIds": [entry["identifier"] for entry in pdb_search["results"][:8]],
            "selectedPdbId": selected_pdb_id,
        },
    )

    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_started",
        title="Prepare target structure",
        summary=f"Downloading {selected_pdb_id} from RCSB.",
        display={"pdbId": selected_pdb_id, "url": _pdb_download_url(selected_pdb_id)},
    )
    target_pdb = await _fetch_target_pdb(selected_pdb_id)
    target_sequence = _target_sequence(target_pdb)
    target_input = _target_input_for_sequence(target_sequence)
    target_artifact_id = await _persist_target_artifact(
        config=config,
        database_url=database_url,
        run_id=run_id,
        workspace_id=workspace_id,
        pdb_id=selected_pdb_id,
        target_pdb=target_pdb,
    )
    await writer.append_event(
        run_id=run_id,
        event_type="tool_call_completed",
        title="Target structure ready",
        summary=f"Prepared {selected_pdb_id} chain {TARGET_CHAIN_ID}.",
        display={
            "artifactId": target_artifact_id,
            "chainId": TARGET_CHAIN_ID,
            "sequenceLength": len(target_sequence),
            "targetInput": target_input,
        },
    )

    generated = await _generate_binder_candidates(
        target_structure=target_pdb,
        target_filename=f"{selected_pdb_id}.pdb",
        target_input=target_input,
        hotspot_residues=HOTSPOT_RESIDUES,
        binder_length_min=BINDER_LENGTH_MIN,
        binder_length_max=BINDER_LENGTH_MAX,
    )
    candidates = [
        candidate
        for candidate in generated.get("candidates", [])
        if candidate.get("sequence") and candidate.get("candidate_id")
    ][:MAX_CANDIDATES_TO_FOLD_AND_SCORE]
    if not candidates:
        raise RuntimeError("Proteina did not return a persisted candidate with sequence.")

    await _fold_sequences_with_chai(
        sequence_candidates=[
            {
                "candidate_id": candidate["candidate_id"],
                "id": _candidate_score_id(candidate),
                "sequence": candidate["sequence"],
            }
            for candidate in candidates
        ],
    )

    score_response = await _score_candidate_interactions(
        target_name=TARGET_NAME,
        target_sequence=target_sequence,
        candidates=[
            {
                "candidate_id": candidate["candidate_id"],
                "id": _candidate_score_id(candidate),
                "pdb": candidate["pdb"],
                "sequence": candidate["sequence"],
            }
            for candidate in candidates
        ],
    )
    best = _best_candidate_from_scores(score_response, candidates)

    await writer.append_event(
        run_id=run_id,
        event_type="assistant_message_completed",
        title="MVP loop complete",
        summary=(
            f"Generated, folded, scored, and selected {best['label']} "
            "for the one-loop 3CL-protease binder demo."
        ),
        display={
            "candidateCount": len(candidates),
            "literatureArtifactId": literature_artifact_id,
            "pdbSearchArtifactId": pdb_artifact_id,
            "selectedCandidateId": best["candidate_id"],
            "targetArtifactId": target_artifact_id,
        },
        raw={"best": best, "scoreResponse": score_response},
    )
    return {
        "best": best,
        "candidate_count": len(candidates),
        "target_artifact_id": target_artifact_id,
        "target_sequence_length": len(target_sequence),
    }


def _literature_query() -> str:
    return (
        '("SARS-CoV-2" OR COVID-19) AND '
        '("3CL protease" OR Mpro OR "main protease") AND '
        '(SRC:PPR OR PUB_TYPE:"preprint")'
    )


async def _search_literature() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            EUROPE_PMC_SEARCH_URL,
            params={
                "format": "json",
                "pageSize": 5,
                "query": _literature_query(),
                "resultType": "core",
            },
        )
    response.raise_for_status()
    payload = response.json()
    records = payload.get("resultList", {}).get("result", [])
    return {
        "hitCount": payload.get("hitCount"),
        "query": _literature_query(),
        "results": [
            {
                "doi": record.get("doi"),
                "id": record.get("id"),
                "source": record.get("source"),
                "title": record.get("title"),
                "year": record.get("pubYear"),
            }
            for record in records
            if isinstance(record, Mapping)
        ],
    }


async def _search_pdb() -> dict[str, Any]:
    query = {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_polymer_entity.pdbx_description",
                        "operator": "exact_match",
                        "value": "3C-like proteinase",
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entity_source_organism.ncbi_scientific_name",
                        "operator": "exact_match",
                        "value": "Severe acute respiratory syndrome coronavirus 2",
                    },
                },
            ],
        },
        "request_options": {
            "paginate": {"rows": 20, "start": 0},
            "sort": [
                {
                    "direction": "asc",
                    "sort_by": "rcsb_accession_info.initial_release_date",
                },
            ],
        },
        "return_type": "entry",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(PDB_SEARCH_URL, json=query)
    response.raise_for_status()
    payload = response.json()
    return {
        "query": query,
        "results": payload.get("result_set", []),
        "totalCount": payload.get("total_count"),
    }


def _select_pdb_id(pdb_search: Mapping[str, Any]) -> str:
    identifiers = [
        str(row.get("identifier"))
        for row in pdb_search.get("results", [])
        if isinstance(row, Mapping) and row.get("identifier")
    ]
    if TARGET_PDB_ID in identifiers:
        return TARGET_PDB_ID
    if identifiers:
        return identifiers[0]
    return TARGET_PDB_ID


async def _fetch_target_pdb(pdb_id: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(_pdb_download_url(pdb_id))
    response.raise_for_status()
    text = response.text
    if "3C-LIKE PROTEINASE" not in text and "MAIN PROTEASE" not in text:
        raise RuntimeError(f"Unexpected target structure downloaded for {pdb_id}.")
    return text


def _pdb_download_url(pdb_id: str) -> str:
    return f"https://files.rcsb.org/download/{pdb_id}.pdb"


def _target_sequence(target_pdb: str) -> str:
    sequences = extract_pdb_sequences(target_pdb)
    sequence = sequences.get(TARGET_CHAIN_ID)
    if not sequence:
        raise RuntimeError(f"Could not extract chain {TARGET_CHAIN_ID}.")
    return sequence


def _target_input_for_sequence(sequence: str) -> str:
    if not sequence:
        raise RuntimeError(f"Could not build target input for chain {TARGET_CHAIN_ID}.")
    return f"{TARGET_CHAIN_ID}1-{len(sequence)}"


async def _persist_target_artifact(
    *,
    config: WorkerConfig,
    database_url: str,
    run_id: str,
    workspace_id: str,
    pdb_id: str,
    target_pdb: str,
) -> str:
    body = target_pdb.encode("utf-8")
    storage_key = f"workspaces/{workspace_id}/runs/{run_id}/target/{pdb_id}.pdb"
    sha256 = await r2_put_object(
        bucket=config.r2_bucket,
        account_id=config.r2_account_id,
        access_key_id=config.r2_access_key_id,
        secret_access_key=config.r2_secret_access_key,
        key=storage_key,
        body=body,
        content_type="chemical/x-pdb",
    )
    return await create_artifact(
        database_url,
        workspace_id=workspace_id,
        run_id=run_id,
        kind="pdb",
        name=f"{pdb_id}.pdb",
        storage_key=storage_key,
        content_type="chemical/x-pdb",
        size_bytes=len(body),
        sha256=sha256,
        metadata_json={
            "chainId": TARGET_CHAIN_ID,
            "pdbId": pdb_id,
            "source": "rcsb",
            "url": _pdb_download_url(pdb_id),
        },
    )


async def _persist_json_artifact(
    *,
    config: WorkerConfig,
    database_url: str,
    run_id: str,
    workspace_id: str,
    kind: str,
    name: str,
    payload: Mapping[str, Any],
) -> str:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    storage_key = f"workspaces/{workspace_id}/runs/{run_id}/evidence/{name}"
    sha256 = await r2_put_object(
        bucket=config.r2_bucket,
        account_id=config.r2_account_id,
        access_key_id=config.r2_access_key_id,
        secret_access_key=config.r2_secret_access_key,
        key=storage_key,
        body=body,
        content_type="application/json",
    )
    return await create_artifact(
        database_url,
        workspace_id=workspace_id,
        run_id=run_id,
        kind=kind,
        name=name,
        storage_key=storage_key,
        content_type="application/json",
        size_bytes=len(body),
        sha256=sha256,
        metadata_json={"source": "demo_pipeline"},
    )


def _candidate_score_id(candidate: Mapping[str, Any]) -> str:
    rank = candidate.get("rank")
    if rank:
        return f"candidate-{rank}"
    filename = candidate.get("filename")
    if filename:
        return str(filename).rsplit(".", 1)[0]
    return str(candidate["candidate_id"])


def _best_candidate_from_scores(
    score_response: Any,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    results = []
    if isinstance(score_response, Mapping):
        raw_results = score_response.get("results") or score_response.get("items") or []
        if isinstance(raw_results, list):
            results = [row for row in raw_results if isinstance(row, Mapping)]
    best_result: Mapping[str, Any] | None = None
    best_value = float("-inf")
    for result in results:
        scores = result.get("scores")
        if not isinstance(scores, Mapping):
            continue
        dscript = scores.get("dscript")
        value = None
        if isinstance(dscript, Mapping):
            value = dscript.get("interaction_probability")
        if isinstance(value, int | float) and float(value) > best_value:
            best_value = float(value)
            best_result = result

    fallback = candidates[0]
    candidate_id_by_score_id = {
        _candidate_score_id(candidate): candidate["candidate_id"]
        for candidate in candidates
    }
    if best_result is None:
        return {
            "candidate_id": fallback["candidate_id"],
            "label": "first_candidate",
            "score": None,
        }

    score_id = str(best_result.get("id") or "")
    aggregate = best_result.get("aggregate")
    label = None
    if isinstance(aggregate, Mapping):
        label = aggregate.get("label")
    return {
        "candidate_id": candidate_id_by_score_id.get(score_id, fallback["candidate_id"]),
        "label": label or "best_candidate",
        "score": best_value,
        "score_id": score_id,
    }
