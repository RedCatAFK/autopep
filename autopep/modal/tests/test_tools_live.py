"""Live integration tests for each tool the Autopep agent can invoke.

These tests hit the *real* upstream services (PubMed, Europe PMC, and the
project's Proteina/Chai/Scoring Modal endpoints) so we can answer the
question "does this tool work end-to-end right now?". They are deliberately
separated from the existing mocked unit tests in
``test_research_tools.py`` / ``test_endpoint_clients.py`` because they:

* require network access,
* may take minutes for the biology model endpoints,
* depend on credentials that are absent in CI.

Run them explicitly with::

    AUTOPEP_LIVE_TOOL_TESTS=1 pytest tests/test_tools_live.py -v

The slow biology-endpoint tests additionally require::

    AUTOPEP_LIVE_SLOW_TESTS=1

so they don't run accidentally during normal development.

Credentials are loaded from ``../../.env`` if present, then overridden by
real environment variables. Each test cleanly skips with a clear message
when its required env vars are missing rather than failing opaquely.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autopep_agent import endpoint_clients, research_tools


# ---------------------------------------------------------------------------
# Bootstrap: opt-in gate + .env loader
# ---------------------------------------------------------------------------

LIVE_GATE_ENV = "AUTOPEP_LIVE_TOOL_TESTS"
SLOW_GATE_ENV = "AUTOPEP_LIVE_SLOW_TESTS"
TESTDATA_DIR = Path(__file__).parent / "testdata"
TARGET_CIF_PATH = TESTDATA_DIR / "1CRN.cif"
DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv_if_present(path: Path) -> None:
    """Lightweight .env loader; only fills vars that aren't already set.

    We intentionally do NOT pull in python-dotenv as a hard dependency.
    The format we care about is ``KEY=VALUE`` (no shell substitution, no
    multi-line values). Lines starting with ``#`` and blank lines are
    ignored. Surrounding single/double quotes on the value are stripped.
    """
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_if_present(DOTENV_PATH)


pytestmark = pytest.mark.skipif(
    os.environ.get(LIVE_GATE_ENV) != "1",
    reason=(
        f"Live tool tests are opt-in. Set {LIVE_GATE_ENV}=1 to run."
    ),
)


def _require_env(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"Missing env vars for this live test: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# 1. search_pubmed_literature  (literature search via NCBI E-Utilities)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_pubmed_literature_real_query_returns_results() -> None:
    """Hit real PubMed for a query that is guaranteed to have hits.

    BACE1 / beta-secretase has thousands of indexed papers, so any non-empty
    response shape is acceptable evidence the tool is working. We only
    assert structural invariants — not exact titles — since PubMed's index
    drifts daily.
    """
    result = await research_tools._search_pubmed_literature(
        query="BACE1 beta secretase", max_results=3,
    )

    assert result["source"] == "pubmed"
    assert result["query"] == "BACE1 beta secretase"
    assert isinstance(result["results"], list)
    assert len(result["results"]) >= 1, "PubMed returned zero hits for BACE1"
    first = result["results"][0]
    assert first["id"]
    assert first["title"]
    assert first["url"].startswith("https://pubmed.ncbi.nlm.nih.gov/")


# ---------------------------------------------------------------------------
# 2. search_europe_pmc_literature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_europe_pmc_literature_real_query_returns_results() -> None:
    """Hit real Europe PMC for a known-populated query."""
    result = await research_tools._search_europe_pmc_literature(
        query="BACE1 beta secretase", max_results=3,
    )

    assert result["source"] == "europe_pmc"
    assert result["query"] == "BACE1 beta secretase"
    assert isinstance(result["results"], list)
    assert len(result["results"]) >= 1, "Europe PMC returned zero hits for BACE1"
    first = result["results"][0]
    assert first["id"]
    assert first["title"]
    assert first["url"]


# ---------------------------------------------------------------------------
# 3. ProteinaClient.design — generate_binder_candidates underlying call
# ---------------------------------------------------------------------------
#
# The wrapper ``_generate_binder_candidates`` also writes to Postgres + R2,
# which we don't want to exercise from a tool-level smoke test. We test the
# HTTP client directly because a hang or auth failure here is exactly what
# would prevent the agent's tool call from ever returning.


SLOW_REASON = (
    "Slow live biology-endpoint test. Set "
    f"{SLOW_GATE_ENV}=1 to run (each request can take minutes)."
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get(SLOW_GATE_ENV) != "1",
    reason=SLOW_REASON,
)
async def test_proteina_design_endpoint_responds_to_minimal_payload() -> None:
    """Smoke-test the live Proteina ``/design`` endpoint with a tiny target.

    We pass the smallest valid PDB structure we have on disk (1CRN, 46
    residues) and a single hotspot residue. Even on the fastest settings
    this endpoint can take a few minutes — the test is gated behind
    AUTOPEP_LIVE_SLOW_TESTS.
    """
    _require_env("MODAL_PROTEINA_URL", "MODAL_PROTEINA_API_KEY")
    assert TARGET_CIF_PATH.exists(), (
        f"Missing test fixture {TARGET_CIF_PATH}. Re-download with "
        "`curl -o tests/testdata/1CRN.cif https://files.rcsb.org/download/1CRN.cif`"
    )
    target_structure = TARGET_CIF_PATH.read_text()

    client = endpoint_clients.ProteinaClient(
        base_url=os.environ["MODAL_PROTEINA_URL"],
        api_key=os.environ["MODAL_PROTEINA_API_KEY"],
        timeout_s=600,
    )
    response = await client.design(
        target_structure=target_structure,
        target_filename="1CRN.cif",
        target_input=None,
        hotspot_residues=["A1"],
        binder_length=[20, 25],
    )

    # The endpoint shape is allowed to evolve; we only assert "we got
    # something dict-like back" so this stays a pure liveness smoke test.
    assert response is not None
    assert isinstance(response, (dict, list)), (
        f"Unexpected Proteina response type: {type(response).__name__}"
    )


# ---------------------------------------------------------------------------
# 4. ChaiClient.predict — fold_sequences_with_chai underlying call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get(SLOW_GATE_ENV) != "1",
    reason=SLOW_REASON,
)
async def test_chai_predict_endpoint_responds_to_minimal_fasta() -> None:
    """Smoke-test the live Chai ``/predict`` endpoint with one tiny sequence."""
    _require_env("MODAL_CHAI_URL", "MODAL_CHAI_API_KEY")
    fasta = (
        ">protein|name=test_binder\n"
        "MKQLEDKVEELLSKNYHLENEVARLKKLVGER\n"
    )

    client = endpoint_clients.ChaiClient(
        base_url=os.environ["MODAL_CHAI_URL"],
        api_key=os.environ["MODAL_CHAI_API_KEY"],
        timeout_s=900,
    )
    response = await client.predict(fasta=fasta, num_diffn_samples=1)

    assert response is not None
    assert isinstance(response, (dict, list)), (
        f"Unexpected Chai response type: {type(response).__name__}"
    )


# ---------------------------------------------------------------------------
# 5. ScoringClient.score_batch — score_candidate_interactions underlying call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get(SLOW_GATE_ENV) != "1",
    reason=SLOW_REASON,
)
async def test_scoring_score_batch_endpoint_responds_to_minimal_pair() -> None:
    """Smoke-test the live scoring ``/score_batch`` endpoint with one pair."""
    _require_env(
        "MODAL_PROTEIN_INTERACTION_SCORING_URL",
        "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY",
    )
    items = [
        {
            "id": "pair-1",
            "protein_a": {
                "name": "target",
                "sequence": "MKQLEDKVEELLSKNYHLENEVARLKKLVGER",
            },
            "protein_b": {
                "name": "binder",
                "sequence": "GSAEELRRRLEELERKLEELERKLE",
            },
        },
    ]

    client = endpoint_clients.ScoringClient(
        base_url=os.environ["MODAL_PROTEIN_INTERACTION_SCORING_URL"],
        api_key=os.environ["MODAL_PROTEIN_INTERACTION_SCORING_API_KEY"],
        timeout_s=600,
    )
    response = await client.score_batch(items)

    assert response is not None
    assert isinstance(response, (dict, list)), (
        f"Unexpected scoring response type: {type(response).__name__}"
    )
