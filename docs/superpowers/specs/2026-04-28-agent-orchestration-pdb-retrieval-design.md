# Agent Orchestration And CIF Retrieval Design

Date: 2026-04-28

## Context

Autopep is a protein-design workspace. The long-term pipeline starts from a natural-language biology goal, finds or prepares target structures, runs downstream generation and scoring models, then iterates toward better binder candidates. This design covers only the first couple of steps:

1. accept a natural-language target request, such as "generate a protein to bind to SARS-CoV-2 spike RBD" or "generate a protein to bind to 3CL-protease";
2. search the Protein Data Bank and literature;
3. rank the top-k relevant protein structures;
4. download and prepare at least one CIF/mmCIF artifact for NVIDIA Proteina Complexa or another downstream model.

Downstream Proteina sequence generation, ProteinMPNN, Chai-1, Boltz scoring, and iterative mutation are integration boundaries, not part of this milestone.

The current repo is a T3/Next application with Better Auth, tRPC, Drizzle, and Neon/Postgres-ready database wiring. It does not yet have an agent, job, artifact, or protein candidate model.

## Product Direction

Autopep should feel like a visual-first molecular studio with transparent scientific provenance. The product is meant to democratize protein design for non-professionals while remaining inspectable by people with scientific training.

The first screen should be a workspace, not a landing page. It should be organized around:

- a simple natural-language project thread;
- a large molecular stage for Mol* structure visualization;
- a ranked candidate and artifact surface;
- a readable research trace showing what the agent did and why.

The app should one-up Phylo/Biomni-style biology workspaces by making the structure viewer and ranked evidence feel like one coherent instrument rather than a cramped set of generic panels. The user should see files appearing, candidates ranking, and the final Proteina-ready CIF state without needing to understand RCSB, UniProt, FASTA, mmCIF, or shell tooling up front.

Visual direction:

- off-white technical workspace, deep charcoal text, one restrained accent color;
- no AI-purple glow or generic dashboard-card visual language;
- asymmetric layout with the molecular viewer as the main stage;
- crisp lines, high-quality icons, and motion only where it explains state changes;
- expanded details for scientists, but a default path that is understandable to non-professionals.

## Goals

- Run an external Codex harness worker using gpt-5.5 and the life-science-research plugin.
- Accept natural-language target requests as the user-facing contract.
- Normalize target entities enough to drive structure and literature search.
- Search RCSB PDB and literature sources through plugin skills or Autopep-specific wrappers.
- Rank top-k candidate structures with an auditable explanation.
- Download source CIF/mmCIF files and prepare at least one CIF artifact for downstream model input.
- Enforce CIF/mmCIF as the universal structure handoff format, converting or rejecting other structure formats before marking an artifact ready.
- Upload important artifacts to Cloudflare R2.
- Store durable state, progress, candidates, and artifact metadata in Neon Postgres.
- Let the Vercel-hosted T3 frontend poll for near-real-time progress.

## Non-Goals

- Proteina Complexa inference.
- ProteinMPNN sequence generation.
- Chai-1 or Boltz scoring.
- Iterative mutation loops.
- Full multi-agent planning.
- Push-based realtime infrastructure.
- Wet-lab validation.
- Production-grade job queueing beyond a simple worker claim loop.

## Recommended Architecture

Use an external worker as the orchestration boundary.

The T3 app on Vercel owns users, projects, chat/job creation, artifact listing, Mol* visualization, and polling-based progress UI. It should create agent runs and read Neon/R2 state, but it should not directly supervise long-running Codex execution.

Neon Postgres is the durable state store. Every project, run, step, event, target entity, ranked protein candidate, and artifact metadata row should be stored there.

Cloudflare R2 is the durable file store. CIF/mmCIF files, prepared CIF files, FASTA files, raw search JSON worth preserving, and future generated structures should be stored as R2 objects. Neon stores object keys and metadata, not file contents.

The external agent worker owns the Codex harness lifecycle. It claims queued runs, launches the harness with gpt-5.5 and tool access, writes progress into Neon, uploads artifacts to R2, and marks completion only after durable database facts exist.

Modal sandboxes are execution scratch spaces. Use them when a skill requires shell/Python execution, when the agent needs to run retrieval helpers, or when a CIF file must be downloaded and prepared. A sandbox may use local disk or a temporary Modal Volume during one run, but Modal is not the project filesystem. As soon as an artifact matters, upload it to R2 and record it in Neon.

## Runtime Boundaries

### T3 App

Responsibilities:

- create projects and agent runs;
- render the prompt thread, progress trace, candidate ranking, artifact browser, and Mol* viewer;
- expose tRPC endpoints for project/run/event/candidate/artifact reads;
- create runs via authenticated mutations;
- poll for run updates every 1-3 seconds for milestone 1.

The app must remain deployable on Vercel free or low-cost tiers. Avoid long-running request handlers.

### Agent Worker

Responsibilities:

- claim queued `agent_runs`;
- launch and supervise the Codex harness;
- provide the harness with the life-science-research plugin and Autopep-specific output contracts;
- emit append-only `agent_events`;
- call Modal sandboxes for shell/Python/file tasks;
- upload accepted artifacts to R2;
- write final candidates and completion state.

For the hackathon, the worker can be a manually started long-running Node or Python process. The schema should still support later leasing, retries, cancellation, and multiple workers.

### Modal Sandbox

Responsibilities:

- run shell/Python skills that require filesystem or network execution;
- run RCSB/literature helper scripts when needed;
- download, clean, validate, and transform CIF/FASTA artifacts;
- return file paths, stdout/stderr summaries, and structured output to the worker.

The sandbox should use a minimal image with Python, life-science scripts, and lightweight structure utilities. It should not be required after the run completes.

### Neon And R2

Neon is for queryable state and provenance. R2 is for file bytes. The frontend and downstream model teams should depend on Neon rows and R2 artifacts, not on agent chat text or sandbox paths.

## Milestone 1 Workflow

1. User creates or opens an Autopep project.
2. User enters a natural-language target request.
3. T3 app creates an `agent_run` with status `queued`, prompt text, and `top_k`, defaulting to 5.
4. Worker claims the run and marks it `running`.
5. Worker emits `normalizing_target`.
6. Harness normalizes likely target entities, aliases, organism, and source IDs when available.
7. Worker emits `searching_structures` and runs RCSB Protein Data Bank search.
8. Worker emits `searching_literature` and runs PubMed/PMC/bioRxiv/other literature lookups as needed.
9. Harness ranks candidate structures using auditable heuristics.
10. Worker writes `protein_candidates` rows with rank and explanation.
11. Worker downloads source CIF/mmCIF files for top candidates through Modal or direct retrieval.
12. Worker prepares the selected CIF artifact, validates it can be parsed, uploads it to R2, and writes an `artifacts` row.
13. Worker marks the top candidate `proteina_ready` when it has a valid linked CIF artifact and enough metadata to explain why it was selected.
14. Worker emits final `ready_for_proteina` event and marks the run `succeeded`.

If the worker cannot produce a Proteina-ready artifact, it should mark the run `failed` with an error summary and preserve any partial candidates or artifacts it did produce.

## Ranking Heuristic

Initial ranking should be simple, transparent, and easy to revise.

Prefer candidates with:

- exact or near-exact target match;
- relevant organism or viral strain;
- experimentally resolved structures over predicted structures when available;
- useful resolution and coverage;
- relevant chain or complex context;
- ligand, receptor, inhibitor, or interface information when useful for binder design;
- supporting literature references;
- clean downloadable CIF/mmCIF format.

Recency is secondary. The model should not choose a structure only because it is new.

Each candidate needs a short `why_selected` explanation. This is product-critical because the audience includes non-professionals who need to understand the agent's reasoning without reading raw metadata.

## Data Model

### `projects`

High-level user workspace.

Suggested fields:

- `id`
- `owner_id`
- `name`
- `goal`
- `created_at`
- `updated_at`

### `agent_runs`

One worker execution for a project prompt.

Suggested fields:

- `id`
- `project_id`
- `created_by_id`
- `prompt`
- `status`: `queued | running | succeeded | failed | canceled`
- `top_k`
- `claimed_by`
- `claimed_at`
- `started_at`
- `finished_at`
- `error_summary`
- `created_at`
- `updated_at`

### `agent_events`

Append-only progress and trace log.

Suggested fields:

- `id`
- `run_id`
- `sequence`
- `type`
- `title`
- `detail`
- `payload_json`
- `created_at`

This table powers polling. The frontend should request new events by `run_id` and sequence cursor.

### `target_entities`

Normalized entities from the natural-language prompt.

Suggested fields:

- `id`
- `run_id`
- `label`
- `aliases_json`
- `organism`
- `source_ids_json`
- `confidence`
- `notes`
- `created_at`

### `protein_candidates`

Ranked structure/literature-supported candidates.

Suggested fields:

- `id`
- `run_id`
- `target_entity_id`
- `rank`
- `score`
- `rcsb_entry_id`
- `title`
- `organism`
- `experimental_method`
- `resolution`
- `chains_json`
- `literature_refs_json`
- `why_selected`
- `proteina_ready`
- `created_at`
- `updated_at`

### `artifacts`

R2-backed files and viewer metadata.

Suggested fields:

- `id`
- `project_id`
- `run_id`
- `candidate_id`
- `type`: `source_cif | prepared_cif | fasta | raw_search_json | report | other`
- `file_name`
- `mime_type`
- `size_bytes`
- `checksum`
- `r2_bucket`
- `r2_key`
- `viewer`
- `viewer_hints_json`
- `created_at`

For Mol*, a prepared CIF artifact should include viewer hints such as format, chain of interest, and optional residue annotations.

## Agent Output Contracts

The harness should produce structured outputs that the worker validates before writing durable state. Minimum contracts:

- target normalization JSON;
- ranked candidate JSON;
- artifact upload request records;
- final selected candidate and artifact IDs.

Completion cannot rely on free-form chat text. A run is complete only when:

- at least one `protein_candidates` row exists;
- at least one linked `prepared_cif` artifact exists in R2, or a `source_cif` artifact has been validated as already satisfying the downstream CIF/mmCIF handoff constraints;
- the top selected candidate is marked `proteina_ready`;
- a final event references the selected candidate ID and artifact ID.

## UI Contract

The frontend should present four live surfaces:

- `Project Thread`: human prompt and concise agent narration.
- `Molecular Stage`: Mol* viewer centered on the selected or active CIF artifact.
- `Evidence/Candidate Rail`: ranked structures with explanations, metadata, and source links.
- `Artifacts/Trace Rail`: files, preparation status, and expandable tool steps.

Default trace text should be understandable:

- "Found SARS-CoV-2 spike RBD"
- "Selected 6M0J because it contains chain E RBD bound to ACE2"
- "Prepared clean RBD CIF"

Detailed raw logs, stdout/stderr, JSON, and source payloads should be expandable rather than always visible.

Polling is sufficient for milestone 1. The frontend should poll run status and events every 1-3 seconds while a run is active.

## Error Handling

If normalization is uncertain, record multiple `target_entities` and continue when there is a reasonable first search. Ask for clarification only if the worker cannot choose a defensible search target.

If one source fails, emit a failed source step with retry metadata and continue with remaining sources when possible.

If a CIF downloads but cannot be parsed or prepared, keep the candidate visible but do not mark it `proteina_ready`.

If R2 upload fails, the run should not claim success. Durable artifact storage is part of completion.

If the worker crashes mid-run, the next worker should eventually be able to detect stale claims and retry or mark the run failed. The hackathon version can implement this manually, but the schema should leave room for it.

## Testing Strategy

Use deterministic fixtures for known prompts:

- "generate a binder for the SARS-CoV-2 spike RBD"
- "generate a protein to bind to 3CL-protease"

Unit tests should cover:

- schema helpers;
- R2 key construction;
- event append sequencing;
- candidate ranking shape and required fields;
- completion validation;
- UI polling response shapes.

Integration tests should first mock RCSB/literature APIs and R2. A live smoke test can run when network and credentials are available.

Success criteria for the milestone:

- a run can be created from the T3 app;
- the worker claims it and emits visible progress;
- target normalization, Protein Data Bank search, literature lookup, ranking, download, and artifact upload steps are represented in Neon;
- at least one top candidate has a CIF artifact in R2;
- the frontend can display the structure in Mol* and show why it was selected.

## Deployment Notes

- Vercel hosts the T3 app and should not run long-lived agent work.
- Neon stores project and progress state.
- Cloudflare R2 stores durable artifacts.
- Modal runs isolated shell/Python execution and file preparation as scratch compute.
- The worker can run wherever easiest for the hackathon: local laptop, a small VM, or a background service. It only needs Neon, R2, Modal, and model/tool credentials.

## References

- Modal Sandboxes: https://modal.com/docs/guide/sandboxes
- Modal sandbox files and Volumes: https://modal.com/docs/guide/sandbox-files
- Modal JavaScript SDK / libmodal: https://github.com/modal-labs/libmodal
- Phylo / Biomni public product reference: https://phylo.bio/
