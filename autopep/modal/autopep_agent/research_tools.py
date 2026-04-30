from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx
from agents import function_tool


PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DEFAULT_MAX_RESULTS = 8
MAX_RESULTS_LIMIT = 20


def _clamp_max_results(max_results: int) -> int:
    return max(1, min(MAX_RESULTS_LIMIT, int(max_results)))


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _doi_from_article_ids(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if item.get("idtype") == "doi":
            return _string_or_none(item.get("value"))
    return None


def _authors_from_summary(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = _string_or_none(item.get("name"))
            if name:
                authors.append(name)
    return authors


def _pubmed_result(uid: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "authors": _authors_from_summary(record.get("authors")),
        "doi": _doi_from_article_ids(record.get("articleids")),
        "id": uid,
        "journal": _string_or_none(record.get("fulljournalname")),
        "published": _string_or_none(record.get("pubdate")),
        "title": _string_or_none(record.get("title")) or f"PubMed record {uid}",
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
    }


async def _search_pubmed_literature(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> dict[str, Any]:
    """Search PubMed via NCBI E-Utilities and return compact citation records."""

    limit = _clamp_max_results(max_results)
    async with httpx.AsyncClient(timeout=60) as client:
        search_response = await client.get(
            PUBMED_SEARCH_URL,
            params={
                "db": "pubmed",
                "retmode": "json",
                "retmax": limit,
                "term": query,
            },
        )
        search_response.raise_for_status()
        search_payload = search_response.json()
        raw_ids = search_payload.get("esearchresult", {}).get("idlist", [])
        ids = [item for item in raw_ids if isinstance(item, str) and item]
        if not ids:
            return {
                "query": query,
                "results": [],
                "source": "pubmed",
            }

        summary_response = await client.get(
            PUBMED_SUMMARY_URL,
            params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        summary_response.raise_for_status()
        summary_payload = summary_response.json()

    result_block = summary_payload.get("result", {})
    if not isinstance(result_block, Mapping):
        result_block = {}
    ordered_uids = result_block.get("uids")
    uids = (
        [uid for uid in ordered_uids if isinstance(uid, str)]
        if isinstance(ordered_uids, list)
        else ids
    )
    results: list[dict[str, Any]] = []
    for uid in uids:
        record = result_block.get(uid)
        if isinstance(record, Mapping):
            results.append(_pubmed_result(uid, record))

    return {
        "query": query,
        "results": results,
        "source": "pubmed",
    }


def _europe_pmc_url(*, doi: str | None, source: str, record_id: str) -> str:
    if doi:
        return f"https://doi.org/{quote(doi, safe='')}"
    return f"https://europepmc.org/article/{quote(source, safe='')}/{quote(record_id, safe='')}"


def _europe_pmc_result(record: Mapping[str, Any]) -> dict[str, Any] | None:
    record_id = _string_or_none(record.get("id"))
    title = _string_or_none(record.get("title"))
    if not record_id or not title:
        return None

    doi = _string_or_none(record.get("doi"))
    source = _string_or_none(record.get("source")) or "UNKNOWN"
    journal = _string_or_none(record.get("journalTitle"))
    return {
        "authors": _string_or_none(record.get("authorString")),
        "doi": doi,
        "id": record_id,
        "journal": journal,
        "published": _string_or_none(record.get("firstPublicationDate")),
        "source": source,
        "title": title,
        "url": _europe_pmc_url(doi=doi, source=source, record_id=record_id),
    }


async def _search_europe_pmc_literature(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> dict[str, Any]:
    """Search Europe PMC, including preprints/PMC records, for literature evidence."""

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

    raw_results = payload.get("resultList", {}).get("result", [])
    results: list[dict[str, Any]] = []
    if isinstance(raw_results, list):
        for record in raw_results:
            if not isinstance(record, Mapping):
                continue
            result = _europe_pmc_result(record)
            if result:
                results.append(result)

    return {
        "hitCount": payload.get("hitCount"),
        "query": query,
        "results": results,
        "source": "europe_pmc",
    }


search_pubmed_literature = function_tool(
    _search_pubmed_literature,
    name_override="search_pubmed_literature",
    strict_mode=False,
)
search_europe_pmc_literature = function_tool(
    _search_europe_pmc_literature,
    name_override="search_europe_pmc_literature",
    strict_mode=False,
)


RESEARCH_TOOLS: list[object] = [
    search_pubmed_literature,
    search_europe_pmc_literature,
]
