"""pdb_search and pdb_fetch tools.

pdb_search hits RCSB's Search API and returns metadata only (no PDB
downloads). Filters by chain length (default <500) and optional organism.

pdb_fetch downloads the chosen PDB into the workspace's R2-mounted
inputs/ directory and registers it as an `artifact` row.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from agents import function_tool

from autopep_agent.db import create_artifact
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import put_object as r2_put_object
from autopep_agent.run_context import get_tool_run_context
from autopep_agent.structure_utils import extract_pdb_sequences


RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download"


def _r2_config_from_env() -> dict[str, str]:
    """Pull R2 credentials from ``WorkerConfig``.

    Imported lazily so tests that patch ``pdb_tools`` don't drag the
    config import into module-load time.
    """

    from autopep_agent.config import WorkerConfig

    config = WorkerConfig.from_env()
    return {
        "bucket": config.r2_bucket,
        "account_id": config.r2_account_id,
        "access_key_id": config.r2_access_key_id,
        "secret_access_key": config.r2_secret_access_key,
    }


def _build_rcsb_query(
    *,
    query: str,
    max_chain_length: int,
    top_k: int,
    organism: str | None,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "entity_poly.rcsb_sample_sequence_length",
                "operator": "less",
                "value": max_chain_length,
            },
        },
    ]
    if organism:
        nodes.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entity_source_organism.ncbi_scientific_name",
                    "operator": "exact_match",
                    "value": organism,
                },
            },
        )
    return {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": nodes,
        },
        "request_options": {
            "paginate": {"rows": top_k, "start": 0},
            "sort": [
                {
                    "direction": "asc",
                    "sort_by": "rcsb_entry_info.resolution_combined",
                },
            ],
        },
        "return_type": "entry",
    }


async def _fetch_rcsb_search(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(RCSB_SEARCH_URL, json=payload)
        response.raise_for_status()
        return response.json()


async def _fetch_rcsb_entry_meta(pdb_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{RCSB_DATA_URL}/{pdb_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def _flatten_meta(pdb_id: str, meta: Mapping[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {
            "pdb_id": pdb_id,
            "title": None,
            "resolution": None,
            "method": None,
            "chain_lengths_by_id": {},
        }
    title = (meta.get("struct") or {}).get("title")
    resolutions = (meta.get("rcsb_entry_info") or {}).get("resolution_combined") or []
    method = None
    for entry in meta.get("exptl") or []:
        if isinstance(entry, Mapping) and entry.get("method"):
            method = entry["method"]
            break
    chain_lengths: dict[str, int] = {}
    for entity in meta.get("polymer_entities") or []:
        ids = (
            (entity or {}).get("rcsb_polymer_entity_container_identifiers") or {}
        ).get("asym_ids") or []
        length = ((entity or {}).get("entity_poly") or {}).get(
            "rcsb_sample_sequence_length"
        )
        if isinstance(length, int):
            for asym in ids:
                if isinstance(asym, str):
                    chain_lengths[asym] = length
    return {
        "pdb_id": pdb_id,
        "title": title,
        "resolution": resolutions[0] if resolutions else None,
        "method": method,
        "chain_lengths_by_id": chain_lengths,
    }


async def _pdb_search(
    query: str,
    max_chain_length: int = 500,
    top_k: int = 10,
    organism: str | None = None,
) -> dict[str, Any]:
    """Search RCSB by query + chain-length cap; return ranked metadata only."""
    payload = _build_rcsb_query(
        query=query,
        max_chain_length=max_chain_length,
        top_k=top_k,
        organism=organism,
    )
    search_payload = await _fetch_rcsb_search(payload)
    identifiers = [
        row.get("identifier")
        for row in search_payload.get("result_set") or []
        if isinstance(row, Mapping) and row.get("identifier")
    ]
    metas = await asyncio.gather(
        *(_fetch_rcsb_entry_meta(str(i)) for i in identifiers),
        return_exceptions=True,
    )
    results: list[dict[str, Any]] = []
    for ident, meta in zip(identifiers, metas):
        if isinstance(meta, BaseException):
            continue
        results.append(_flatten_meta(str(ident), meta))
    return {
        "query": query,
        "max_chain_length": max_chain_length,
        "results": results,
        "total_count": search_payload.get("total_count"),
    }


async def _download_pdb_text(pdb_id: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{RCSB_DOWNLOAD_URL}/{pdb_id}.pdb")
        response.raise_for_status()
        return response.text


def _pdb_storage_key(*, workspace_id: str, run_id: str, pdb_id: str) -> str:
    return f"workspaces/{workspace_id}/runs/{run_id}/inputs/{pdb_id}.pdb"


def _sandbox_path_for_pdb(*, run_id: str, pdb_id: str) -> str:
    return f"/workspace/runs/{run_id}/inputs/{pdb_id}.pdb"


async def _pdb_fetch(
    pdb_id: str,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Download a PDB from RCSB, mount it in the workspace, register an artifact."""
    ctx = get_tool_run_context()
    cfg = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    text = await _download_pdb_text(pdb_id)
    if not text.startswith("HEADER") and "ATOM" not in text:
        raise RuntimeError(
            f"PDB download for {pdb_id} did not look like a PDB file"
        )

    body = text.encode("utf-8")
    storage_key = _pdb_storage_key(
        workspace_id=ctx.workspace_id, run_id=ctx.run_id, pdb_id=pdb_id
    )
    sha256 = await r2_put_object(
        bucket=cfg["bucket"],
        account_id=cfg["account_id"],
        access_key_id=cfg["access_key_id"],
        secret_access_key=cfg["secret_access_key"],
        key=storage_key,
        body=body,
        content_type="chemical/x-pdb",
    )

    artifact_id = await create_artifact(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        kind="pdb",
        name=f"{pdb_id}.pdb",
        storage_key=storage_key,
        content_type="chemical/x-pdb",
        size_bytes=len(body),
        sha256=sha256,
        metadata_json={
            "pdbId": pdb_id,
            "source": "rcsb",
            "url": f"{RCSB_DOWNLOAD_URL}/{pdb_id}.pdb",
            "chainId": chain_id,
        },
    )
    await writer.append_event(
        run_id=ctx.run_id,
        event_type="artifact_created",
        title=f"Stored {pdb_id}.pdb",
        summary=f"Saved RCSB {pdb_id} into workspace inputs/.",
        display={"artifactId": artifact_id, "kind": "pdb", "pdbId": pdb_id},
    )

    sequences = extract_pdb_sequences(text)
    chosen_chain = chain_id or next(iter(sequences.keys()), None)
    if chosen_chain is None:
        raise RuntimeError(f"Could not extract any chain from {pdb_id}")
    sequence = sequences.get(chosen_chain, "")

    return {
        "pdb_id": pdb_id,
        "artifact_id": artifact_id,
        "sandbox_path": _sandbox_path_for_pdb(run_id=ctx.run_id, pdb_id=pdb_id),
        "chain_id": chosen_chain,
        "sequence": sequence,
        "all_chains": sequences,
    }


pdb_search = function_tool(
    _pdb_search,
    name_override="pdb_search",
    strict_mode=False,
)
pdb_fetch = function_tool(
    _pdb_fetch,
    name_override="pdb_fetch",
    strict_mode=False,
)
