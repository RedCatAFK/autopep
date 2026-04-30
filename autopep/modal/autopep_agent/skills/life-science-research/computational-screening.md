# Computational screening language

This agent runs **computational predictions** — Proteina structure
generation, Chai folding, D-SCRIPT/Prodigy interaction scoring, ESM-2
qualitative classifiers. None of this is wet-lab validation, clinical
efficacy, or therapeutic readiness.

## Required language

When summarizing results, use phrasing like:

- "Predicted interaction probability …"
- "Scored solubility likelihood …"
- "Computational binding-affinity estimate …"
- "Folded structure (Chai-1, no MSA) …"

## Forbidden language

Never use these without explicit caveats:

- "This binder will work in cell culture / animals / patients."
- "Safe / efficacious / therapeutic / drug-like."
- "Validated against …" (unless wet-lab data was supplied by the user).

## When uncertainty is high

If the top candidate's scores are mediocre (D-SCRIPT < 0.5, Prodigy ΔG > -5),
say so explicitly. Recommend further computational checks (re-fold with MSA,
mutate-and-rescore, longer Proteina sampling) instead of overclaiming.
