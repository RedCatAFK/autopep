# Literature evidence discipline

When the user asks about biological knowledge that exists in the published
literature (mechanism, prior binders, structural homologues, clinical
findings), retrieve evidence with `literature_search` BEFORE answering.

## Hierarchy

1. **Peer-reviewed primary research** (PubMed, journals): highest weight for
   established mechanism. Cite explicitly.
2. **Reviews and meta-analyses**: useful for orienting; cite but distinguish
   from primary findings.
3. **Preprints (bioRxiv, medRxiv)**: useful for recent state-of-the-art and
   negative results. Always flag as "preprint, not yet peer-reviewed".
4. **Computational predictions in this run**: flag as model output, not
   evidence. Never weight equal to retrieved literature.

## Anti-patterns

- Citing a paper title without a DOI or PubMed link.
- Stating a fact "as established" when the only source is a 2024 preprint.
- Listing references in a final summary that you didn't actually retrieve.

## When to cite uncertainty

If the literature contains conflicting findings (e.g. "study A reports binding
affinity 5 nM, study B reports 50 nM"), surface the conflict explicitly. Do
not pick one number silently.
