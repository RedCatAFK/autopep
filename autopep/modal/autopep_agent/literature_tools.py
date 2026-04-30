"""Unified literature_search tool — fans out to PubMed + Europe PMC.

Europe PMC's SRC:PPR filter covers bioRxiv + medRxiv + arXiv preprints,
plus PMC and PubMed records. We keep PubMed E-Utilities as a separate
source for peer-reviewed citations and merge dedup'd by DOI then PMCID.

Failures in one source do NOT abort the call; the merged response includes
an `errors` map naming any failed source so the agent can flag partial data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from agents import function_tool


PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DEFAULT_MAX_RESULTS = 8
MAX_RESULTS_LIMIT = 20


def _clamp_max_results(n: int) -> int:
    return max(1, min(MAX_RESULTS_LIMIT, int(n)))


def _strip(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _doi_from_articleids(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, Mapping) and item.get("idtype") == "doi":
            return _strip(item.get("value"))
    return None


def _pmcid_from_articleids(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, Mapping) and item.get("idtype") == "pmc":
            return _strip(item.get("value"))
    return None


async def _search_pubmed(query: str, max_results: int) -> dict[str, Any]:
    limit = _clamp_max_results(max_results)
    async with httpx.AsyncClient(timeout=60) as client:
        search = await client.get(
            PUBMED_SEARCH_URL,
            params={"db": "pubmed", "retmode": "json", "retmax": limit, "term": query},
        )
        search.raise_for_status()
        ids = [
            i for i in search.json().get("esearchresult", {}).get("idlist", [])
            if isinstance(i, str)
        ]
        if not ids:
            return {"results": []}

        summary = await client.get(
            PUBMED_SUMMARY_URL,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        summary.raise_for_status()
        block = summary.json().get("result", {})

    results: list[dict[str, Any]] = []
    for uid in block.get("uids", ids):
        record = block.get(uid)
        if not isinstance(record, Mapping):
            continue
        results.append(
            {
                "id": uid,
                "title": _strip(record.get("title")) or f"PubMed {uid}",
                "doi": _doi_from_articleids(record.get("articleids")),
                "pmcid": _pmcid_from_articleids(record.get("articleids")),
                "journal": _strip(record.get("fulljournalname")),
                "published": _strip(record.get("pubdate")),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source": "pubmed",
            }
        )
    return {"results": results}


async def _search_europe_pmc(query: str, max_results: int) -> dict[str, Any]:
    limit = _clamp_max_results(max_results)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            EUROPE_PMC_SEARCH_URL,
            params={
                "format": "json",
                "pageSize": limit,
                "query": query,
                "resultType": "core",
                "sort": "FIRST_PDATE_D desc",
            },
        )
        response.raise_for_status()
        payload = response.json()

    results: list[dict[str, Any]] = []
    for record in payload.get("resultList", {}).get("result", []) or []:
        if not isinstance(record, Mapping):
            continue
        rid = _strip(record.get("id"))
        title = _strip(record.get("title"))
        if not rid or not title:
            continue
        doi = _strip(record.get("doi"))
        pmcid = _strip(record.get("pmcid"))
        source = _strip(record.get("source")) or "UNKNOWN"
        url = (
            f"https://doi.org/{doi}" if doi
            else f"https://europepmc.org/article/{source}/{rid}"
        )
        results.append(
            {
                "id": rid,
                "title": title,
                "doi": doi,
                "pmcid": pmcid,
                "journal": _strip(record.get("journalTitle")),
                "published": _strip(record.get("firstPublicationDate")),
                "authors": _strip(record.get("authorString")),
                "url": url,
                "source": source,
            }
        )
    return {"results": results, "hitCount": payload.get("hitCount")}


def _dedup_key(record: Mapping[str, Any]) -> str:
    """Stable dedup key — DOI when present, else PMCID, else (source, id)."""
    doi = record.get("doi")
    if isinstance(doi, str) and doi:
        return f"doi:{doi.lower()}"
    pmcid = record.get("pmcid")
    if isinstance(pmcid, str) and pmcid:
        return f"pmcid:{pmcid.upper()}"
    return f"src:{record.get('source')}:{record.get('id')}"


async def _literature_search(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> dict[str, Any]:
    """Search PubMed + Europe PMC in parallel; dedup; merge sorted by recency."""
    results = await asyncio.gather(
        _search_pubmed(query, max_results),
        _search_europe_pmc(query, max_results),
        return_exceptions=True,
    )
    errors: dict[str, str] = {}
    pubmed_records: list[dict[str, Any]] = []
    europe_records: list[dict[str, Any]] = []

    if isinstance(results[0], BaseException):
        errors["pubmed"] = str(results[0])
    else:
        pubmed_records = list(results[0].get("results", []))
    if isinstance(results[1], BaseException):
        errors["europe_pmc"] = str(results[1])
    else:
        europe_records = list(results[1].get("results", []))

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for source_records in (pubmed_records, europe_records):
        for record in source_records:
            key = _dedup_key(record)
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)

    merged.sort(key=lambda r: r.get("published") or "", reverse=True)

    response: dict[str, Any] = {"query": query, "results": merged[:max_results]}
    if errors:
        response["errors"] = errors
    return response


literature_search = function_tool(
    _literature_search,
    name_override="literature_search",
    strict_mode=False,
)
