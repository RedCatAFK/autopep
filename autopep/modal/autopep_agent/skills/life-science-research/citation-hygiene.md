# Citation hygiene

Every literature reference in your final assistant message must include:

1. The retrieved title.
2. The DOI (preferred) or PubMed ID.
3. An inline link, formatted as `[Title (Year)](https://doi.org/10.xxxx/...)`.

If `literature_search` returned a paper without a DOI or PMID, do not invent
one — describe the source as "Europe PMC record {id}, no DOI assigned" and
move on.

## Never fabricate

- Never list a reference you did not retrieve in this run.
- Never paraphrase a paper's findings beyond what its title + abstract
  support, unless the user has provided the full text.
- If asked to "cite the seminal paper for X" and your search did not surface a
  clear seminal paper, say so. Do not produce a plausible-sounding citation.

## Format example

> **Top binders for SARS-CoV-2 main protease:**
>
> 1. Candidate-3 — D-SCRIPT 0.91, ΔG -10.2 kcal/mol, solubility 0.78.
>    Designed against PDB 6LU7. The active-site residues (His41, Cys145)
>    are documented in [Jin et al. (2020), DOI:10.1038/s41586-020-2223-y](https://doi.org/10.1038/s41586-020-2223-y).
