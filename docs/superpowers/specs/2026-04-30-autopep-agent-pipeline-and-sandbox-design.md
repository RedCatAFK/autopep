# Autopep Agent — Pipeline, Sandbox, and Multi-Turn Design

**Date:** 2026-04-30
**Status:** Draft, awaiting user review
**Owner:** Chris Yoo
**Related specs:** `2026-04-28-agent-orchestration-pdb-retrieval-design.md`, `2026-04-29-autopep-agent-runtime-redesign-design.md`, `2026-04-29-autopep-e2e-completion-design.md`

## Problem statement

The current Autopep agent ([autopep/modal/autopep_agent/runner.py](../../../autopep/modal/autopep_agent/runner.py)) cannot end-to-end execute the demo pipeline a user expects when they type *"generate a protein to bind to X"*.

Concretely:

- The agent has only 5 hand-rolled function-tools and lacks a PDB-search tool entirely; the only RCSB query in the codebase lives inside a deterministic `demo_pipeline.execute_demo_one_loop` that is hardcoded to SARS-CoV-2 3CL-protease and is unreachable from the chat UI today.
- There is no way for the agent to execute Python or shell commands, so it cannot inspect PDB/CIF files, manipulate sequences, or compute hotspot residues itself.
- Proteina is called with `nsamples=1` instead of returning candidates as a batch.
- Chai folds candidates sequentially; quality-scorers (solubility, expressibility, plausibility) exist as a Modal app but are never called.
- The agent has no conversation memory: each new chat message starts the agent stateless, so multi-turn workflows ("fold candidate-2 with a tighter MSA cap") cannot resolve prior-turn entities.
- The "life-sciences-research plugin" referenced in NOTES.md is just one prompt sentence, not an actual `Skills` capability.
- Streaming of tokens and tool-call events exists in plumbing but has not been verified end-to-end against the OpenAI Agents SDK's `SandboxAgent`/`Capabilities` event shapes.

## Goals

1. The agent can drive the full demo pipeline end-to-end via tools (literature → PDB → Proteina → Chai → score → ranked summary) for an arbitrary target named by the user.
2. The agent can execute arbitrary Python/shell in a Modal sandbox to inspect and manipulate PDB/CIF files (read sequences, compute hotspots, splice motifs, etc.).
3. Multi-turn conversation works across messages and across multiple workspaces, with the agent able to reference prior-turn entities (candidate ids, PDB ids, scores) without restating them.
4. Token streaming and tool-call event streaming are verified to actually work against the deployed stack, with assertions in regression tests.
5. The architecture is forward-compatible with a tree-based design phase (orchestrator + subagents using Proteina warm-start), without locking in that pattern now.
6. Every phase is validated against the deployed Neon + Modal + Vercel stack before being declared done.

## Non-goals

- **Subagent / orchestrator pattern.** A multi-agent shape with `spawn_subagent`/`invoke_subagent` tools and per-subagent fresh sandboxes is not implemented in this spec. The architecture is forward-compatible — the schema, tool shapes, and capability composition leave room for it — but it is deferred to the tree-search phase.
- **Filesystem snapshots.** Modal's `session.snapshot_filesystem()` for forking sandbox state into branches is not used. We have no expensive shared-setup phase to snapshot from.
- **Sandbox resume across runs.** `RunState`/`session_state` serialization for paused/resumable runs is not implemented. Our runs are bounded (~minutes) with no human-in-the-loop pauses.
- **`Memory` capability.** Cross-run learned memory (e.g. `MEMORY.md`) is not added. May come later.
- **GPU on the sandbox itself.** Model inference goes through dedicated Modal model apps via the function-tools. The sandbox is CPU-only.
- **Wet-lab handoff / FASTA export.** Future addition; out of scope.

## Architecture overview

### Today (state before this spec)

- One `agents.Agent` per run. Five function-tools (`search_pubmed_literature`, `search_europe_pmc_literature`, `generate_binder_candidates`, `fold_sequences_with_chai`, `score_candidate_interactions`).
- Manual workspace-volume + R2 download plumbing in `_download_attachments_to_inputs`.
- Deterministic `demo_pipeline.execute_demo_one_loop` for `task_kind="branch_design"` — unreachable from chat (only test scripts route to it). Hardcoded for 6LU7 chain A.
- Dead `choose_task_kind` function. Conversation memory not implemented (`Runner.run_streamed` called without `session=`).
- `_flush_assistant_message` partial assistant-text persistence webhook.
- `messages` table holds user/assistant chat rows but not tool-call traces.
- Streaming plumbing exists (Modal Queue for token deltas, `agent_events` ledger for structured events) but unverified against the SDK.

### After (target state)

One `SandboxAgent` per run, configured as:

```python
agent = SandboxAgent(
    name="Autopep",
    model=run_context.model,
    instructions=build_agent_instructions(enabled_recipes),
    default_manifest=Manifest(
        entries={
            "workspace": R2Mount(
                bucket=config.r2_bucket,
                prefix=f"workspaces/{workspace_id}/",
                # credentials via mount entry, not in prompt
            ),
        },
        environment={"WORKSPACE_RUN_ID": run_id},
    ),
    capabilities=Capabilities.default() + [
        Skills(from_=LocalDir(src="/skills/life-science-research")),
    ],
    tools=[
        literature_search,
        pdb_search,
        pdb_fetch,
        proteina_design,
        chai_fold_complex,
        score_candidates,
    ],
)

result = await Runner.run_streamed(
    agent,
    input=prompt,
    session=PostgresSession(thread_id),
    run_config=RunConfig(
        sandbox=SandboxRunConfig(
            client=ModalSandboxClient(),
            options=ModalSandboxClientOptions(
                app_name="autopep-agent-runtime",
                timeout=SANDBOX_TIMEOUT_SECONDS,
            ),
        ),
        ...
    ),
)
```

Key shifts:

- `Capabilities.default()` provides `Filesystem()` (`apply_patch`, `view_image`) and `Shell()` (full command execution) and `Compaction()`. The "execute arbitrary Python in our sandbox" requirement is satisfied without a custom function-tool.
- `R2Mount` mounts the workspace's R2 prefix at `/workspace/`. Tools and the agent's `Shell` read/write through normal file IO; bytes flow through R2 transparently.
- `Skills(from_=LocalDir(...))` points at curated life-science-research skill markdown checked into the repo at `autopep/modal/autopep_agent/skills/life-science-research/`.
- `PostgresSession(thread_id)` reads/writes `thread_items` rows so the agent sees full conversation history (including prior tool-call inputs and outputs) on every turn.
- The runner stops branching on `task_kind`. The `branch_design` deterministic pipeline is deleted (its constants are kept as named exports). `choose_task_kind` is deleted. The smoke task kinds (`smoke_chat`, `smoke_tool`, `smoke_sandbox`) remain.

## Schema overhaul

We have no production users yet, so destructive schema changes are acceptable.

### Drop

- **Table `messages`.** Holds only user/assistant text rows today. Replaced by `thread_items` which is the single source of truth for everything the LLM sees.
- **`_flush_assistant_message` helper** in `runner.py` plus its `/api/agent/messages` webhook route. Subsumed by `PostgresSession.add_items`.

### Add

- **Table `thread_items`** mirroring the OpenAI Agents SDK item shape:

  ```sql
  CREATE TABLE thread_items (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       UUID        NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    run_id          UUID        REFERENCES agent_runs(id) ON DELETE SET NULL,
    sequence        BIGINT      NOT NULL,
    item_type       TEXT        NOT NULL,
    role            TEXT,
    content_json    JSONB       NOT NULL,
    attachment_refs_json  JSONB,
    context_refs_json     JSONB,
    recipe_refs_json      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (thread_id, sequence)
  );
  CREATE INDEX thread_items_thread_id_seq_idx ON thread_items (thread_id, sequence DESC);
  CREATE INDEX thread_items_run_id_idx        ON thread_items (run_id);
  ```

  - `item_type ∈ {'message', 'function_call', 'function_call_output', 'reasoning', ...future SDK kinds}`.
  - `role ∈ {'user', 'assistant', 'system', 'tool'}` for messages, NULL otherwise.
  - `content_json` stores the literal SDK item; the SDK's session protocol round-trips through this.
  - Attachment/context/recipe refs are typed columns set only on user-message rows (NULL elsewhere).
  - `(thread_id, sequence)` is the durable ordering key.
  - `run_id` nullable so user-message rows can exist before a run is claimed.

### Why one table for all kinds (not separate `messages` + `session_items`)

- One source of truth — chat panel and SDK can't disagree.
- Tool-call traces appear in conversation history so turn N+1 can reference "candidate-2's solubility score" by reading turn N's `function_call_output` payload directly.
- Future SDK item kinds drop in without schema migration.
- `agent_events` (structured run-scoped trace ledger for live UI rendering) stays — it's a different reader: it captures things the LLM never sees (sandbox stdout deltas, lifecycle events) and is the source for the UI's live tool-call cards. `thread_items` and `agent_events` are not duplicates; they're projections of different cuts of the run.

### Touched code

- `autopep/src/server/db/schema.ts` — drop `messages`, add `threadItems`.
- `autopep/src/server/agent/project-run-creator.ts` — `insertUserMessage` → `insertUserThreadItem`.
- `autopep/src/server/api/routers/workspace.ts` — `mapMessage` → `mapThreadMessageItem`; queries filter by `item_type='message'`.
- `autopep/src/app/_components/build-stream-items.ts` — input prop type renamed; rendering unchanged.
- `autopep/modal/autopep_agent/session.py` — new `PostgresSession` class implementing the SDK Session protocol.
- `autopep/modal/autopep_agent/runner.py` — pass `session=PostgresSession(thread_id)` into `Runner.run_streamed`; delete `_flush_assistant_message`, `ASSISTANT_TEXT_BUFFERS`, `_accumulate_assistant_text`.
- `autopep/src/app/api/agent/messages/route.ts` — delete.

### Forward-compat with tree-search

Subagent runs each get their own `agent_run` with `rootRunId`/`parentRunId` (already in schema). Subagent transcripts can either share the orchestrator's `thread_id` (subagent activity appears inline as `function_call`/`function_call_output` items in the orchestrator's thread, mirroring the Modal blog example) or use a separate `thread_id` per subagent for branch isolation. The schema supports both — no further changes needed when subagents land.

## Tool surface

Six function-tools wrap our Modal model endpoints. Everything else (file IO, sequence manipulation, ad-hoc analysis) goes through `Capabilities.default()`'s `Shell` and `Filesystem`, so we don't add a `run_python` tool we don't need.

| Tool | Replaces | Signature | Notes |
|---|---|---|---|
| `literature_search` | `search_pubmed_literature` + `search_europe_pmc_literature` | `(query: str, max_results: int = 8)` | Europe PMC + PubMed in parallel via `asyncio.gather`. Europe PMC's `SRC:PPR` filter covers bioRxiv + medRxiv + arXiv preprints. Dedup by DOI then PMCID; merge sorted by recency. |
| `pdb_search` | (new) | `(query: str, max_chain_length: int = 500, top_k: int = 10, organism: str \| None = None)` | RCSB Search API. Reuses query-shape pattern from kept `demo_pipeline` constants, parameterized. `max_chain_length` becomes a chain-length terminal node. Returns `{pdb_id, title, organism, resolution, chain_lengths_by_id, method, ligand_ids}`. No download. |
| `pdb_fetch` | (new) | `(pdb_id: str, chain_id: str \| None = None)` | Downloads from `files.rcsb.org`, writes to `/workspace/runs/{run_id}/inputs/{pdb_id}.pdb` (R2-mounted), inserts `artifact` row, emits `artifact_created`. Extracts chain sequences. Returns `{artifact_id, sandbox_path, chain_id, sequence, all_chains}`. |
| `proteina_design` | `generate_binder_candidates` | `(target_pdb_path: str, hotspot_residues: list[str] = [], binder_length_min: int = 60, binder_length_max: int = 90, num_candidates: int = 5, warm_start_structure_path: str \| None = None)` | Reads `target_pdb_path` from mounted workspace (no PDB text in tool args). Bumps Proteina's `batch_size` and `nsamples` 1→5. `warm_start_structure_path` triggers existing `warm_start_overrides` machinery. Empty hotspots = unconstrained design. Writes 5 candidates to `/workspace/runs/{run_id}/proteina/candidate-{1..5}.pdb`, registers each artifact. |
| `chai_fold_complex` | `fold_sequences_with_chai` | `(candidate_ids: list[str], target_sequence: str \| None = None, target_name: str = "target")` | **Parallel via `asyncio.gather`** instead of sequential `for` loop. Always folds target+binder complex. Writes `/workspace/runs/{run_id}/folds/{candidate_id}-complex.cif`, registers `chai_result` artifact, links to candidate row. |
| `score_candidates` | `score_candidate_interactions` (extended) | `(target_name: str, target_sequence: str, candidate_ids: list[str])` | Fans out via `asyncio.gather` to `protein_interaction_scoring` (D-SCRIPT + Prodigy) **and** `quality-scorers` (solubility, expressibility, plausibility). Merge results keyed by candidate. Persists each scorer's output as a separate `candidate_scores` row. Returns merged matrix for the LLM to rank. |

**No `run_python` tool.** `Shell` from `Capabilities.default()` exposes a bash-like executor; the agent runs `python -c '...'` or `python /workspace/scripts/foo.py`. `Filesystem` exposes `apply_patch` and `view_image`. Together these subsume mutate-sequence, extract-chain, splice-motif, and any ad-hoc BioPython work.

### Sandbox image

`autopep-agent-runtime` Modal app: Python 3.12 + `biopython`, `numpy`, `pandas`, `requests`, `httpx`, `pyyaml`. R2Mount provides `/workspace/`. CPU-only.

### Skills

`autopep/modal/autopep_agent/skills/life-science-research/` is a curated subset of `openai/plugins/plugins/life-science-research/skills` checked into our repo (not git-cloned at sandbox-create time, for build hermeticity and editability). Covers literature-evidence discipline, primary vs secondary sources, citation hygiene, when-to-cite-uncertainty.

### System prompt

`build_agent_instructions` keeps existing prose (computational-screening-only, cite uncertainty, no wet-lab claims) but generalizes the workflow paragraph to:

> *For binder-design tasks, the typical loop is `literature_search` → `pdb_search` → `pdb_fetch` → optionally inspect the structure with shell + BioPython to identify hotspots → `proteina_design` → `chai_fold_complex` → `score_candidates` → present a ranked summary citing the literature you found and the artifacts you produced. You may iterate (e.g., warm-start Proteina from your best fold) within the same run.*

## Streaming verification

### Kept

- **Token deltas — Modal Queue side-channel.** `_push_token_delta` in [runner.py:162](../../../autopep/modal/autopep_agent/runner.py:162) puts each `response.output_text.delta` onto a per-run Modal Queue; Next.js `/api/agent/run-stream` SSE endpoint tails it. Sub-100ms latency.
- **Structured events — Postgres `agent_events` ledger.** `tool_call_started`, `tool_call_completed`, `tool_call_failed`, `sandbox_command_started`, `sandbox_command_completed`, `artifact_created`, `candidate_ranked` persist as durable rows; the workspace tRPC query reads them; `build-stream-items.ts` renders matched start→complete pairs as live tool-call cards.

### Deleted (in Phase 1, after `PostgresSession` lands)

- `_flush_assistant_message`, `ASSISTANT_TEXT_BUFFERS`, `_accumulate_assistant_text`, the `/api/agent/messages` route. Their job — durably persisting final assistant text — is now `PostgresSession.add_items`. **Phase 0 keeps these as a transitional bridge** writing into `thread_items` (instead of the deleted `messages` table) so chat works during the schema migration; Phase 1 removes them once the SDK-native session machinery replaces them.

### Suspect (verify in Phase 1 gate)

1. **Tool-call cards may not render until *after* the tool completes.** The `tool_called` event fires only when the model has finished emitting the function call. If Proteina takes 3 minutes, the user might see a frozen panel between "decided to call" and "started running". Mitigation if confirmed: emit a synthetic `tool_call_started` ledger row from inside each tool wrapper at the *start* of execution via a shared `with emit_tool_call_lifecycle(...)` context manager.
2. **`Shell` capability event shape unverified.** The smoke-test sandbox event coalescer at [streaming.py:32](../../../autopep/modal/autopep_agent/streaming.py:32) was written against the smoke path. Whether the SDK's `Shell` capability emits the same `sandbox_command_*` shape needs to be confirmed; if not, extend `extract_sandbox_event` and the normalizer.

### Verification additions to `scripts/smoke-roundtrip.ts`

New `--scenario backend-streaming` mode asserts:

1. First `assistant_token_delta` arrives within 5s of run claim.
2. Tool-call cards appear in `agent_events` in the right order, with `started.created_at < completed.created_at`.
3. `proteina_design`'s started→completed gap is realistic (>5s) — i.e. the started event is not synthesized at completion.
4. `Shell` capability calls produce `sandbox_command_started` before `sandbox_command_completed` and stdout is captured.

## Phase plan with deploy gates

**Hard rule:** a phase is not done until its gate scenario produces the asserted outcome on a clean run **against the deployed Neon + Modal + Vercel stack**. Local-dev is for iteration. The gate is the deployed environment.

### Per-phase deployment ritual (added to the close of every phase)

1. **Neon (schema):** `bun --cwd autopep run db:push` against the production Neon branch. Verify with `db:studio` or `psql` that tables match the spec.
2. **Modal (worker + sandbox image + tool apps):**
   - `modal deploy autopep/modal/autopep_worker.py` for the agent runtime.
   - `modal deploy tools/<changed>/modal_app.py` for any tool app changed in this phase.
   - Verify each app via `modal app list` and the deployed app's health endpoint.
3. **Vercel (web):** push the phase branch, let preview deploy build, promote to production. Verify `/api/agent/run-stream` accepts SSE on the deployed URL.
4. **Run the phase's gate scenario against the *deployed* stack.** Test client → prod Vercel URL → prod Modal apps → prod Neon + prod R2.

A new helper script `autopep/scripts/deploy-and-validate.sh` runs steps 1–4 and exits non-zero on any failure. Each phase PR description includes the green output of this script as proof.

### Backend gate test extension

`scripts/smoke-roundtrip.ts` gets a `--target {local|prod}` flag. In `prod` mode it:

- Reads `AUTOPEP_PROD_BASE_URL` and `AUTOPEP_PROD_API_TOKEN` from env.
- Hits the deployed `sendMessage` tRPC mutation against prod.
- Tails `/api/agent/run-stream` over HTTPS.
- Reads `agent_events` and `thread_items` from prod Neon (read-only role) to assert durable side-effects.
- Cleans up: deletes test workspaces (named `smoke-test-{ts}-{rand}`) so prod doesn't accumulate.
- A weekly Modal cron scrubs anything matching the pattern older than 24h.

### Phases

| Phase | Work | Gate scenario | Pass criteria |
|---|---|---|---|
| **0. Schema reset + dead-code purge** | Drop `messages`, add `thread_items`. Repoint `project-run-creator` (user-message insert) and the existing `_flush_assistant_message` webhook to write to `thread_items` (with `item_type='message'`, role + content_json shape). Repoint `workspace.ts`, `build-stream-items`, chat-panel reads to `thread_items` filtered to `item_type='message'`. Delete `demo_pipeline.execute_demo_one_loop` orchestration and `branch_design` runner branch. Delete `choose_task_kind`. Keep `demo_pipeline` constants as named exports. (`_flush_assistant_message` / `/api/agent/messages` route stay in Phase 0 as a transitional bridge, deleted in Phase 1 when `PostgresSession` lands.) | Existing chat works end-to-end on one turn against prod with `thread_items` as the persistence target. | `bun run scripts/smoke-roundtrip.ts smoke_chat --target prod` green. UI smoke against prod: send "hi" in fresh workspace, get response, refresh page, both user and assistant rows present in `thread_items`. `grep -nE 'messagesTable\\|from \"@/server/db/schema\".*\\bmessages\\b' autopep/src` returns 0 results — i.e. no code imports the dropped Drizzle `messages` table. |
| **1. SandboxAgent base + multi-turn (S5)** | Build `autopep-agent-runtime` Modal sandbox image with biopython/numpy/pandas/httpx. Switch `build_autopep_agent` from `Agent` to `SandboxAgent` with `default_manifest=Manifest(entries={"workspace": R2Mount(...)}, environment={...})`, `Capabilities.default()`. Implement `PostgresSession` (`get_items` reads `thread_items` ordered by sequence; `add_items` inserts new rows during the streamed run for `function_call`, `function_call_output`, `reasoning`, and `message` items). Wire `Runner.run_streamed(..., session=PostgresSession(thread_id))`. Now that `PostgresSession.add_items` durably persists assistant text via the SDK's normal item completion, **delete `_flush_assistant_message`, `ASSISTANT_TEXT_BUFFERS`, `_accumulate_assistant_text`, and the `/api/agent/messages` route**. Existing 5 function-tools stay as-is for this phase. | **(S5) Multi-turn coherence on prod.** Send "Generate a binder for SARS-CoV-2 spike RBD". Wait for completion. Send "What was the top candidate's solubility score?". Send "Now show me what residues 40-60 look like in the fold for that candidate" — without restating the candidate or target. Switch to a new workspace. Send "hi". Switch back. Send "Remind me which PDB ID we used for the target." | All four follow-up responses correctly reference prior-turn entities by reading `thread_items` via `PostgresSession`. The sandbox `Shell` capability is exercised at least once (verified by `sandbox_command_started`/`completed` event pair in `agent_events`). Token deltas arrive over SSE within 5s of run claim. The `/api/agent/messages` route returns 404 on the deployed Vercel URL. |
| **2. literature_search consolidation + Skills capability (S1)** | Add `literature_search` tool fanning out to Europe PMC + PubMed via `asyncio.gather`, dedup by DOI/PMCID. Delete `_search_pubmed_literature` and `_search_europe_pmc_literature`. Curate skills under `autopep/modal/autopep_agent/skills/life-science-research/`. Add `Skills(from_=LocalDir(...))` to capabilities. Update `build_agent_instructions`. | **(S1) "Find literature about EGFR small-molecule inhibitor preprints from the last year."** | `literature_search` called once with sensible query. Results merge bioRxiv/medRxiv/PMC/PubMed with no duplicate DOIs. Final assistant message cites ≥3 references with DOIs and inline links. Skill markdown for citation-hygiene loaded (verified by `Skills` capability event in trace). Old tool names absent from new ledger rows. |
| **3. PDB tools (S2)** | Implement `pdb_search` and `pdb_fetch`. Reuse RCSB query JSON from kept `demo_pipeline` constants. `max_chain_length` defaults to 500. `pdb_fetch` writes to `/workspace/runs/{run_id}/inputs/`, registers `pdb` artifact, returns extracted target sequence. | **(S2) "Search the PDB for human ACE2 ectodomain structures and show me the highest-resolution one."** | `pdb_search` returns ≥3 candidate IDs filtered by chain length <500. Agent calls `pdb_fetch` on chosen one. `pdb` artifact appears in Files panel. Sequence in chat-panel response. Artifact opens in Mol*. |
| **4. Proteina batch-of-5 + warm-start, parallel Chai (S3)** | Bump Proteina overrides from 1/1 → 5/5 in [endpoint_clients.py:8-15](../../../autopep/modal/autopep_agent/endpoint_clients.py:8). Add optional `warm_start_structure_path` arg to `proteina_design`. Convert `_fold_sequences_with_chai`'s sequential loop ([biology_tools.py:281](../../../autopep/modal/autopep_agent/biology_tools.py:281)) to `asyncio.gather`. Tool always folds target+binder complex. | **(S3) Upload a `.pdb` file via chat composer's Paperclip control. Send: "Fold this sequence with Chai and visualise the result alongside the target sequence: [paste a binder candidate sequence]."** Plus the dual proteina batch test: a separate prompt "design 5 binders for [target]" must produce 5 distinct candidates from one Proteina call. | Uploaded artifact mounts at `/workspace/inputs/<file>.pdb` and is read by `chai_fold_complex`. A complex CIF artifact renders in Mol* with both chains in different colors. Proteina called with `nsamples=5`, returns 5 distinct candidates, each persisted as `proteina_result` artifact. |
| **5. Parallel score wiring + ranking final message (S4)** | Wire `tools/quality-scorers` into `score_candidates`. Tool fans out via `asyncio.gather` to (a) `protein_interaction_scoring` and (b) `quality-scorers`. Merge results, persist per-scorer rows. Update `build_agent_instructions` to require a final ranked summary referencing each scorer dimension. | **(S4) Full demo: "Generate a protein that binds to SARS-CoV-2 main protease (3CL-protease)."** | Tool-call sequence in `agent_events`: `literature_search`, `pdb_search`, `pdb_fetch`, (optional `Shell`), `proteina_design` (returns 5), `chai_fold_complex` (5 parallel folds), `score_candidates` (one call, both scorers parallel), final assistant message. Final message names a top candidate, lists scores by scorer, cites ≥2 literature references, mentions PDB target ID. Candidates table shows all 5 with all score columns populated. Run completes in <8 minutes. |
| **6. UI acceptance** | No new code unless 0–5 reveal UI defects. Pure validation phase. | **End-to-end UI walkthrough on prod.** Playwright test (or scripted manual run with committed screenshots) against deployed Vercel URL. Sign in with test account from env. Run S4. Verify live chat-panel, tool-call cards, Files panel, Mol* viewer, candidates table. Run S5 multi-turn follow-up. Open second workspace, run S1, switch back, verify state preserved. | Screenshots committed to `docs/superpowers/specs/screenshots/2026-04-30-...`. Playwright test asserts: chat-panel renders ≥1 token-delta-driven assistant text update in <5s, ≥6 tool-call cards present in chat, ≥5 candidates in candidates table, ≥1 Mol* viewer tab opened, ≥1 multi-turn follow-up references prior turn entities. |

### Branch / PR strategy

One feature branch per phase, opened against `main`. PR title pattern `feat(autopep): phase N — <title>`. Each PR description includes the gate scenario and a paste of the green `deploy-and-validate.sh` output. Phase 0 lands first, then 1, then 2, in strict order — no parallel phases.

## Implementation discipline

For every external API/library used in this work, confirm the latest interface shape via `context7` MCP (`mcp__plugin_context7_context7__query-docs`) and web search before writing code. Do not rely on training-data memory of API shapes. Specifically:

- **OpenAI Agents SDK** (`agents` Python package): confirm `SandboxAgent`, `Capabilities`, `Manifest`, `R2Mount`, `Skills`, `LocalDir`, `ModalSandboxClient`, `ModalSandboxClientOptions`, `Session` protocol, `Runner.run_streamed` argument shapes against the current pinned version. The Modal blog post at <https://modal.com/blog/building-with-modal-and-the-openai-agent-sdk> and example repo at <https://github.com/modal-labs/openai-agents-python-example> are the reference for Modal-specific integration.
- **Modal SDK** (`modal` Python package): confirm sandbox image build syntax, `App.cls` decorators, `Volume` and `Queue` APIs.
- **Drizzle ORM** (`drizzle-orm`): confirm `pgTable` column types, `jsonb` vs `json`, FK + cascade syntax, `db:push` behavior on Neon.
- **OpenAI Agents SDK Sessions**: confirm `Session.get_items()` / `add_items()` / `clear_session()` signatures and the exact item-shape contract for `function_call` vs `function_call_output` vs `reasoning` items.
- **BioPython** (`Bio.PDB`): for any PDB parsing in the agent's `Shell` calls or in our `pdb_fetch` tool's sequence extraction.
- **Playwright** for the Phase 6 UI test.

When in doubt, web-fetch the specific docs page rather than guessing.

## Risks

- **`SandboxAgent` + `R2Mount` cold-start latency** may add 5–15s to first-turn latency. Phase 1 gate's "tokens visible within 5s of run claim" assertion will surface this. Mitigation if needed: emit a "preparing workspace…" event at run claim so the user sees something while the sandbox boots.
- **`Shell` capability event-shape unknown.** Phase 1 gate exercises it; if mismatched, extend `extract_sandbox_event` and normalizer.
- **Quality-scorers Modal app currently unmaintained.** The trained classifier-head joblib files at `tools/quality-scorers/.../*.joblib` may not load with current `scikit-learn`/`joblib` versions. Phase 5 work includes a smoke test of the deployed scorer against a known sequence before wiring into `score_candidates`.
- **`thread_items.content_json` SDK-shape drift** if the SDK changes its item schema. Mitigation: pin `openai-agents` version in `requirements.txt`; bump deliberately with a verification test.
- **Prod-mode smoke test pollution.** Mitigation: name all test workspaces `smoke-test-{timestamp}-{random}`, scope cleanup to that pattern, weekly Modal cron scrubs anything matching the pattern older than 24h.

## Future work (architecture supports, not in this spec)

- **Tree-based protein design with subagents.** Add an `OrchestratorAgent` (a second `SandboxAgent` with `spawn_subagent`/`invoke_subagent` tools and no Shell), a `SubAgentPool` modeled on the Modal blog example, optional `session.snapshot_filesystem()` for branch forking. `agent_runs.rootRunId`/`parentRunId` already in schema; `thread_items` schema already supports per-subagent threads.
- **`Memory` capability.** Distill cross-run lessons (e.g. "for protease targets, hotspot residues from `SITE` records work better than ligand-proximity heuristics") into a `MEMORY.md` the next run reads.
- **Sandbox resume across runs.** When a long Proteina run hits a human-in-the-loop checkpoint, `RunState` + `session_state` lets the user pause and resume.
- **Wet-lab handoff.** Export top candidates as ordering-ready FASTA + provenance pack — pure tool addition, no architecture change.

## Acceptance criteria

All six phases pass their gates against the deployed stack:

1. Phase 0 — schema reset, no regressions; `bun run scripts/smoke-roundtrip.ts smoke_chat --target prod` green.
2. Phase 1 — multi-turn coherence (S5) works on prod; sandbox `Shell` exercised on prod.
3. Phase 2 — literature search prompt (S1) works on prod.
4. Phase 3 — PDB search prompt (S2) works on prod.
5. Phase 4 — fold-uploaded-sequence prompt (S3) works on prod; Proteina returns 5 candidates in batch.
6. Phase 5 — full demo prompt (S4) works on prod with all scorers parallel and a final ranked summary.
7. Phase 6 — Playwright UI test green against prod, screenshots committed, multi-workspace switch verified.

Each phase PR is merged only with the green `deploy-and-validate.sh` output pasted into the description.
