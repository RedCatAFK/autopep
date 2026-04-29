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
- Add first-class workspaces, threads, recipes, context references, artifacts, and run lineage.
- Make Mol* selection a prompt context source so a user can refer to clicked protein regions.
- Preserve flexibility for later branching candidate-generation pipelines.

## Non-Goals

- Production billing, quotas, or team administration.
- Sequence generation tools such as ProteinMPNN, Chai, Boltz, Proteina, or custom binder generation in this phase.
- Wet-lab validation or medical/clinical claims.
- Perfect multi-agent branching optimization in the first implementation pass.
- A direct frontend connection to the OpenAI SDK stream as the only source of truth.

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
   - Owns file bytes: CIF/mmCIF, FASTA, raw search responses worth preserving, generated BioPython scripts, mutated structures, logs, thumbnails, and later generated structures.
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
- `kind`: `cif | mmcif | fasta | pdb_metadata | literature_snapshot | biopython_script | mutated_structure | log | image | other`
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
- `source`: `rcsb_pdb | alphafold | generated | uploaded | mutated`
- `structure_id`
- `chain_ids_json`
- `title`
- `score_json`
- `why_selected`
- `artifact_id`
- `metadata_json`
- `created_at`

`parent_candidate_id` supports future mutation lineage.

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

Each tool returns structured JSON plus any artifact IDs. Raw source payloads should be stored only when useful for audit/debugging; the UI should default to compact summaries.

Initial biology scope:

- Q&A chat grounded in current workspace context.
- Literature search through PubMed/PMC/bioRxiv where relevant.
- PDB search/download/visualization.
- CIF/mmCIF preparation and validation.
- BioPython execution for inspection and simple mutation tasks.

Later scope:

- sequence generation tools
- branch-and-bound candidate trees
- hierarchical validation
- model scoring
- generated protein lineage

The current schema already leaves room for those later phases through `parent_run_id`, `root_run_id`, and `parent_candidate_id`.

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
   - cursor polling endpoint
   - Life Science Research plugin loading
   - initial tool wrappers

2. **Biology workflow**
   - PDB search/download
   - PubMed/PMC/bioRxiv search
   - CIF/mmCIF validation
   - prepared target artifact
   - BioPython inspection and simple mutation
   - ranked candidate events and artifacts

3. **Product shell**
   - unified chat panel
   - compact journey panel
   - larger Mol* stage
   - Mol* context references
   - workspace navigation and CRUD
   - recipe management UI
   - trace cards for tools, commands, artifacts, candidates, and errors

The implementation plan should start with track 1, because tracks 2 and 3 should render and consume the same durable contracts rather than inventing separate state paths.

## Testing Strategy

Required coverage:

- database migration and schema tests for new Autopep tables
- TypeScript contract tests for run/event/artifact APIs
- Python unit tests for event normalization from SDK stream events
- Python tests for biology tool wrappers using mocked RCSB, PubMed/PMC, and bioRxiv fixtures
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
