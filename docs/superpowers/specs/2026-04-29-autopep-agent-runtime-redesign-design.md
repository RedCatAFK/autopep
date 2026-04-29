# Autopep Agent Runtime Redesign Design

Date: 2026-04-29

## Context

Autopep is moving from a crowded prototype workspace into a Codex/Cursor/Claude Code-style scientific agent interface. The current UI splits the same agent story across a prompt card, examples, assistant card, best match, "what's ready", ranked structures, research trace, design journey, and Mol* viewer chrome. The result is visually busy and technically brittle: the frontend is carrying too many bespoke panels instead of rendering a single durable agent/run/artifact model.

The project has no active users, so the Autopep-specific database tables may be destructively replaced. Better Auth user/session/account tables should remain unless a later migration explicitly needs to change authentication.

This design replaces the Codex harness-in-Modal approach with a Python OpenAI Agents SDK runtime on Modal, using SDK-native `SandboxAgent` support with `ModalSandboxClient`. Autopep keeps ownership of durable state, event normalization, artifacts, workspace management, recipes, and the biology-specific tool contract.

## Goals

- Replace the current fragmented left and right panels with a unified chat-plus-progress surface.
- Use a Python OpenAI Agents SDK worker as the agent control plane.
- Use SDK-native `SandboxAgent` plus Modal sandboxes for code execution, file mutation, BioPython, artifact preparation, and resumable workspace state.
- Stream model tokens, agent steps, tool calls, and sandbox command output into an Autopep-owned event ledger.
- Keep Vercel as a thin frontend/API layer, not the long-running execution host.
- Always load the Life Science Research plugin into the agent environment.
- Model core biology actions as structured tools with stable inputs, outputs, artifacts, and events.
- Treat the Modal-hosted Proteina-Complexa, Chai-1, and protein interaction scoring endpoints as first-class agent tools.
- Support one full end-to-end MVP loop for the 3CL-protease binder demo: research, structure selection, generation, folding, scoring, and ranked summary.
- Add first-class workspaces, threads, recipes, context references, artifacts, and run lineage.
- Make Mol* selection a prompt context source so a user can refer to clicked protein regions.
- Preserve flexibility for later branching candidate-generation pipelines.

## Non-Goals

- Production billing, quotas, or team administration.
- Wet-lab validation or medical/clinical claims.
- Multi-loop BFS/tree search optimization in the first implementation pass.
- A direct frontend connection to the OpenAI SDK stream as the only source of truth.
- Additional scoring functions beyond the protein interaction scoring endpoint. Chai-1 confidence values may rank folds from one request, but they are not binding scores.

## Architecture

Use four explicit runtime boundaries:

1. **Next/Vercel app**
   - Owns authenticated UI, workspace CRUD, chat input, read APIs, lightweight mutations, and browser rendering.
   - Creates messages and queued runs.
   - Reads durable state from Neon and object metadata from the app API.
   - Starts Modal work through a short API call, then exits.
   - Does not supervise long-running agent execution.

2. **Neon Postgres**
   - Owns queryable product state: workspaces, threads, messages, runs, events, artifacts, candidates, recipes, context references, sandbox state snapshots, and lineage.
   - Acts as the durable realtime ledger. The frontend reads events by cursor.

3. **Cloudflare R2 or compatible object storage**
   - Owns file bytes: CIF/mmCIF, PDB, FASTA, raw search responses worth preserving, generated BioPython scripts, generated or mutated structures, logs, thumbnails, and scoring reports.
   - Neon stores object keys, hashes, MIME type, size, provenance, and semantic metadata.

4. **Modal worker and sandboxes**
   - Runs the Python OpenAI Agents SDK.
   - Creates or resumes `SandboxAgent` sessions with `ModalSandboxClient`.
   - Executes BioPython, command-line preparation, downloads, mutations, validation, and future generation/scoring code in sandboxes.
   - Consumes SDK streaming events and Modal process streams, normalizes them, and appends Autopep events to Neon.

This keeps the cheapest/free-tier shape practical: Vercel Hobby for the UI, Neon free/serverless for state, R2 for low-cost artifacts, and Modal Starter/on-demand execution with spend limits. The first implementation should spawn one Modal function per run. Sandbox session state may be persisted and resumed for a workspace, but the worker process itself should not stay alive between runs.

## Agent Runtime

The worker should be Python-first. The top-level Autopep agent is a normal Agents SDK agent with access to structured Autopep tools and an execution boundary. For shell/file/code tasks, use `SandboxAgent` with:

- `SandboxRunConfig(client=ModalSandboxClient(), session=...)`
- `ModalSandboxClientOptions(app_name="autopep-agent", workspace_persistence="snapshot_filesystem", timeout=...)`
- a controlled image containing Python, BioPython, structure utilities, and the mounted/lazily loaded recipe and life-science skill directories
- sandbox capabilities for shell, filesystem, skills, memory, and compaction where useful

Autopep should not rebuild sandbox lifecycle, snapshots, and remote shell binding from scratch. The SDK-native sandbox layer is the right default. Autopep should build around it:

- durable run/session records
- normalized events
- biology tool wrappers
- artifact upload and metadata
- workspace and recipe policy
- cost, timeout, cancellation, and approval rules

The Modal example repository currently uses `Runner.run(...)` plus lifecycle hooks and a terminal display. Autopep should instead use `Runner.run_streamed(...)` for primary runs so the product can show token and step progress.

## Streaming Contract

The SDK stream is an internal source, not the frontend transport. The Modal worker consumes it and writes Autopep events.

Worker flow:

1. Claim a queued run.
2. Mark it `running`.
3. Start `Runner.run_streamed(...)` with the selected agent/session/sandbox config.
4. Iterate `result.stream_events()`.
5. Map `raw_response_event` text deltas to buffered `assistant_token_delta` events.
6. Map `run_item_stream_event` records to `tool_call_started`, `tool_call_completed`, `reasoning_step`, `handoff`, `message_created`, or `approval_requested`.
7. Map `agent_updated_stream_event` to `agent_changed`.
8. For Modal command execution, stream `stdout` and `stderr` from the sandbox process into `sandbox_stdout_delta` and `sandbox_stderr_delta` events where the command/tool wrapper supports streaming.
9. Persist final message, final run output, `last_response_id` or equivalent continuation state, sandbox session state, and artifacts.
10. Mark the run `completed`, `failed`, `paused`, or `cancelled`.

The frontend should read from Neon through cursor-based polling first. Short-lived SSE can be added as an acceleration layer, but polling remains the reliable baseline because Vercel request duration and Edge streaming limits make long-lived agent streams a poor source of truth.

Events are append-only and ordered per run by `sequence`. Every event has a compact display shape plus raw JSON for expanded details.

Core event types:

- `run_started`
- `assistant_message_started`
- `assistant_token_delta`
- `assistant_message_completed`
- `reasoning_step`
- `tool_call_started`
- `tool_call_delta`
- `tool_call_completed`
- `tool_call_failed`
- `sandbox_command_started`
- `sandbox_stdout_delta`
- `sandbox_stderr_delta`
- `sandbox_command_completed`
- `artifact_created`
- `candidate_ranked`
- `approval_requested`
- `agent_changed`
- `run_paused`
- `run_failed`
- `run_cancelled`
- `run_completed`

## Data Model

Destructively replace Autopep-specific tables with a schema centered on workspaces, chat, runs, events, artifacts, and recipes. Keep Better Auth tables.

### `workspaces`

One top-level user workspace.

Fields:

- `id`
- `owner_id`
- `name`
- `description`
- `active_thread_id`
- `created_at`
- `updated_at`
- `archived_at`

### `threads`

Conversation timeline within a workspace.

Fields:

- `id`
- `workspace_id`
- `title`
- `created_at`
- `updated_at`

### `messages`

User, assistant, and system-visible messages.

Fields:

- `id`
- `thread_id`
- `run_id`
- `role`: `user | assistant | system`
- `content`
- `context_refs_json`
- `recipe_refs_json`
- `attachment_refs_json`
- `created_at`

### `agent_runs`

One agent execution turn or background task.

Fields:

- `id`
- `workspace_id`
- `thread_id`
- `parent_run_id`
- `root_run_id`
- `created_by_id`
- `status`: `queued | running | paused | completed | failed | cancelled`
- `task_kind`: `chat | research | structure_search | prepare_structure | mutate_structure | branch_design`
- `prompt`
- `model`
- `agent_name`
- `modal_call_id`
- `sandbox_session_state_json`
- `sdk_state_json`
- `last_response_id`
- `started_at`
- `finished_at`
- `error_summary`
- `created_at`
- `updated_at`

`parent_run_id` and `root_run_id` are required now so later tree-like protein generation can branch without another schema rewrite.

### `agent_events`

Append-only durable run trace.

Fields:

- `id`
- `run_id`
- `sequence`
- `type`
- `title`
- `summary`
- `display_json`
- `raw_json`
- `created_at`

`display_json` is safe for compact UI cards. `raw_json` stores SDK/tool/sandbox detail for expanded inspection.

### `artifacts`

Any durable file or derived object.

Fields:

- `id`
- `workspace_id`
- `run_id`
- `source_artifact_id`
- `kind`: `cif | mmcif | pdb | fasta | sequence | pdb_metadata | literature_snapshot | biopython_script | proteina_result | chai_result | mutated_structure | score_report | log | image | other`
- `name`
- `storage_provider`
- `storage_key`
- `content_type`
- `size_bytes`
- `sha256`
- `metadata_json`
- `created_at`

### `protein_candidates`

Ranked structures or generated candidates.

Fields:

- `id`
- `workspace_id`
- `run_id`
- `parent_candidate_id`
- `rank`
- `source`: `rcsb_pdb | alphafold | proteina_complexa | chai_1 | generated | uploaded | mutated`
- `structure_id`
- `chain_ids_json`
- `sequence`
- `title`
- `score_json`
- `why_selected`
- `artifact_id`
- `fold_artifact_id`
- `parent_inference_id`
- `metadata_json`
- `created_at`

`parent_candidate_id` supports future mutation lineage.

### `model_inferences`

One external model/tool invocation that may create many candidates or artifacts.

Fields:

- `id`
- `workspace_id`
- `run_id`
- `parent_inference_id`
- `provider`: `modal`
- `model_name`: `proteina_complexa | chai_1 | protein_interaction_scoring | future_scorer`
- `status`: `queued | running | completed | failed | cancelled`
- `endpoint_url_snapshot`
- `request_json`
- `response_json`
- `external_request_id`
- `started_at`
- `finished_at`
- `error_summary`
- `created_at`

This table keeps long-running generation, folding, and scoring calls auditable without turning the chat trace into the only source of provenance.

### `candidate_scores`

Queryable score records for one candidate or candidate-target pair.

Fields:

- `id`
- `workspace_id`
- `run_id`
- `candidate_id`
- `model_inference_id`
- `scorer`: `dscript | prodigy | protein_interaction_aggregate | future_scorer`
- `status`: `ok | partial | failed | unavailable`
- `label`
- `value`
- `unit`
- `values_json`
- `warnings_json`
- `errors_json`
- `created_at`

The scoring endpoint also returns an aggregate label. Store that aggregate as its own `candidate_scores` row so the UI can sort/filter without parsing raw response JSON.

### `context_references`

References injected into a prompt, including Mol* selections.

Fields:

- `id`
- `workspace_id`
- `artifact_id`
- `kind`: `protein_selection | artifact | candidate | literature | note`
- `label`
- `selector_json`
- `created_by_id`
- `created_at`

For protein selections, `selector_json` should include structure/artifact identity, chain identifiers, residue ranges or residue IDs, atom IDs when selected, and Mol* loci data when needed for accurate restoration.

### `recipes`

Reusable markdown instructions.

Fields:

- `id`
- `owner_id`
- `workspace_id`
- `name`
- `description`
- `body_markdown`
- `is_global`
- `enabled_by_default`
- `created_at`
- `updated_at`
- `archived_at`

### `recipe_versions`

Immutable recipe bodies for reproducible runs.

Fields:

- `id`
- `recipe_id`
- `version`
- `body_markdown`
- `created_by_id`
- `created_at`

### `run_recipes`

The exact recipe versions attached to a run.

Fields:

- `id`
- `run_id`
- `recipe_id`
- `recipe_version_id`
- `name_snapshot`
- `body_snapshot`
- `created_at`

Messages may still keep `recipe_refs_json` for quick rendering, but reproducibility depends on `run_recipes`.

## Biology Tool Contract

The Life Science Research plugin should always be available to the agent process. The first implementation should load its relevant skills or materialize them through the SDK skills capability rather than asking the user to opt in.

Autopep-specific tools should wrap the same ideas in stable product contracts:

- `search_structures(query, target_entities, top_k, filters)` - RCSB/PDB search with compact ranked results.
- `search_literature(query, entities, sources)` - PubMed/PMC/bioRxiv summaries with identifiers and evidence links.
- `download_structure(structure_id, format)` - downloads source CIF/mmCIF and stores an artifact.
- `prepare_structure(artifact_id, options)` - validates and prepares a design-ready CIF artifact.
- `inspect_structure(artifact_id, selector)` - summarizes chains, residues, ligands, interfaces, or clicked selections.
- `run_biopython(task, input_artifacts, code_policy)` - executes generated BioPython in a sandbox and returns artifacts/logs.
- `mutate_structure(artifact_id, mutations, selector, rationale)` - applies controlled mutations in BioPython and produces a new structure artifact.
- `generate_binder_candidates(target_artifact_id, target_input, hotspot_residues, binder_length, warm_start_candidates, mode)` - calls Proteina-Complexa and stores generated PDB candidates.
- `fold_sequences_with_chai(fasta, sequence_candidates, sampling)` - calls Chai-1 and stores ranked CIF fold predictions.
- `score_candidate_interactions(target_candidate_id, binder_candidates, structure_artifacts, options)` - calls protein interaction scoring and stores D-SCRIPT, PRODIGY, and aggregate score rows.

Each tool returns structured JSON plus any artifact IDs. Raw source payloads should be stored only when useful for audit/debugging; the UI should default to compact summaries.

Initial biology scope:

- Q&A chat grounded in current workspace context.
- Literature search through PubMed/PMC/bioRxiv where relevant.
- PDB search/download/visualization.
- CIF/mmCIF preparation and validation.
- BioPython execution for inspection and simple mutation tasks.
- Proteina-Complexa candidate generation from a prepared target structure.
- Chai-1 folding of amino-acid sequences into ranked CIF structures.
- Protein interaction scoring with D-SCRIPT and PRODIGY for one generated candidate batch.

Later scope:

- branch-and-bound candidate trees
- hierarchical validation
- additional scoring models and consensus ranking
- generated protein lineage
- multi-loop iterative research/generation

The current schema already leaves room for those later phases through `parent_run_id`, `root_run_id`, and `parent_candidate_id`.

## Modal Inference Endpoints

Autopep now has three deployed Modal inference APIs that should be called only from server-side code or the Modal worker. The browser must never receive these API keys.

Required environment variables:

- `MODAL_CHAI_URL`
- `MODAL_CHAI_API_KEY`
- `MODAL_PROTEINA_URL`
- `MODAL_PROTEINA_API_KEY`
- `MODAL_PROTEIN_INTERACTION_SCORING_URL`
- `MODAL_PROTEIN_INTERACTION_SCORING_API_KEY`

The inference APIs accept `X-API-Key`, `Authorization: Bearer`, or HTTP Basic auth. Autopep should use `X-API-Key` for backend calls.

### Chai-1

Purpose: predict 3D structures from amino-acid FASTA input.

Endpoint:

- `GET /health`
- `POST /predict`
- `POST /`

Request options:

- raw FASTA body, or JSON body with `fasta`
- `fasta`: required, max 128 KiB, must start with `>`
- `num_trunk_recycles`: default `3`, range `1-20`
- `num_diffn_timesteps`: default `200`, range `1-1000`
- `num_diffn_samples`: default `5`, range `1-10`
- `seed`: default `42`, range `0-2147483647`
- `include_pdb`: default `false`
- `include_viewer_html`: default `false`

Server-fixed model settings:

- MSA search disabled
- template search disabled
- ESM embeddings enabled
- primary output format is CIF/mmCIF

Response:

- `format: "cif"`
- `count`
- `request_id`
- `cifs[]` with `rank`, `filename`, `cif`, `aggregate_score`, `mean_plddt`, and optional `pdb` or `viewer_html`
- `parameters`
- `timings`

Autopep handling:

- Store every returned CIF as an artifact.
- Create or update generated/folded `protein_candidates` for each returned rank.
- Use `aggregate_score` and `mean_plddt` as fold-confidence metadata only. They do not replace binding or safety scoring.
- Render rank 1 by default in Mol*, with rank switching available from the candidate card.

### Proteina-Complexa

Purpose: generate binder candidate structures from a target structure and optional warm-start seed binders.

Endpoint:

- `GET /health`
- `POST /design`
- `POST /predict`
- `POST /design.pdb`
- `POST /predict.pdb`
- `POST /`

Request is JSON only.

Target contract:

- `target.structure`: required CIF/PDB text, max 16 MiB. File paths are rejected.
- `target.filename`: source filename, used to infer structure format.
- `target.name`: optional target name.
- `target.target_input`: target residue selection such as `A1-162`; if omitted the server attempts to infer contiguous chain ranges.
- `target.chains`: optional chain filter.
- `target.hotspot_residues`: optional list such as `["A45"]`.
- `target.binder_length`: inclusive `[min_length, max_length]`, default `[60, 120]`.

Generation controls:

- `action`: `design-cif`, `design`, `predict`, `smoke-cif`, or `smoke`.
- `run_name`: optional durable run name.
- `pipeline_config`: optional Complexa pipeline config.
- `overrides`: optional Hydra override strings.
- `design_steps`: optional subset of `generate | filter | evaluate | analyze`.
- `return_format`: `pdb`, `file`, or `download` to return only the first PDB.

Warm start:

- `warm_start` may be one object or a list.
- each seed contains `structure`, `filename`, optional `chain`, optional `noise_level`, optional `start_t`, optional `num_steps`.
- batched warm starts must share `noise_level`, `start_t`, and `num_steps` when those controls are set.
- if warm-start setup fails, the wrapper falls back to cold generation and reports that in `design.warm_start.mode`.

Response:

- `run_name`
- `task_name`
- `mode`
- `format: "pdb"`
- `warm_start_count`
- `count`
- `pdbs[]` with `rank`, `filename`, `relative_path`, `pdb`
- first `pdb_filename` and `pdb`
- `preprocessed_target` with target sequence, target input, paths, feature JSON/FASTA paths, and Hydra overrides
- `design.warm_start` metadata

Autopep handling:

- Send prepared target CIF/mmCIF text or PDB text from stored artifacts.
- Use Mol* selections to populate `target_input` and `hotspot_residues` when the user explicitly selects a binding region.
- Store every returned PDB as an artifact.
- Extract binder sequences from returned PDBs into `protein_candidates.sequence` and/or FASTA artifacts.
- Create `protein_candidates` with `source="proteina_complexa"` and lineage back to the target candidate/artifact.
- Fan out Chai-1 folding calls for generated sequences when the workflow requires independent folding prediction.
- Keep `smoke-cif` as a health/check mode; use `design-cif` for real candidate generation.

### Protein Interaction Scoring

Purpose: score generated target-binder pairs with available computational interaction indicators.

Endpoint:

- `GET /health`
- `POST /score_batch`
- `POST /score_batch_upload`

Request options:

- `items[]`: non-empty batch, default service maximum is 8 items.
- `items[].id`: stable candidate/pair identifier.
- `items[].protein_a`: target protein name and optional sequence.
- `items[].protein_b`: binder protein name and optional sequence.
- `items[].structure`: optional PDB/CIF/mmCIF complex containing both proteins.
- `structure.format`: `pdb | cif | mmcif`.
- `structure.content_base64`: base64-encoded structure content, max 25 MiB decoded by default.
- `structure.chain_a` and `structure.chain_b`: optional chain identifiers; the server can infer the first two protein chains when omitted.
- `options.run_dscript`: default `true`.
- `options.run_prodigy`: default `true`.
- `options.temperature_celsius`: default `25.0`.
- `options.fail_fast`: default `false`.

Response:

- `results[]`, preserving request order.
- per result `status`: `ok | partial | failed`.
- `scores.dscript.available`, `interaction_probability`, `raw_score`, `model_name`, `warnings`.
- `scores.prodigy.available`, `delta_g_kcal_per_mol`, `kd_molar`, `temperature_celsius`, `warnings`.
- `aggregate.available`, `label`, `notes`.
- item-level `errors` and `warnings`.
- `batch_summary` with submitted/succeeded/partial/failed counts.

Aggregate labels:

- `likely_binder`: D-SCRIPT probability >= 0.7 and PRODIGY delta G <= -7.0 kcal/mol.
- `possible_binder`: D-SCRIPT probability >= 0.5 or PRODIGY delta G <= -5.0 kcal/mol.
- `unlikely_binder`: D-SCRIPT probability < 0.5 and PRODIGY delta G > -5.0 kcal/mol.
- `insufficient_data`: one or both scorers unavailable.

Autopep handling:

- Prefer `/score_batch` with base64 structure content when artifacts are already in R2.
- Use `protein_a` for the target chain/sequence and `protein_b` for the generated binder.
- Include a structure complex when possible so PRODIGY can run; sequence-only pairs only support D-SCRIPT.
- Store raw response JSON in `model_inferences.response_json`.
- Store D-SCRIPT, PRODIGY, and aggregate values in `candidate_scores`.
- Treat the aggregate label as a computational screening indicator, not a wet-lab binding claim.
- Sort the MVP candidate list by aggregate label, then PRODIGY delta G, then D-SCRIPT probability, while still showing raw values.

## MVP Demo Workflow

The primary demo prompt is:

> Generate a protein that binds to 3CL-protease.

MVP scope is exactly one complete loop:

1. Understand the biological target and normalize entities for 3CL-protease.
2. Search literature, especially bioRxiv/PubMed/PMC, for target biology, known inhibitors, interfaces, and design-relevant residues.
3. Search and filter PDB structures for suitable target structures.
4. Prepare the selected target CIF/mmCIF artifact and identify target input ranges/hotspots.
5. Call Proteina-Complexa to generate binder candidates against the selected target.
6. Extract candidate sequences and store generated PDB artifacts.
7. Call Chai-1 in parallel to fold candidate sequences into ranked CIF predictions.
8. Call protein interaction scoring for generated target-binder pairs.
9. Display target, Proteina outputs, Chai folds, and score results as selectable artifacts and candidate cards.
10. Produce a ranked summary of the most promising candidates, with caveats.

This is enough for the full demo path. The agent must still frame results as computational screening, not confirmed binding. UI copy should say "interaction score", "predicted delta G", "D-SCRIPT probability", or "screening indicator"; it should not imply experimental validation.

Phase 2 is tree-based discovery: score candidates, select promising branches, mutate or warm-start from those branches, generate another batch, and iterate with BFS-like exploration. The schema should preserve lineage now, but MVP implementation should stop after the first scored generation/folding batch.

## Product Shell

The first screen is the workspace. Do not create a landing page.

### Left Panel

Replace the existing goal prompt, examples, assistant, best match, and "what's ready" sections with one chat panel:

- conversation scroll area
- empty-state example goals before the first message
- progress events rendered inline under the active assistant turn
- collapsible tool, command, reasoning, and artifact cards
- prompt composer pinned to the bottom
- attachment button
- recipe picker
- settings/options button
- context chips for selected protein regions, artifacts, candidates, and uploaded files

Ranked PDB structures and research trace no longer live as separate right-side panels. They appear as structured tool results in the assistant run trace.

### Center Stage

Mol* is the main workspace surface.

- Reduce top padding and oversized status chrome.
- Move viewer actions into four compact in-view controls: fullscreen, download/export, reset camera, and viewer settings.
- Remove the ambiguous current five-option overlay unless a control is proven useful.
- Keep the loaded structure filename/artifact visible but compact.
- Make the viewer visually larger than every surrounding panel.

### Right Panel

The right panel becomes a compact design journey and workspace summary:

- current objective
- current selected structure/artifact
- major milestones
- active run status
- next recommended action
- important artifacts

It should not duplicate raw trace, ranked structures, or detailed tool output. Those belong in the chat trace.

For generation workflows, the right panel should also include a compact candidate tree:

- root: target structure
- child batch: Proteina generation
- candidate leaves: generated PDBs and extracted sequences
- fold children: Chai CIF predictions
- score leaves: D-SCRIPT probability, PRODIGY delta G, and aggregate label
- MVP stop marker after the first scored batch
- phase-2 affordance for "branch again" disabled or marked future

The tree is a navigation and status surface, not a dense data table. Candidate cards should show the aggregate label, D-SCRIPT probability, PRODIGY delta G, and fold confidence without hiding warnings or partial scorer failures. Detailed payloads stay in collapsible chat/tool trace cards.

## Mol* Context References

Clicking or selecting part of a protein in Mol* should create a structured context reference that can be inserted into the composer.

The selection adapter should map Mol* loci into:

- artifact ID
- candidate ID when available
- structure ID
- model ID
- chain/auth asym ID
- residue IDs or ranges
- atom IDs when selection is atom-level
- human-readable label

Example chip labels:

- `6M0J chain A residues 333-527`
- `3CLpro catalytic dyad`
- `Chain B ligand pocket`

When the user sends a message, `context_refs_json` on the message stores the selected reference IDs. The worker resolves those references into agent context and can call `inspect_structure` or `run_biopython` before answering or mutating.

## Workspace Management

Add real workspace CRUD:

- create workspace
- list workspaces
- open workspace
- rename workspace
- archive/delete workspace

Navigation should make it obvious that separate Autopep agents may be working on separate tasks. Each workspace owns threads, runs, artifacts, recipes, context references, candidates, and sandbox state.

Deletion can be destructive for now because there are no users. The implementation should still avoid deleting Better Auth records and should delete or orphan R2 artifacts deliberately, not accidentally.

## Recipes

Recipes are Autopep's version of reusable agent skills.

They are markdown files or DB-backed markdown records with instructions such as:

> When generating a protein, first research similar structures in PDB and bioRxiv.

The UI should support:

- list recipes
- create recipe
- edit recipe
- enable/disable recipe for a workspace or prompt
- attach selected recipes to a run

At run start, the worker snapshots the enabled recipe bodies into run context. The SDK skills capability can be used to expose recipes as skill-like material, but Autopep must retain a product-level recipe registry so users can manage them without editing local files.

The Life Science Research plugin is not just another user recipe. It is platform-provided and always loaded.

## Error Handling And Approvals

Runs can pause or fail without losing context.

Run states:

- `queued`
- `running`
- `paused`
- `completed`
- `failed`
- `cancelled`

Pause conditions:

- tool approval required
- high-cost GPU or long timeout requested
- destructive workspace deletion requested
- ambiguous mutation target that cannot be safely inferred

Failure conditions:

- tool exception
- sandbox timeout
- missing artifact
- invalid CIF/mmCIF
- external API failure after retries
- model/run max-turn failure

Failures should preserve all events and partial artifacts. The UI should show a compact failed step with raw details expanded on demand.

## Security, Cost, And Operations

- Never run generated BioPython or shell commands on Vercel or the host machine.
- Keep OpenAI, Modal, Neon, and R2 credentials in provider environment variables or secrets.
- Default sandbox timeouts should be modest; expensive or long tasks require explicit approval later.
- Keep Modal GPU disabled for basic PDB/literature/CIF workflows.
- Persist artifacts and state before marking a run completed.
- Add cancellation support early enough to terminate or detach Modal sessions.
- Use spend limits on Modal and avoid always-on workers.
- Store enough run metadata to debug costs: model, token usage when available, sandbox runtime, artifact sizes, and tool durations.

## Delivery Tracks

Implement as one architecture spine with three specs/streams of work:

1. **Runtime, schema, tool, and event contract**
   - destructive Autopep schema migration
   - Python Agents SDK worker
   - `SandboxAgent` plus `ModalSandboxClient`
   - run/event/artifact persistence
   - model inference and candidate score persistence
   - cursor polling endpoint
   - Life Science Research plugin loading
   - initial tool wrappers

2. **Biology workflow**
   - PDB search/download
   - PubMed/PMC/bioRxiv search
   - CIF/mmCIF validation
   - prepared target artifact
   - BioPython inspection and simple mutation
   - Proteina-Complexa candidate generation
   - Chai-1 sequence folding
   - protein interaction scoring
   - ranked candidate events and artifacts

3. **Product shell**
   - unified chat panel
   - compact journey panel
   - larger Mol* stage
   - Mol* context references
   - workspace navigation and CRUD
   - recipe management UI
   - one-loop generation/folding/scoring candidate tree
   - trace cards for tools, commands, artifacts, candidates, scores, and errors

The implementation plan should start with track 1, because tracks 2 and 3 should render and consume the same durable contracts rather than inventing separate state paths.

## Testing Strategy

Required coverage:

- database migration and schema tests for new Autopep tables
- TypeScript contract tests for run/event/artifact APIs
- Python unit tests for event normalization from SDK stream events
- Python tests for biology tool wrappers using mocked RCSB, PubMed/PMC, and bioRxiv fixtures
- mocked Proteina-Complexa contract tests for target, warm-start, response, and error handling
- mocked Chai-1 contract tests for FASTA, sampling parameters, ranked CIF response, and error handling
- mocked protein interaction scoring contract tests for batch scoring, partial scorer availability, aggregate labels, and warnings
- mocked Modal sandbox tests for command stdout/stderr event streaming
- artifact persistence tests for R2-compatible storage adapters
- frontend component tests for chat trace event rendering
- browser-use flow test for workspace creation, prompt send, live progress rendering, artifact selection, Mol* loading, and Mol* context chip creation

Do not depend on real OpenAI, Modal, RCSB, PubMed, or R2 calls in the default local test suite. Use integration tests behind explicit environment flags.

## References Checked

- OpenAI Sandbox Agents: https://developers.openai.com/api/docs/guides/agents/sandboxes
- OpenAI Agents SDK streaming: https://openai.github.io/openai-agents-python/streaming/
- OpenAI streaming event reference: https://openai.github.io/openai-agents-python/ref/stream_events/
- Modal OpenAI Agents SDK blog: https://modal.com/blog/building-with-modal-and-the-openai-agent-sdk
- Modal OpenAI Agents SDK example: https://github.com/modal-labs/openai-agents-python-example
- Modal sandbox command streaming: https://modal.com/docs/guide/sandbox-spawn
- Vercel function limits: https://vercel.com/docs/functions/limitations
- Chai-1 endpoint implementation: `tools/chai-1`
- Proteina-Complexa endpoint implementation: `tools/proteina-complexa`
- Protein interaction scoring endpoint implementation: `tools/protein_interaction_scoring`
