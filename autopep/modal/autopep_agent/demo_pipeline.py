"""Constants for the autopep demo pipeline.

Orchestration was removed in 2026-04-30 — see
docs/superpowers/specs/2026-04-30-autopep-agent-pipeline-and-sandbox-design.md.
The named exports here are reused by the new pdb_search/literature_search
tools and by build_agent_instructions.
"""

from __future__ import annotations


TARGET_PDB_ID = "6LU7"
TARGET_CHAIN_ID = "A"
TARGET_NAME = "SARS-CoV-2 3CL-protease 6LU7 chain A"
TARGET_PDB_URL = f"https://files.rcsb.org/download/{TARGET_PDB_ID}.pdb"
PDB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
HOTSPOT_RESIDUES = ["A41", "A145", "A163", "A166", "A189"]
BINDER_LENGTH_MIN = 60
BINDER_LENGTH_MAX = 90

DEMO_RECIPE_NAME = "One-loop 3CL-protease binder demo"
DEMO_RECIPE_BODY = """\
When the user asks to generate a protein binder for 3CL-protease:
1. Search preprint/literature evidence for SARS-CoV-2 Mpro / 3CLpro context.
2. Run a filtered PDB search for SARS-CoV-2 3C-like proteinase structures.
3. Select a high-confidence experimental target structure, defaulting to 6LU7 chain A when appropriate.
4. Call proteina_design to generate binder candidates.
5. Fold generated candidates with chai_fold_complex.
6. Score target-candidate interactions with score_candidates.
7. Pick the strongest candidate for the MVP and stop after this one loop.
"""


def literature_query() -> str:
    """Reusable preprint-tilted query for SARS-CoV-2 main-protease evidence."""
    return (
        '("SARS-CoV-2" OR COVID-19) AND '
        '("3CL protease" OR Mpro OR "main protease") AND '
        '(SRC:PPR OR PUB_TYPE:"preprint")'
    )


def rcsb_3clpro_query() -> dict:
    """The canonical RCSB query JSON shape for 3C-like proteinase + SARS-CoV-2."""
    return {
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
