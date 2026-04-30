from __future__ import annotations

import httpx
import pytest
import respx

from autopep_agent import research_tools


@pytest.mark.asyncio
@respx.mock
async def test_search_pubmed_literature_returns_title_metadata_and_urls() -> None:
    search_route = respx.get(research_tools.PUBMED_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["12345", "67890"]}},
        ),
    )
    summary_route = respx.get(research_tools.PUBMED_SUMMARY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["12345", "67890"],
                    "12345": {
                        "articleids": [{"idtype": "doi", "value": "10.1000/bace1"}],
                        "authors": [{"name": "A Author"}],
                        "fulljournalname": "Journal of Secretases",
                        "pubdate": "2024",
                        "title": "BACE1 functions in human biology.",
                    },
                    "67890": {
                        "authors": [],
                        "fulljournalname": "Neuroscience Reports",
                        "pubdate": "2022",
                        "title": "Beta-secretase substrates.",
                    },
                },
            },
        ),
    )

    result = await research_tools._search_pubmed_literature(
        query="BACE1 human function",
        max_results=2,
    )

    assert search_route.called
    assert summary_route.called
    assert search_route.calls.last.request.url.params["term"] == "BACE1 human function"
    assert summary_route.calls.last.request.url.params["id"] == "12345,67890"
    assert result["source"] == "pubmed"
    assert result["results"] == [
        {
            "authors": ["A Author"],
            "doi": "10.1000/bace1",
            "id": "12345",
            "journal": "Journal of Secretases",
            "published": "2024",
            "title": "BACE1 functions in human biology.",
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        },
        {
            "authors": [],
            "doi": None,
            "id": "67890",
            "journal": "Neuroscience Reports",
            "published": "2022",
            "title": "Beta-secretase substrates.",
            "url": "https://pubmed.ncbi.nlm.nih.gov/67890/",
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_search_europe_pmc_literature_returns_open_literature_records() -> None:
    route = respx.get(research_tools.EUROPE_PMC_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "hitCount": 1,
                "resultList": {
                    "result": [
                        {
                            "authorString": "Author A, Author B",
                            "doi": "10.1101/2026.01.01.000001",
                            "firstPublicationDate": "2026-01-01",
                            "id": "PPR123",
                            "journalTitle": "bioRxiv",
                            "source": "PPR",
                            "title": "A BACE1 preprint.",
                        },
                    ],
                },
            },
        ),
    )

    result = await research_tools._search_europe_pmc_literature(
        query="BACE1 human function",
        max_results=3,
    )

    assert route.called
    assert route.calls.last.request.url.params["query"] == "BACE1 human function"
    assert result["hitCount"] == 1
    assert result["results"] == [
        {
            "authors": "Author A, Author B",
            "doi": "10.1101/2026.01.01.000001",
            "id": "PPR123",
            "journal": "bioRxiv",
            "published": "2026-01-01",
            "source": "PPR",
            "title": "A BACE1 preprint.",
            "url": "https://doi.org/10.1101%2F2026.01.01.000001",
        },
    ]
