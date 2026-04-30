# Autopep Agent — Pipeline, Sandbox & Multi-Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demo pipeline ("generate a protein to bind to X") work end-to-end via the agent, add Python sandbox execution, multi-turn conversation, parallel scoring, and a 5-candidate Proteina batch — all validated against the deployed Neon + Modal + Vercel stack.

**Architecture:** Switch the agent from a plain `Agent` to `SandboxAgent` with `Capabilities.default()` (Shell + Filesystem + Compaction) + `Skills` capability + `R2Mount` manifest. Replace 5 hand-rolled tools with 6 SDK-aligned ones (`literature_search`, `pdb_search`, `pdb_fetch`, `proteina_design`, `chai_fold_complex`, `score_candidates`). Drop the `messages` table; add `thread_items` as the single SDK Session source-of-truth. Implement `PostgresSession` so the SDK reads/writes conversation history directly from Postgres for multi-turn coherence.

**Tech Stack:** Python (`agents` SDK 0.x with sandbox extras, `modal`, `httpx`, `biopython`), TypeScript (Next.js 15, tRPC, Drizzle ORM v0.x, `vitest`), Postgres (Neon), Cloudflare R2, Modal serverless GPU. Playwright for Phase 6 UI tests.

**Spec reference:** [`docs/superpowers/specs/2026-04-30-autopep-agent-pipeline-and-sandbox-design.md`](../specs/2026-04-30-autopep-agent-pipeline-and-sandbox-design.md). Read it before starting.

**Implementation discipline (repeated from spec §Implementation discipline):** Before writing code that touches an external API/library, confirm the latest interface shape via `mcp__plugin_context7_context7__query-docs` and a web search. Don't rely on training-data memory of the OpenAI Agents SDK, Modal SDK, Drizzle, or BioPython surfaces. The Modal blog post at `https://modal.com/blog/building-with-modal-and-the-openai-agent-sdk` and example repo at `https://github.com/modal-labs/openai-agents-python-example` are canonical for Modal sandbox integration.

**Hard rule (repeated from spec §Phase plan):** **If a phase's gate scenario fails on the deployed stack, the phase is not done — fix the gap before moving on.** Local-dev passing is necessary but not sufficient. Each phase ends with `autopep/scripts/deploy-and-validate.sh` green output pasted into the PR description.

---

## File structure

This section enumerates every file the plan creates, modifies, or deletes. Read this before starting any phase so you understand the dependency graph.

### New files

**Python (Modal worker):**
- `autopep/modal/autopep_agent/session.py` — `PostgresSession` adapter implementing the OpenAI Agents SDK `Session` protocol against `thread_items`.
- `autopep/modal/autopep_agent/sandbox_image.py` — Modal image definition for the `autopep-agent-runtime` sandbox app (BioPython + numpy + pandas + httpx + pyyaml on Python 3.12).
- `autopep/modal/autopep_agent/literature_tools.py` — `literature_search` function-tool fanning out to PubMed + Europe PMC.
- `autopep/modal/autopep_agent/pdb_tools.py` — `pdb_search` and `pdb_fetch` function-tools.
- `autopep/modal/autopep_agent/scoring_tools.py` — `score_candidates` function-tool fanning out to interaction + quality scorers.
- `autopep/modal/autopep_agent/skills/life-science-research/` (directory containing `.md` skill files curated from `openai/plugins`).
- `autopep/modal/tests/test_session.py`
- `autopep/modal/tests/test_literature_tools.py`
- `autopep/modal/tests/test_pdb_tools.py`
- `autopep/modal/tests/test_scoring_tools.py`

**TypeScript (Next.js):**
- `autopep/scripts/deploy-and-validate.sh` — runs `db:push` → `modal deploy` (changed apps) → vercel deploy → prod-target smoke test.
- `autopep/tests/e2e/full-demo.spec.ts` — Playwright UI test for Phase 6 (path may differ depending on existing Playwright setup).

**Other:**
- `docs/superpowers/specs/screenshots/2026-04-30-*.png` — Phase 6 deliverables.

### Modified files

**Python (Modal worker):**
- `autopep/modal/autopep_agent/runner.py` — switch `Agent` → `SandboxAgent`, wire `PostgresSession`, delete `_flush_assistant_message`/`ASSISTANT_TEXT_BUFFERS`/`_accumulate_assistant_text`/`choose_task_kind`, delete `branch_design` task-kind branch.
- `autopep/modal/autopep_agent/biology_tools.py` — rename `_generate_binder_candidates` → `_proteina_design` with new signature (reads from path, batch-of-5, optional warm-start); rename `_fold_sequences_with_chai` → `_chai_fold_complex` with `asyncio.gather`; delete `_score_candidate_interactions` (moves to `scoring_tools.py`).
- `autopep/modal/autopep_agent/research_tools.py` — delete (replaced by `literature_tools.py`); leave the file with a deprecation shim only if any external code imports from it (no callers in our repo, so just delete).
- `autopep/modal/autopep_agent/demo_pipeline.py` — keep constants (`HOTSPOT_RESIDUES`, `_literature_query`, RCSB query JSON, `TARGET_NAME`, etc.) as named exports; delete `execute_demo_one_loop`.
- `autopep/modal/autopep_agent/endpoint_clients.py` — bump `PROTEINA_FAST_GENERATION_OVERRIDES` from 1/1 → 5/5; add optional `warm_start_structure` to `ProteinaClient.design`.
- `autopep/modal/autopep_agent/db.py` — drop `messages` helpers, add `thread_items` helpers (`insert_thread_item`, `select_thread_items`, `select_thread_items_for_session`).
- `autopep/modal/autopep_worker.py` — wire the new sandbox image; verify Modal app stays exposed at the same web endpoint.
- `autopep/modal/requirements.txt` — pin `openai-agents[modal]` to a known-good version; add anything missing for the sandbox image.
- `autopep/modal/tests/test_runner.py` — update for new tool list, `SandboxAgent`, `PostgresSession`.
- `autopep/modal/tests/test_biology_tools.py` — rewrite for the new tool signatures.

**TypeScript (Next.js):**
- `autopep/src/server/db/schema.ts` — drop `messages` + relations; add `threadItems`.
- `autopep/src/server/agent/project-run-creator.ts` — `insertUserMessage` → `insertUserThreadItem`.
- `autopep/src/server/api/routers/workspace.ts` — `mapMessage` → `mapThreadMessageItem`; queries that read user/assistant chat filter on `item_type='message'`.
- `autopep/src/app/_components/build-stream-items.ts` — input prop type renamed from `messages` to `threadMessageItems`.
- `autopep/src/app/_components/autopep-workspace.tsx` and any consumer — type updates.
- `autopep/src/app/api/agent/messages/route.ts` — kept in Phase 0 but rewritten to insert into `thread_items`; deleted in Phase 1.
- `autopep/scripts/smoke-roundtrip.ts` — add `--target prod` mode + `backend-streaming` scenario + S1/S2/S3/S4/S5 scenario shells.
- Tests in `autopep/src/**/*.test.ts*` — update for new types.

### Deleted files (final state by end of Phase 1)

- `autopep/src/app/api/agent/messages/route.ts` (deleted in Phase 1).
- `autopep/modal/autopep_agent/research_tools.py` (deleted in Phase 2).

---

## Per-phase parallelization map

Phases run **strictly sequentially** because each phase's gate scenario validates against the deployed stack and is a precondition for the next phase. Within each phase, work is decomposed into parallel tracks. **Tracks within a phase can be done by different subagents concurrently** (or in any order if working alone) up to the synchronization point at the end of the phase.

| Phase | Tracks | Sync point |
|---|---|---|
| 0 | A: schema migration → push to local + prod (gating). B: TS code reads/writes (after A). C: Python webhook rewrite to thread_items (after A). D: delete demo_pipeline orchestration + choose_task_kind + branch_design routing (independent). E: deploy-and-validate.sh skeleton (independent). | All-tracks-merge → run gate scenario on prod. |
| 1 | A: build sandbox Modal image. B: implement `PostgresSession`. C: extend smoke-roundtrip.ts with `--target prod` + `backend-streaming` scenario. **Then** D: switch agent to `SandboxAgent` (depends on A + B). **Then** E: delete old webhook + assistant-buffer code (depends on D). | After E. |
| 2 | A: curate skill markdown. B: implement `literature_search` tool. **Then** C: wire `Skills` capability + delete old research tools (depends on A + B). | After C. |
| 3 | A: implement `pdb_search`. B: implement `pdb_fetch`. **Then** C: wire both into agent's tool list. | After C. |
| 4 | A: bump Proteina overrides + add `warm_start_structure_path` arg. B: parallelize Chai with `asyncio.gather` + always-complex folding. **Then** C: rename tools in agent + tests. | After C. |
| 5 | A: smoke-test quality-scorers Modal app + repair `joblib` if broken. **Then** B: rewrite `score_candidates` to fan out to both endpoints (depends on A). C: system-prompt update for ranking (independent). | After B + C. |
| 6 | A: write Playwright test. B: capture committed screenshots. C: manual multi-workspace verification. | All converge. |

**Subagent dispatch tip:** within a phase, dispatch one subagent per track. Wait for all tracks to merge before running the phase gate. The phase gate is the only blocking sync; everything inside the phase is fan-out friendly.

---

## Phase 0: Schema reset + dead-code purge

**Goal:** Drop `messages`, add `thread_items`, repoint all reads/writes (TS + Python webhook), delete dead code from the deterministic `branch_design` path. Existing one-turn chat must keep working end-to-end against prod.

**Spec reference:** §Schema overhaul, §Phase plan Phase 0.

**Gate scenario (Phase 0):** `bun run scripts/smoke-roundtrip.ts smoke_chat --target prod` green; UI smoke against prod (send "hi" in fresh workspace, get response, refresh, both rows in `thread_items`); `grep -nE 'messagesTable|from "@/server/db/schema".*\bmessages\b' autopep/src` returns 0 results.

**Parallelization (within Phase 0):**
- **Track A (gating):** Tasks 0.1 → 0.2 → 0.3 (schema definition + drizzle generation + push). Everything else waits.
- **Track B (after A):** Tasks 0.4 → 0.5 → 0.6 → 0.7 (TS code: project-run-creator + workspace router + UI prop types + tests).
- **Track C (after A):** Tasks 0.8 → 0.9 (Python: db.py thread_items helpers + webhook route rewrite to thread_items).
- **Track D (independent, can run parallel to anything):** Tasks 0.10 → 0.11 → 0.12 (delete demo_pipeline orchestration + choose_task_kind + branch_design runner branch).
- **Track E (independent):** Task 0.13 (deploy-and-validate.sh skeleton).
- **Sync point:** Task 0.14 (deploy + run gate).

---

### Task 0.1: Define `thread_items` table in Drizzle schema

**Files:**
- Modify: `autopep/src/server/db/schema.ts:188-221` (replace `messages` block) and `:647-668` (replace `messageRelations`)

**Track A · gating · ~10 min**

- [ ] **Step 1: Read the current `messages` block + relations**

Run: `grep -nE "messages|messageRelations" autopep/src/server/db/schema.ts`

You'll see the `messages` table at line 188 and `messageRelations` near line 651. Read both blocks fully.

- [ ] **Step 2: Replace `messages` definition with `threadItems`**

In `autopep/src/server/db/schema.ts`, replace the entire `export const messages = createAutopepTable(...)` block (lines 188–221 in the current state) with:

```ts
export const threadItems = createAutopepTable(
	"thread_item",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		threadId: uuid("thread_id")
			.notNull()
			.references(() => threads.id, { onDelete: "cascade" }),
		runId: uuid("run_id").references(() => agentRuns.id, {
			onDelete: "set null",
		}),
		sequence: bigint("sequence", { mode: "number" }).notNull(),
		itemType: text("item_type", {
			enum: [
				"message",
				"function_call",
				"function_call_output",
				"reasoning",
			],
		}).notNull(),
		role: text("role", { enum: ["user", "assistant", "system", "tool"] }),
		contentJson: jsonb("content_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		attachmentRefsJson: jsonb("attachment_refs_json").$type<string[]>(),
		contextRefsJson: jsonb("context_refs_json").$type<string[]>(),
		recipeRefsJson: jsonb("recipe_refs_json").$type<string[]>(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [
		index("autopep_thread_item_thread_seq_idx").on(t.threadId, t.sequence),
		index("autopep_thread_item_run_idx").on(t.runId),
		unique("autopep_thread_item_thread_seq_unique").on(
			t.threadId,
			t.sequence,
		),
	],
);
```

Note: `bigint` import. Add `bigint` to the import line at the top of the file alongside `uuid`, `text`, `jsonb`, etc.

- [ ] **Step 3: Replace `messageRelations` with `threadItemRelations`**

Replace the `messageRelations` block (around line 651) with:

```ts
export const threadItemRelations = relations(threadItems, ({ one }) => ({
	thread: one(threads, {
		fields: [threadItems.threadId],
		references: [threads.id],
	}),
	run: one(agentRuns, {
		fields: [threadItems.runId],
		references: [agentRuns.id],
	}),
}));
```

And update the `threadRelations` block (around line 647) — the `many(messages)` becomes `many(threadItems)`:

```ts
// inside threadRelations:
threadItems: many(threadItems),
```

Also: the `agentRuns` relations file may reference `messages` — `grep -n 'messages' autopep/src/server/db/schema.ts` and update any remaining references (e.g. `messages: many(messages)` inside `agentRunRelations`) to `threadItems: many(threadItems)`.

- [ ] **Step 4: Verify the file compiles**

Run: `bun --cwd autopep run typecheck` (if no `typecheck` script, use `bun --cwd autopep tsc --noEmit -p tsconfig.json`).

Expected: passes for the schema file. Other files will have errors referencing `messages` — that's fine for now; later tasks fix them.

- [ ] **Step 5: Commit**

```bash
git add autopep/src/server/db/schema.ts
git commit -m "feat(autopep): replace messages table with thread_items in schema

Drops the user-facing-only messages table and replaces with a
polymorphic thread_items table that mirrors the OpenAI Agents SDK
Session item shape (message, function_call, function_call_output,
reasoning). This is the single source of truth that PostgresSession
will read/write in Phase 1.

Refs: docs/superpowers/specs/2026-04-30-autopep-agent-pipeline-and-sandbox-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 0.2: Generate + apply Drizzle migration to local Neon

**Files:**
- Create: `autopep/drizzle/<auto-generated>.sql`

**Track A · gating · ~5 min**

- [ ] **Step 1: Generate the migration**

Run: `bun --cwd autopep run db:generate` (if no `db:generate` script, use `bun --cwd autopep drizzle-kit generate`).

Inspect the generated SQL — it should `DROP TABLE "autopep_message"` and `CREATE TABLE "autopep_thread_item" (...)`.

- [ ] **Step 2: Confirm the SQL matches expectations**

Run: `cat autopep/drizzle/<latest>.sql`

Verify:
- A `DROP TABLE "autopep_message" CASCADE` (the cascade is needed because of FK from agentRuns/threads).
- A `CREATE TABLE "autopep_thread_item"` with the columns from Task 0.1.
- Two indexes (`autopep_thread_item_thread_seq_idx`, `autopep_thread_item_run_idx`).
- One unique constraint on `(thread_id, sequence)`.

If anything is off, fix `schema.ts` and re-run `db:generate` until correct.

- [ ] **Step 3: Push to local Neon (or local dev DB)**

Run: `bun --cwd autopep run db:push` against your local `DATABASE_URL`.

Expected: clean apply. If it complains about existing data in `autopep_message`, that's fine — `db:push` will drop it (we have no users yet).

- [ ] **Step 4: Verify with psql**

```bash
psql "$DATABASE_URL" -c "\d autopep_thread_item"
psql "$DATABASE_URL" -c "SELECT to_regclass('autopep_message');"  # should return NULL
```

- [ ] **Step 5: Commit**

```bash
git add autopep/drizzle/
git commit -m "feat(autopep): drizzle migration for thread_items"
```

---

### Task 0.3: Push schema to **production Neon**

**Track A · gating · ~3 min**

- [ ] **Step 1: Confirm DATABASE_URL points at prod**

Run: `cd autopep && env $(grep DATABASE_URL .env.production.local | xargs) drizzle-kit push` (or whatever the team's prod-push pattern is — check `autopep/scripts/` and `package.json`).

If unclear, ask a teammate before running. Production schema mistakes are recoverable but annoying.

- [ ] **Step 2: Verify with psql against prod**

```bash
psql "$PROD_DATABASE_URL" -c "\d autopep_thread_item"
```

Expected: table exists with all columns + indexes.

- [ ] **Step 3: No commit** — schema state is on the cloud, not in git. Note the timestamp in your phase notes.

---

### Task 0.4: Rewrite `project-run-creator.ts` to insert `thread_items`

**Files:**
- Modify: `autopep/src/server/agent/project-run-creator.ts:286-298`

**Track B · after A · ~10 min**

- [ ] **Step 1: Read the existing user-message insert**

Open `autopep/src/server/agent/project-run-creator.ts`. Find the `await writeDb.insert(messages).values({...})` block around line 286.

- [ ] **Step 2: Replace with `threadItems` insert**

Replace the block with:

```ts
const [threadItem] = await writeDb
	.insert(threadItems)
	.values({
		threadId: workspaceBundle.thread.id,
		runId: run.id,
		sequence: await nextThreadSequence(writeDb, workspaceBundle.thread.id),
		itemType: "message",
		role: "user",
		contentJson: { type: "input_text", text: input.prompt },
		attachmentRefsJson: input.attachmentRefs ?? [],
		contextRefsJson: input.contextRefs ?? [],
		recipeRefsJson: input.recipeRefs ?? [],
	})
	.returning();

if (!threadItem) {
	throw new Error("Failed to create user thread item.");
}
```

Update imports: replace `messages` import with `threadItems`. Add a `nextThreadSequence` helper (next step).

Update the return value: the function returns `{ message, run, thread, workspace }` today. Rename `message` → `threadItem` in the return object and update consumers.

- [ ] **Step 3: Add `nextThreadSequence` helper**

In the same file, near the top:

```ts
const nextThreadSequence = async (
	db: typeof appDb,
	threadId: string,
): Promise<number> => {
	const [row] = await db
		.select({ max: sql<number>`coalesce(max(${threadItems.sequence}), 0)` })
		.from(threadItems)
		.where(eq(threadItems.threadId, threadId));
	return (row?.max ?? 0) + 1;
};
```

Add the necessary imports: `sql` from `drizzle-orm`, `threadItems` from `@/server/db/schema`.

- [ ] **Step 4: Update `createMessageRunWithLaunch`'s return type**

The function now returns `{ threadItem, run, thread, workspace }` instead of `{ message, run, thread, workspace }`. Update the return statement and the type annotations.

- [ ] **Step 5: Find and update callers**

```bash
grep -rn "createMessageRunWithLaunch\|createProjectRunWithLaunch" autopep/src
```

Update each caller's destructuring from `{ message }` → `{ threadItem }`. Most callers will only use `run` and `workspace`, so the change is small.

- [ ] **Step 6: Update the existing test file**

Open `autopep/src/server/agent/project-run-creator.test.ts`. Update test expectations to assert `threadItems` row was created with the right shape, not `messages`. The test code is yours to write — focus on:

```ts
test("inserts user thread item with content_json text", async () => {
	const result = await createMessageRunWithLaunch({ db, input: { prompt: "hello" }, ownerId });
	const items = await db.select().from(threadItems).where(eq(threadItems.threadId, result.thread.id));
	expect(items).toHaveLength(1);
	expect(items[0].itemType).toBe("message");
	expect(items[0].role).toBe("user");
	expect(items[0].contentJson).toMatchObject({ text: "hello" });
});
```

- [ ] **Step 7: Run the test**

```bash
bun --cwd autopep test src/server/agent/project-run-creator.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add autopep/src/server/agent/project-run-creator.ts autopep/src/server/agent/project-run-creator.test.ts
git commit -m "feat(autopep): repoint project-run-creator at thread_items"
```

---

### Task 0.5: Rewrite the workspace tRPC router for `thread_items`

**Files:**
- Modify: `autopep/src/server/api/routers/workspace.ts` (multiple sites — search for `messages`)

**Track B · after A · ~15 min**

- [ ] **Step 1: Find every reference**

```bash
grep -nE "messages|mapMessage|messagesTable" autopep/src/server/api/routers/workspace.ts
```

- [ ] **Step 2: Rename `mapMessage` → `mapThreadMessageItem`, update its signature**

The new function takes a `threadItems.$inferSelect` row and returns a chat-renderable message shape. Only rows where `item_type='message'` and `role IN ('user', 'assistant')` are renderable; the caller already filters.

```ts
const mapThreadMessageItem = (item: typeof threadItems.$inferSelect) => {
	const content = (item.contentJson as { text?: string } | null)?.text ?? "";
	return {
		id: item.id,
		role: item.role,
		content,
		runId: item.runId,
		threadId: item.threadId,
		createdAt: item.createdAt.toISOString(),
		attachmentRefsJson: item.attachmentRefsJson ?? [],
		contextRefsJson: item.contextRefsJson ?? [],
		recipeRefsJson: item.recipeRefsJson ?? [],
	};
};
```

- [ ] **Step 3: Update queries that read messages**

Each `db.query.messages.findMany(...)` or `db.select(...).from(messages)` becomes `from(threadItems)` with an additional filter:

```ts
.where(
	and(
		eq(threadItems.threadId, threadId),
		eq(threadItems.itemType, "message"),
		inArray(threadItems.role, ["user", "assistant"]),
	),
)
.orderBy(asc(threadItems.sequence))
```

- [ ] **Step 4: Update the returned shape names**

If the tRPC procedures return a `messages` field in their response object, keep the field name as `messages` for backward compatibility with the frontend, but populate it from `threadItems`-with-`item_type='message'`. (Renaming the response field would force UI changes; we'd rather fix this incrementally.)

- [ ] **Step 5: Update tests**

`autopep/src/server/api/routers/workspace.test.ts` (if it exists; otherwise skip). Update test fixtures to insert `threadItems` rows.

- [ ] **Step 6: Verify typecheck**

```bash
bun --cwd autopep tsc --noEmit -p tsconfig.json
```

Expected: 0 errors in `workspace.ts`.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/server/api/routers/workspace.ts autopep/src/server/api/routers/workspace.test.ts
git commit -m "feat(autopep): workspace router reads thread_items as chat messages"
```

---

### Task 0.6: Update UI components that consume the chat-message prop

**Files:**
- Modify: `autopep/src/app/_components/build-stream-items.ts`
- Modify: `autopep/src/app/_components/build-stream-items.test.ts`

**Track B · after A · ~5 min**

- [ ] **Step 1: Re-read the input prop type**

In `build-stream-items.ts`, the input prop is `messages: Message[]`. Since the wire response keeps the `messages` field name (Task 0.5 step 4), no rename is needed at this layer. **Verify no schema-shape change is needed** by checking what fields the `Message` type uses.

- [ ] **Step 2: Run existing build-stream-items tests**

```bash
bun --cwd autopep test src/app/_components/build-stream-items.test.ts
```

Expected: PASS (no changes needed if the wire response field name stayed `messages`).

If any test fails, it likely depends on a renamed schema field — fix accordingly.

- [ ] **Step 3: Verify chat-panel integration test**

```bash
bun --cwd autopep test src/app/_components/chat-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit (if anything changed)**

```bash
git add -A autopep/src/app/_components/
git commit -m "test(autopep): verify chat UI components after thread_items rename"
```

---

### Task 0.7: Add `bigint` import to schema if missing

**Track B · after A · ~2 min**

- [ ] **Step 1: Verify imports**

```bash
grep -n "bigint" autopep/src/server/db/schema.ts | head
```

If `bigint` is not in the import block at the top of `schema.ts`, add it. Search for the `import` from `drizzle-orm/pg-core` and add `bigint` to the list.

- [ ] **Step 2: Re-run typecheck**

```bash
bun --cwd autopep tsc --noEmit -p tsconfig.json
```

Expected: 0 errors.

- [ ] **Step 3: Commit (if changed)**

```bash
git add autopep/src/server/db/schema.ts
git commit -m "fix(autopep): add bigint import for thread_items.sequence"
```

---

### Task 0.8: Add `thread_items` helpers to Python `db.py`

**Files:**
- Modify: `autopep/modal/autopep_agent/db.py`

**Track C · after A · ~10 min**

- [ ] **Step 1: Read the current `db.py` to see the existing pattern**

```bash
head -100 autopep/modal/autopep_agent/db.py
```

Note the SQL helper conventions (likely `psycopg.AsyncConnection.execute` with parameterized SQL).

- [ ] **Step 2: Write a failing test for `insert_thread_item`**

Create or extend `autopep/modal/tests/test_db.py`:

```python
import pytest

from autopep_agent.db import insert_thread_item, select_thread_items_for_session


@pytest.mark.asyncio
async def test_insert_thread_item_persists_user_message(database_url: str, thread_id: str) -> None:
    item_id = await insert_thread_item(
        database_url,
        thread_id=thread_id,
        run_id=None,
        item_type="message",
        role="user",
        content_json={"type": "input_text", "text": "hello"},
    )
    assert item_id

    items = await select_thread_items_for_session(database_url, thread_id=thread_id)
    assert len(items) == 1
    assert items[0]["item_type"] == "message"
    assert items[0]["role"] == "user"
    assert items[0]["content_json"]["text"] == "hello"
```

(Use the existing test fixtures pattern — `conftest.py` in `autopep/modal/tests/` likely provides `database_url` and `thread_id`. If not, follow the existing test-DB-init pattern.)

- [ ] **Step 3: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_db.py::test_insert_thread_item_persists_user_message -v
```

Expected: FAIL with `ImportError: cannot import name 'insert_thread_item'`.

- [ ] **Step 4: Implement `insert_thread_item`, `select_thread_items_for_session`, `next_thread_sequence`**

In `autopep/modal/autopep_agent/db.py`:

```python
import json
from typing import Any

# follow existing connection pattern in this file
async def next_thread_sequence(database_url: str, thread_id: str) -> int:
    async with _connect(database_url) as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(MAX(sequence), 0) AS max_seq
            FROM autopep_thread_item
            WHERE thread_id = $1
            """,
            thread_id,
        )
    return int(row["max_seq"]) + 1


async def insert_thread_item(
    database_url: str,
    *,
    thread_id: str,
    run_id: str | None,
    item_type: str,
    role: str | None,
    content_json: dict[str, Any],
    attachment_refs_json: list[str] | None = None,
    context_refs_json: list[str] | None = None,
    recipe_refs_json: list[str] | None = None,
    sequence: int | None = None,
) -> str:
    """Insert one thread_items row. Returns the new id."""
    if sequence is None:
        sequence = await next_thread_sequence(database_url, thread_id)
    async with _connect(database_url) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO autopep_thread_item (
                thread_id, run_id, sequence, item_type, role, content_json,
                attachment_refs_json, context_refs_json, recipe_refs_json
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb)
            RETURNING id
            """,
            thread_id, run_id, sequence, item_type, role,
            json.dumps(content_json),
            json.dumps(attachment_refs_json) if attachment_refs_json is not None else None,
            json.dumps(context_refs_json) if context_refs_json is not None else None,
            json.dumps(recipe_refs_json) if recipe_refs_json is not None else None,
        )
    return str(row["id"])


async def select_thread_items_for_session(
    database_url: str,
    *,
    thread_id: str,
) -> list[dict[str, Any]]:
    """Return all items in this thread, ordered by sequence ASC, ready to feed into the SDK Session."""
    async with _connect(database_url) as conn:
        rows = await conn.fetch(
            """
            SELECT id, run_id, sequence, item_type, role, content_json,
                   attachment_refs_json, context_refs_json, recipe_refs_json, created_at
            FROM autopep_thread_item
            WHERE thread_id = $1
            ORDER BY sequence ASC
            """,
            thread_id,
        )
    return [
        {
            "id": str(r["id"]),
            "run_id": str(r["run_id"]) if r["run_id"] else None,
            "sequence": int(r["sequence"]),
            "item_type": r["item_type"],
            "role": r["role"],
            "content_json": r["content_json"],  # already a dict via psycopg jsonb
            "attachment_refs_json": r["attachment_refs_json"],
            "context_refs_json": r["context_refs_json"],
            "recipe_refs_json": r["recipe_refs_json"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
```

Adapt the connection pattern (`_connect`, `pool`, async context manager) to whatever the existing `db.py` uses. If the existing file uses `psycopg` (not `asyncpg`), use psycopg's parameter style (`%s` placeholders) instead.

- [ ] **Step 5: Drop the old `messages` helpers**

Search `db.py` for any function that reads/writes the `autopep_message` table. Delete those functions. Update any internal callers (likely none beyond `_flush_assistant_message` flow which is in `runner.py`).

- [ ] **Step 6: Run the test again**

```bash
cd autopep/modal && pytest tests/test_db.py::test_insert_thread_item_persists_user_message -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/modal/autopep_agent/db.py autopep/modal/tests/test_db.py
git commit -m "feat(autopep): db.py thread_items helpers, drop messages helpers"
```

---

### Task 0.9: Repoint the `/api/agent/messages` webhook to insert into `thread_items` (transitional)

**Files:**
- Modify: `autopep/src/app/api/agent/messages/route.ts`

**Track C · after A · ~5 min**

- [ ] **Step 1: Read the current route**

```bash
cat autopep/src/app/api/agent/messages/route.ts
```

It currently inserts into `messages` keyed off `(runId, role)`.

- [ ] **Step 2: Rewrite the insert to target `threadItems`**

Replace the insert with:

```ts
import { sql } from "drizzle-orm";
import { threadItems } from "@/server/db/schema";

// inside POST handler, replacing the messages.insert(...):
const sequence = await db
	.select({ max: sql<number>`coalesce(max(${threadItems.sequence}), 0)` })
	.from(threadItems)
	.where(eq(threadItems.threadId, body.threadId))
	.then((rows) => (rows[0]?.max ?? 0) + 1);

await db
	.insert(threadItems)
	.values({
		threadId: body.threadId,
		runId: body.runId,
		sequence,
		itemType: "message",
		role: "assistant",
		contentJson: { type: "output_text", text: body.content },
	})
	.onConflictDoNothing(); // matches the prior idempotent upsert behavior
```

If the prior implementation did a deterministic upsert (e.g. `ON CONFLICT (run_id, role)` to be replay-safe), preserve that intent — add a unique partial index in a follow-up migration if needed, OR rely on `runId + assistant` lookup before insert. For Phase 0 transitional we accept that the webhook may insert a duplicate assistant row on retry; Phase 1 deletes this route anyway.

- [ ] **Step 3: Hit the route locally to verify**

```bash
curl -X POST http://localhost:3000/api/agent/messages \
	-H "Content-Type: application/json" \
	-H "Authorization: Bearer $AUTOPEP_MODAL_WEBHOOK_SECRET" \
	-d '{"runId":"<test-run-id>","threadId":"<test-thread-id>","role":"assistant","content":"test","metadata":{}}'

psql "$DATABASE_URL" -c "SELECT item_type, role, content_json FROM autopep_thread_item ORDER BY created_at DESC LIMIT 1;"
```

Expected: row with `item_type='message', role='assistant', content_json={"type":"output_text","text":"test"}`.

- [ ] **Step 4: Commit**

```bash
git add autopep/src/app/api/agent/messages/route.ts
git commit -m "feat(autopep): webhook writes assistant text to thread_items (transitional)"
```

---

### Task 0.10: Delete `execute_demo_one_loop` orchestration; keep constants

**Files:**
- Modify: `autopep/modal/autopep_agent/demo_pipeline.py`

**Track D · independent · ~5 min**

- [ ] **Step 1: Read `demo_pipeline.py` to identify constants vs. orchestration**

Constants to KEEP:
- `TARGET_PDB_ID`, `TARGET_CHAIN_ID`, `TARGET_NAME`, `TARGET_PDB_URL`
- `PDB_SEARCH_URL`, `EUROPE_PMC_SEARCH_URL`
- `HOTSPOT_RESIDUES`, `BINDER_LENGTH_MIN`, `BINDER_LENGTH_MAX`
- `DEMO_RECIPE_NAME`, `DEMO_RECIPE_BODY`
- The query-construction helpers `_literature_query()`, `_pdb_search_query()` (the dict)
- `extract_pdb_sequences` re-export if it's imported from here (it's not — it lives in `structure_utils.py`)

Orchestration to DELETE:
- `execute_demo_one_loop` (the giant async function)
- `_search_literature`, `_search_pdb`, `_select_pdb_id`, `_fetch_target_pdb`, `_target_sequence`, `_target_input_for_sequence`, `_persist_target_artifact`, `_persist_json_artifact`, `_candidate_score_id`, `_best_candidate_from_scores` (these get re-implemented as proper tools in Phases 2–5; we don't keep half-implementations).

- [ ] **Step 2: Refactor the file**

Replace `demo_pipeline.py` with a slimmer version containing only constants:

```python
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
```

- [ ] **Step 3: Delete tests for the orchestration**

```bash
grep -rn "execute_demo_one_loop\|_search_literature\|_search_pdb" autopep/modal/tests
```

Delete or update tests that reference the deleted functions. Tests that exercise the constants should still pass — keep those.

- [ ] **Step 4: Run the modal test suite**

```bash
cd autopep/modal && pytest -x
```

Expected: PASS (or skips for tests that are pending Phase 1+).

- [ ] **Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/demo_pipeline.py autopep/modal/tests/
git commit -m "refactor(autopep): drop demo_pipeline orchestration, keep constants"
```

---

### Task 0.11: Delete `choose_task_kind` and the `branch_design` runner branch

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py:274-286, 814-845`
- Modify: `autopep/modal/tests/test_runner.py` (delete tests for these)

**Track D · independent · ~5 min**

- [ ] **Step 1: Locate the dead code**

```bash
grep -nE "choose_task_kind|branch_design|execute_demo_one_loop" autopep/modal/autopep_agent/runner.py
```

You'll see:
- The `choose_task_kind` function definition (~line 274–286).
- The `if task_kind == "branch_design":` block in `execute_run` (~line 814–845).
- An import of `execute_demo_one_loop` near the top.

- [ ] **Step 2: Delete `choose_task_kind`**

Remove the entire function (`def choose_task_kind(prompt: str) -> str:` and its body).

- [ ] **Step 3: Delete the `branch_design` branch in `execute_run`**

Remove the `if task_kind == "branch_design":` block and its body. Drop the `from autopep_agent.demo_pipeline import execute_demo_one_loop` import.

- [ ] **Step 4: Update test_runner.py**

```bash
grep -nE "choose_task_kind|branch_design" autopep/modal/tests/test_runner.py
```

Delete each test that exercises these. The tests at line ~41, ~48, ~313 in the current file are good candidates — read each test and delete cleanly.

- [ ] **Step 5: Run the test suite**

```bash
cd autopep/modal && pytest tests/test_runner.py -v
```

Expected: remaining tests PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_runner.py
git commit -m "refactor(autopep): delete choose_task_kind and branch_design routing"
```

---

### Task 0.12: Remove `branch_design` from the public TS task-kind enums

**Files:**
- Modify: `autopep/src/server/agent/contracts.ts:12-19`
- Modify: `autopep/src/server/db/schema.ts:118` (the `taskKind` enum on `agentRuns`)

**Track D · independent · ~3 min**

- [ ] **Step 1: Update the enums**

In `contracts.ts`, remove `"branch_design"` from `publicTaskKindSchema`. Keep it in `taskKindSchema` (the internal one) only if it's still referenced by historical DB rows; otherwise remove it from there too.

In `schema.ts`, the `taskKind` enum on `agentRuns` is at line ~118. Drop `"branch_design"` from the enum.

- [ ] **Step 2: Generate + apply the migration**

```bash
bun --cwd autopep run db:generate
# inspect the generated migration — should be an enum value drop or noop
bun --cwd autopep run db:push
```

Note: dropping enum values in Postgres is irreversible without a workaround. If `db:push` complains about existing rows with `branch_design`, run `UPDATE autopep_agent_run SET task_kind = 'chat' WHERE task_kind = 'branch_design';` first.

- [ ] **Step 3: Push the migration to prod Neon**

Same `db:push` against the prod URL. (Defer to Task 0.14 if you'd rather batch all schema changes.)

- [ ] **Step 4: Verify typecheck across the TS app**

```bash
bun --cwd autopep tsc --noEmit -p tsconfig.json
```

Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add autopep/src/server/agent/contracts.ts autopep/src/server/db/schema.ts autopep/drizzle/
git commit -m "refactor(autopep): remove branch_design from task kind enums"
```

---

### Task 0.13: `deploy-and-validate.sh` skeleton

**Files:**
- Create: `autopep/scripts/deploy-and-validate.sh`

**Track E · independent · ~10 min**

- [ ] **Step 1: Create the script**

```bash
mkdir -p autopep/scripts
```

`autopep/scripts/deploy-and-validate.sh`:

```bash
#!/usr/bin/env bash
# Deploy the current branch end-to-end and run the prod-target gate scenario.
#
# Usage: ./scripts/deploy-and-validate.sh <phase-number>
#   e.g. ./scripts/deploy-and-validate.sh 0
#
# Steps:
#   1. drizzle db:push to prod Neon
#   2. modal deploy of changed apps (autopep_worker + any tools/<app>/modal_app.py)
#   3. vercel deploy to production
#   4. run scripts/smoke-roundtrip.ts in --target prod mode for the phase's gate scenario

set -euo pipefail

PHASE="${1:?Usage: $0 <phase-number>}"
echo "==> Deploy + validate for Phase $PHASE"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 1. Schema push
echo "==> Step 1/4: drizzle db:push (prod Neon)"
if [ -z "${DATABASE_URL:-}" ]; then
	echo "DATABASE_URL must be set to the prod Neon URL"; exit 1
fi
bun run db:push

# 2. Modal deploy of changed apps
echo "==> Step 2/4: modal deploy"
modal deploy modal/autopep_worker.py
# Phase-specific tool deploys are added in later phases.

# 3. Vercel deploy
echo "==> Step 3/4: vercel --prod"
if ! command -v vercel >/dev/null; then
	echo "vercel CLI not found; install with 'npm i -g vercel'"; exit 1
fi
vercel --prod --yes

# 4. Run the prod-target smoke for this phase
echo "==> Step 4/4: smoke-roundtrip --target prod"
bun run scripts/smoke-roundtrip.ts "smoke_phase_${PHASE}" --target prod

echo "==> Phase $PHASE deploy + validate green ✓"
```

```bash
chmod +x autopep/scripts/deploy-and-validate.sh
```

- [ ] **Step 2: Verify the script runs the `--help` path cleanly**

```bash
cd autopep && bash -n scripts/deploy-and-validate.sh
```

Expected: no syntax errors. (Don't run it for real until Phase 0's gate at Task 0.14.)

- [ ] **Step 3: Commit**

```bash
git add autopep/scripts/deploy-and-validate.sh
git commit -m "feat(autopep): deploy-and-validate.sh skeleton"
```

---

### Task 0.14: Phase 0 gate — deploy + validate against prod

**Track ALL · sync point · ~20 min**

- [ ] **Step 1: Push the phase-0 branch + open a PR**

```bash
git push -u origin julia
# open a PR on GitHub: feat(autopep): phase 0 — schema reset + dead-code purge
```

- [ ] **Step 2: Run deploy-and-validate locally pointed at prod**

```bash
cd autopep && DATABASE_URL=<prod neon URL> ./scripts/deploy-and-validate.sh 0
```

This will:
1. Apply the `thread_items` migration to prod Neon.
2. Deploy `autopep_worker.py` to Modal.
3. Deploy the Next.js app to Vercel prod.
4. Hit the prod URL with a smoke `smoke_chat` task and assert it round-trips.

- [ ] **Step 3: Manual UI smoke against prod**

Open the deployed Vercel URL in a browser. Sign in. Send "hi" in a fresh workspace. Verify:
- Assistant response renders.
- Refresh the page — both the user "hi" and the assistant response are still rendered (i.e. they came from the DB on reload).

```bash
psql "$PROD_DATABASE_URL" -c "SELECT item_type, role, jsonb_extract_path_text(content_json, 'text') AS text FROM autopep_thread_item ORDER BY created_at DESC LIMIT 4;"
```

Expected: 2 rows (one user, one assistant) for the workspace you just used.

- [ ] **Step 4: Greppable assertion**

```bash
grep -nE 'messagesTable|from "@/server/db/schema".*\bmessages\b' autopep/src
```

Expected: 0 results.

- [ ] **Step 5: Paste the green output into the PR description and merge**

```bash
git checkout main
git pull
git branch -d julia  # only after the PR is merged
```

- [ ] **Step 6: Phase 0 done.** No code commit at this step — the merge is the artifact.

---
## Phase 1: SandboxAgent base + multi-turn

**Goal:** Switch the agent from `Agent` to `SandboxAgent` with `Capabilities.default()` (Shell + Filesystem + Compaction). Mount R2 at `/workspace/`. Implement `PostgresSession` so the SDK reads conversation history from `thread_items` on every turn. Delete the transitional assistant-text webhook.

**Spec reference:** §Architecture overview, §Schema overhaul (PostgresSession), §Phase plan Phase 1.

**Gate scenario (Phase 1, S5):** Multi-turn coherence on prod. Send "Generate a binder for SARS-CoV-2 spike RBD". Wait. Send "What was the top candidate's solubility score?". Send "Now show me what residues 40-60 look like in the fold for that candidate" — without restating the candidate or target. Switch to a new workspace. Send "hi". Switch back. Send "Remind me which PDB ID we used for the target." All four follow-ups correctly reference prior-turn entities. Sandbox `Shell` exercised at least once. Token deltas arrive over SSE within 5s of run claim. `/api/agent/messages` returns 404.

**Parallelization (within Phase 1):**
- **Track A:** Tasks 1.1 → 1.2 (sandbox Modal image definition + deploy).
- **Track B:** Tasks 1.3 → 1.4 → 1.5 (`PostgresSession` design + impl + tests).
- **Track C:** Tasks 1.10 → 1.11 (extend smoke-roundtrip with `--target prod` + `backend-streaming` scenario).
- **Then sequential:** Task 1.6 (switch agent to `SandboxAgent`, wire `R2Mount` manifest + `Capabilities.default()`, depends on A + B).
- **Then sequential:** Task 1.7 (delete `_flush_assistant_message`, ASSISTANT_TEXT_BUFFERS, etc.; depends on 1.6).
- **Then sequential:** Task 1.8 (delete `/api/agent/messages` route, depends on 1.7).
- **Then sequential:** Task 1.9 (Phase 1 gate).

---

### Task 1.1: Define the sandbox Modal image

**Files:**
- Create: `autopep/modal/autopep_agent/sandbox_image.py`

**Track A · ~10 min**

- [ ] **Step 1: Use context7 to confirm the latest `ModalSandboxClient` + `ModalSandboxClientOptions` signatures**

Run via the `mcp__plugin_context7_context7__query-docs` tool: query "openai-agents Python SDK ModalSandboxClient ModalSandboxClientOptions image". Skim the result. The Modal blog at <https://modal.com/blog/building-with-modal-and-the-openai-agent-sdk> shows the canonical pattern; the example repo at <https://github.com/modal-labs/openai-agents-python-example> is the authoritative reference.

- [ ] **Step 2: Create `sandbox_image.py`**

```python
"""Modal image definition for the autopep-agent-runtime sandbox.

The OpenAI Agents SDK's ModalSandboxClient launches sandboxes from a
Modal app named in ModalSandboxClientOptions(app_name=...). The app
must exist (be deployed) before the agent attempts to create a session.

This module both:
  1. Declares the image so it can be deployed via `modal deploy`.
  2. Exposes IMAGE_REF for use in autopep_worker.py.

The image bundles BioPython + numpy + pandas + httpx so the agent's
Shell capability can run real protein-engineering code without
per-run pip installs.
"""

from __future__ import annotations

import modal

SANDBOX_APP_NAME = "autopep-agent-runtime"

app = modal.App(SANDBOX_APP_NAME)

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl")
    .pip_install(
        "biopython>=1.84",
        "numpy>=1.26",
        "pandas>=2.2",
        "httpx>=0.27",
        "pyyaml>=6.0",
        "scipy>=1.13",
    )
)


@app.function(image=sandbox_image)
def _sandbox_warmup() -> str:
    """Health endpoint so `modal app list` shows the app as deployable."""
    return "ok"


if __name__ == "__main__":
    # `python sandbox_image.py` deploys the app for local testing.
    pass
```

- [ ] **Step 3: Verify the file is import-clean**

```bash
cd autopep && python -c "from modal.autopep_agent.sandbox_image import SANDBOX_APP_NAME, sandbox_image; print(SANDBOX_APP_NAME)"
```

Expected: `autopep-agent-runtime`.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/sandbox_image.py
git commit -m "feat(autopep): sandbox Modal image (BioPython + numpy + httpx)"
```

---

### Task 1.2: Deploy the sandbox image

**Track A · ~5 min**

- [ ] **Step 1: Deploy**

```bash
cd autopep && modal deploy modal/autopep_agent/sandbox_image.py
```

Expected: green output ending with "Deployed app autopep-agent-runtime".

- [ ] **Step 2: Verify visibility**

```bash
modal app list | grep autopep-agent-runtime
```

Expected: app listed with status "deployed".

- [ ] **Step 3: No commit** — Modal deploys are out-of-band artifacts.

---

### Task 1.3: `PostgresSession` — failing test first

**Files:**
- Create: `autopep/modal/tests/test_session.py`

**Track B · ~10 min**

- [ ] **Step 1: Confirm the SDK Session protocol shape**

Run via `mcp__plugin_context7_context7__query-docs`: "openai-agents Python Session protocol get_items add_items clear_session". The protocol defines:

```python
from agents import Session

class Session(Protocol):
    async def get_items(self) -> list[ResponseInputItem]: ...
    async def add_items(self, items: list[ResponseInputItem]) -> None: ...
    async def clear_session(self) -> None: ...
```

(Confirm exact types with context7 — `ResponseInputItem` is from `agents.types` or similar.)

- [ ] **Step 2: Write the failing test**

```python
"""Tests for PostgresSession — the SDK Session adapter against thread_items."""

from __future__ import annotations

import pytest

from autopep_agent.session import PostgresSession
from autopep_agent.db import insert_thread_item


@pytest.mark.asyncio
async def test_get_items_returns_prior_user_message_in_sdk_shape(
    database_url: str,
    thread_id: str,
) -> None:
    await insert_thread_item(
        database_url,
        thread_id=thread_id,
        run_id=None,
        item_type="message",
        role="user",
        content_json={"type": "input_text", "text": "hello"},
    )

    session = PostgresSession(database_url=database_url, thread_id=thread_id)
    items = await session.get_items()

    assert len(items) == 1
    assert items[0]["type"] == "message"
    assert items[0]["role"] == "user"
    assert any(c.get("text") == "hello" for c in items[0]["content"])


@pytest.mark.asyncio
async def test_add_items_persists_assistant_message(
    database_url: str,
    thread_id: str,
    run_id: str,
) -> None:
    session = PostgresSession(database_url=database_url, thread_id=thread_id, run_id=run_id)
    await session.add_items([
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hi back"}],
        }
    ])

    items_again = await session.get_items()
    assert len(items_again) == 1
    assert items_again[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_add_items_preserves_function_call_shape(
    database_url: str,
    thread_id: str,
    run_id: str,
) -> None:
    session = PostgresSession(database_url=database_url, thread_id=thread_id, run_id=run_id)
    await session.add_items([
        {
            "type": "function_call",
            "name": "literature_search",
            "arguments": '{"query": "EGFR inhibitors"}',
            "call_id": "call_abc123",
        },
        {
            "type": "function_call_output",
            "call_id": "call_abc123",
            "output": '{"results": [], "source": "pubmed"}',
        },
    ])

    items = await session.get_items()
    assert items[0]["type"] == "function_call"
    assert items[0]["name"] == "literature_search"
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "call_abc123"
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_session.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'autopep_agent.session'`.

- [ ] **Step 4: Commit the failing test**

```bash
git add autopep/modal/tests/test_session.py
git commit -m "test(autopep): failing tests for PostgresSession"
```

---

### Task 1.4: `PostgresSession` — implementation

**Files:**
- Create: `autopep/modal/autopep_agent/session.py`

**Track B · ~15 min**

- [ ] **Step 1: Implement the adapter**

```python
"""PostgresSession — SDK Session adapter persisting items in thread_items."""

from __future__ import annotations

from typing import Any, Mapping

from autopep_agent.db import insert_thread_item, select_thread_items_for_session


def _content_json_to_sdk_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a thread_items row's content_json back into an SDK input item.

    The content_json column stores the literal SDK item shape so a round-trip
    is identity. We re-attach the row-level role/item_type as a sanity check
    in case content_json was written by the transitional Phase 0 webhook,
    which only stored {"type": "...", "text": "..."}.
    """
    payload = dict(row["content_json"] or {})
    if row["item_type"] == "message" and "content" not in payload:
        text = payload.get("text", "")
        payload = {
            "type": "message",
            "role": row["role"],
            "content": [
                {
                    "type": "output_text" if row["role"] == "assistant" else "input_text",
                    "text": text,
                },
            ],
        }
    elif "type" not in payload:
        payload["type"] = row["item_type"]
    return payload


def _role_for_item(item: Mapping[str, Any]) -> str | None:
    item_type = str(item.get("type") or "")
    if item_type == "message":
        return str(item.get("role") or "assistant")
    if item_type == "function_call_output":
        return "tool"
    return None


class PostgresSession:
    """Session adapter compatible with `agents.Session` protocol.

    Reads thread_items rows ordered by sequence ASC; appends new items as
    new thread_items rows. Workspace isolation comes free because thread_id
    is unique per workspace's active thread.
    """

    def __init__(
        self,
        *,
        database_url: str,
        thread_id: str,
        run_id: str | None = None,
    ) -> None:
        self._database_url = database_url
        self._thread_id = thread_id
        self._run_id = run_id

    async def get_items(self) -> list[dict[str, Any]]:
        rows = await select_thread_items_for_session(
            self._database_url, thread_id=self._thread_id
        )
        return [_content_json_to_sdk_item(row) for row in rows]

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            item_type = str(item.get("type") or "message")
            await insert_thread_item(
                self._database_url,
                thread_id=self._thread_id,
                run_id=self._run_id,
                item_type=item_type,
                role=_role_for_item(item),
                content_json=dict(item),
            )

    async def clear_session(self) -> None:
        # Not used by Autopep flows; implemented for protocol completeness.
        # Delete via raw SQL to avoid loading every row into memory first.
        from autopep_agent.db import _connect  # type: ignore[attr-defined]

        async with _connect(self._database_url) as conn:
            await conn.execute(
                "DELETE FROM autopep_thread_item WHERE thread_id = $1",
                self._thread_id,
            )
```

If the SDK requires implementing a typed Protocol with concrete generics (e.g. `Session[ResponseInputItem]`), import the type and adjust signatures. Use `mcp__plugin_context7_context7__query-docs` to confirm.

- [ ] **Step 2: Run the tests**

```bash
cd autopep/modal && pytest tests/test_session.py -v
```

Expected: PASS for all three tests.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/session.py
git commit -m "feat(autopep): PostgresSession adapter for SDK multi-turn"
```

---

### Task 1.5: Property test — `(get_items → add_items → get_items)` round-trip

**Files:**
- Modify: `autopep/modal/tests/test_session.py`

**Track B · ~10 min**

- [ ] **Step 1: Add a round-trip test**

```python
@pytest.mark.asyncio
async def test_full_round_trip_preserves_item_order_and_payload(
    database_url: str,
    thread_id: str,
    run_id: str,
) -> None:
    """Items added in turn 1 are visible to turn 2's get_items in the same order."""
    session_turn_1 = PostgresSession(database_url=database_url, thread_id=thread_id, run_id=run_id)
    await session_turn_1.add_items([
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "design a binder for ACE2"}]},
        {"type": "function_call", "name": "pdb_search", "arguments": '{"query": "ACE2"}', "call_id": "c1"},
        {"type": "function_call_output", "call_id": "c1", "output": '{"results": [{"pdb_id": "6M0J"}]}'},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I found 6M0J."}]},
    ])

    session_turn_2 = PostgresSession(database_url=database_url, thread_id=thread_id)
    items = await session_turn_2.get_items()
    assert [it["type"] for it in items] == [
        "message", "function_call", "function_call_output", "message"
    ]
    assert items[1]["name"] == "pdb_search"
    assert items[2]["call_id"] == "c1"
    assert items[3]["role"] == "assistant"
```

- [ ] **Step 2: Run**

```bash
cd autopep/modal && pytest tests/test_session.py::test_full_round_trip_preserves_item_order_and_payload -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_session.py
git commit -m "test(autopep): round-trip test for PostgresSession item ordering"
```

---

### Task 1.6: Switch agent to `SandboxAgent` with `R2Mount` + `Capabilities.default()`

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py:289-340, 379-403, 880-915`

**Sequential · after Tasks 1.2 + 1.5 · ~25 min**

- [ ] **Step 1: Read the current `build_autopep_agent` and `_build_run_config`**

```bash
sed -n '289,340p;379,403p;880,915p' autopep/modal/autopep_agent/runner.py
```

You'll see:
- `build_agent_instructions()` building the system prompt.
- `build_autopep_agent(enabled_recipes)` creating an `Agent`.
- `_build_run_config()` building a `RunConfig` (with optional sandbox).
- `execute_run()` calling `Runner.run_streamed(agent, input=..., run_config=run_config)`.

- [ ] **Step 2: Confirm the SDK shape**

Use `mcp__plugin_context7_context7__query-docs` for: "openai-agents Python SandboxAgent Capabilities default Manifest R2Mount Skills LocalDir".

Confirm the import paths are still:
```python
from agents.sandbox import SandboxAgent, Manifest, SandboxRunConfig
from agents.sandbox.capabilities import Capabilities, Skills
from agents.sandbox.entries import R2Mount, LocalDir
from agents.sandbox.sandboxes.modal import ModalSandboxClient, ModalSandboxClientOptions
```

(If the SDK has moved these around in a recent release, adjust accordingly. Don't guess.)

- [ ] **Step 3: Rewrite `build_autopep_agent` to return a `SandboxAgent`**

Replace the existing function body:

```python
from agents.sandbox import SandboxAgent, Manifest
from agents.sandbox.capabilities import Capabilities, Skills
from agents.sandbox.entries import R2Mount, LocalDir

from autopep_agent.config import WorkerConfig
from autopep_agent.sandbox_image import SANDBOX_APP_NAME

SKILLS_DIR = "/app/autopep_agent/skills/life-science-research"


def build_autopep_agent(
    *,
    config: WorkerConfig,
    workspace_id: str,
    run_id: str,
    enabled_recipes: list[str] | None = None,
) -> SandboxAgent:
    return SandboxAgent(
        name="Autopep",
        instructions=build_agent_instructions(enabled_recipes),
        default_manifest=Manifest(
            entries={
                "workspace": R2Mount(
                    bucket=config.r2_bucket,
                    prefix=f"workspaces/{workspace_id}/",
                    access_key_id=config.r2_access_key_id,
                    secret_access_key=config.r2_secret_access_key,
                    account_id=config.r2_account_id,
                ),
            },
            environment={
                "WORKSPACE_RUN_ID": run_id,
                "WORKSPACE_ID": workspace_id,
            },
        ),
        capabilities=Capabilities.default() + [
            Skills(from_=LocalDir(src=SKILLS_DIR)),
        ],
        tools=[
            *RESEARCH_TOOLS,
            generate_binder_candidates,
            fold_sequences_with_chai,
            score_candidate_interactions,
        ],
    )
```

(The tool list stays unchanged for this phase — Phases 2–5 swap them out.)

If `R2Mount`'s exact constructor signature differs from what's shown above (Modal's R2 mount integration evolves), adjust based on context7's confirmation. The principle is: bucket + prefix + read/write credentials.

- [ ] **Step 4: Update `_build_run_config` to use `ModalSandboxClient`**

```python
from agents.sandbox.sandboxes.modal import ModalSandboxClient, ModalSandboxClientOptions

def _build_run_config(
    *,
    model: str,
    run_id: str,
    thread_id: str,
    workspace_id: str,
) -> RunConfig:
    return RunConfig(
        model=model,
        workflow_name="Autopep agent runtime",
        group_id=thread_id,
        trace_metadata={
            "run_id": run_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
        },
        sandbox=SandboxRunConfig(
            client=ModalSandboxClient(),
            options=ModalSandboxClientOptions(
                app_name=SANDBOX_APP_NAME,
                timeout=SANDBOX_TIMEOUT_SECONDS,
            ),
        ),
    )
```

Drop the existing `SandboxCompatibilityConfig` shim — we now require the modern SDK that supports sandbox config natively.

- [ ] **Step 5: Wire `PostgresSession` into the streamed run**

In `execute_run`, where the streaming run is invoked (around line 894):

```python
from autopep_agent.session import PostgresSession

# ... inside the agent-path branch:
agent = build_autopep_agent(
    config=config,
    workspace_id=workspace_id,
    run_id=run_id,
    enabled_recipes=run_context.enabled_recipes,
)
run_config = _build_run_config(
    model=run_context.model or config.default_model,
    run_id=run_id,
    thread_id=thread_id,
    workspace_id=workspace_id,
)
session = PostgresSession(
    database_url=database_url,
    thread_id=thread_id,
    run_id=run_id,
)
streamed_run = await _maybe_await(
    Runner.run_streamed(
        agent,
        input=_build_runner_input(
            prompt=run_context.prompt,
            run_id=run_id,
            task_kind=task_kind,
            thread_id=thread_id,
            workspace_id=workspace_id,
            attachment_paths=attachment_paths,
        ),
        run_config=run_config,
        session=session,
    ),
)
```

- [ ] **Step 6: Update `test_runner.py` for new signatures**

```bash
cd autopep/modal && pytest tests/test_runner.py -v
```

Most existing tests will fail (build_autopep_agent signature changed). For each failing test, update fixture setup to pass `config`, `workspace_id`, `run_id`. For tests that asserted `Agent` instance, change to `SandboxAgent`.

- [ ] **Step 7: Local end-to-end smoke**

```bash
cd autopep && bun run scripts/smoke-roundtrip.ts smoke_chat
```

This goes against your local dev DB + locally-running Modal worker. Expected: green.

- [ ] **Step 8: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_runner.py
git commit -m "feat(autopep): switch agent to SandboxAgent with R2Mount + Skills + multi-turn session"
```

---

### Task 1.7: Delete `_flush_assistant_message` + assistant-text buffers

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py:185-238, 472-505`

**Sequential · after 1.6 · ~5 min**

- [ ] **Step 1: Locate the dead code**

```bash
grep -nE "_flush_assistant_message|ASSISTANT_TEXT_BUFFERS|_accumulate_assistant_text" autopep/modal/autopep_agent/runner.py
```

- [ ] **Step 2: Remove all three**

Delete:
- `ASSISTANT_TEXT_BUFFERS` module-level dict.
- `_accumulate_assistant_text` function.
- `_flush_assistant_message` function.
- The two callsites inside `_append_normalized_stream_events` that call `_accumulate_assistant_text` and `_flush_assistant_message` (around lines 496–505).

`PostgresSession.add_items` now persists assistant text via the SDK's normal completion event.

- [ ] **Step 3: Run the test suite**

```bash
cd autopep/modal && pytest tests/test_runner.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py
git commit -m "refactor(autopep): drop assistant text webhook buffers, replaced by PostgresSession"
```

---

### Task 1.8: Delete `/api/agent/messages` route

**Files:**
- Delete: `autopep/src/app/api/agent/messages/route.ts`
- Modify: `autopep/modal/autopep_agent/runner.py` (drop the env vars referencing the webhook)

**Sequential · after 1.7 · ~3 min**

- [ ] **Step 1: Delete the route**

```bash
rm autopep/src/app/api/agent/messages/route.ts
rmdir autopep/src/app/api/agent/messages 2>/dev/null || true
```

- [ ] **Step 2: Drop env-var references**

```bash
grep -nE "AUTOPEP_NEXT_PUBLIC_URL|AUTOPEP_MODAL_WEBHOOK_SECRET" autopep/modal/autopep_agent/runner.py
```

`AUTOPEP_MODAL_WEBHOOK_SECRET` is still used elsewhere (Modal-side auth), so keep that. `AUTOPEP_NEXT_PUBLIC_URL` was only used by `_flush_assistant_message` — its references should be gone after Task 1.7. Confirm and remove any remaining strays.

- [ ] **Step 3: Verify the deployed URL no longer responds**

This will be checked at the gate (Task 1.9). For now, just ensure the build is clean.

```bash
bun --cwd autopep run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/src/app/api/agent/messages autopep/modal/autopep_agent/runner.py
git commit -m "refactor(autopep): delete /api/agent/messages route (subsumed by PostgresSession)"
```

---

### Task 1.10: Extend `smoke-roundtrip.ts` with `--target prod`

**Files:**
- Modify: `autopep/scripts/smoke-roundtrip.ts`

**Track C · independent · ~15 min**

- [ ] **Step 1: Read the current shape**

```bash
head -60 autopep/scripts/smoke-roundtrip.ts
```

You'll see CLI arg parsing for the task kind. Add a `--target {local|prod}` flag.

- [ ] **Step 2: Add `--target` parsing**

Near the top of `main`:

```ts
const target = process.argv.includes("--target")
	? process.argv[process.argv.indexOf("--target") + 1]
	: "local";

if (target !== "local" && target !== "prod") {
	console.error(`Invalid --target ${target}. Use 'local' or 'prod'.`);
	process.exit(1);
}

const baseUrl = target === "prod"
	? (process.env.AUTOPEP_PROD_BASE_URL ?? throwError("AUTOPEP_PROD_BASE_URL required for --target prod"))
	: "http://localhost:3000";

const apiToken = target === "prod"
	? (process.env.AUTOPEP_PROD_API_TOKEN ?? throwError("AUTOPEP_PROD_API_TOKEN required for --target prod"))
	: undefined;
```

(`throwError` is a small helper that throws — define inline.)

- [ ] **Step 3: Replace the in-process tRPC call with an HTTP call when `target === "prod"`**

Pseudocode:

```ts
const result = target === "prod"
	? await fetchTrpc(baseUrl, "workspace.sendMessage", { prompt, taskKind: "smoke_chat" }, apiToken)
	: await createMessageRunWithLaunch({ db, input: { prompt, taskKind }, ownerId });
```

`fetchTrpc` is a tiny helper that POSTs to the tRPC HTTP endpoint with the right shape. tRPC HTTP encoding: see existing app's tRPC client config.

- [ ] **Step 4: When `target === "prod"`, point DB reads at the prod read-only Neon role**

Add a `--prod-db-url` flag (or auto-derive from `AUTOPEP_PROD_DATABASE_URL`). In prod mode, use this connection only for read assertions (event ledger, thread_items).

- [ ] **Step 5: Add cleanup**

After assertions pass, delete the test workspace:

```ts
if (target === "prod" && createdWorkspaceId) {
	await db.delete(workspaces).where(eq(workspaces.id, createdWorkspaceId));
}
```

Workspace cleanup cascades to threads → thread_items → agent_runs → agent_events via the existing FK cascades.

- [ ] **Step 6: Verify against local first**

```bash
cd autopep && bun run scripts/smoke-roundtrip.ts smoke_chat --target local
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add autopep/scripts/smoke-roundtrip.ts
git commit -m "feat(autopep): smoke-roundtrip --target prod with cleanup"
```

---

### Task 1.11: Add `backend-streaming` scenario to smoke-roundtrip

**Files:**
- Modify: `autopep/scripts/smoke-roundtrip.ts`

**Track C · independent · ~15 min**

- [ ] **Step 1: Add a new scenario branch**

```ts
if (taskKind === "smoke_phase_1" || taskKind === "backend_streaming") {
	await runBackendStreamingScenario({ baseUrl, apiToken, target });
	return;
}
```

- [ ] **Step 2: Implement `runBackendStreamingScenario`**

```ts
async function runBackendStreamingScenario({
	baseUrl,
	apiToken,
	target,
}: {
	baseUrl: string;
	apiToken: string | undefined;
	target: "local" | "prod";
}): Promise<void> {
	const prompt = `smoke-test-${Date.now()}: respond with the word ack`;
	const startTime = Date.now();

	// 1. Send message via tRPC
	const { run, thread } = await sendMessage({ baseUrl, apiToken, prompt });

	// 2. Open SSE connection and time-to-first-delta
	const sseUrl = `${baseUrl}/api/agent/run-stream?runId=${run.id}`;
	const firstDeltaPromise = new Promise<number>((resolve, reject) => {
		const ev = new EventSource(sseUrl);
		const timeout = setTimeout(() => {
			ev.close();
			reject(new Error("No delta received within 30s"));
		}, 30_000);
		ev.addEventListener("delta", (event) => {
			clearTimeout(timeout);
			ev.close();
			resolve(Date.now() - startTime);
		});
	});
	const ttfd = await firstDeltaPromise;
	if (ttfd > 5000) {
		throw new Error(`First token-delta arrived in ${ttfd}ms, expected <5000ms`);
	}
	console.log(`✓ first token-delta in ${ttfd}ms`);

	// 3. Wait for run completion
	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 60_000 });

	// 4. Read agent_events from DB and assert tool-call started/completed pairs are well-ordered
	const events = await fetchAgentEvents({ runId: run.id });
	const toolStarts = events.filter((e) => e.type === "tool_call_started");
	const toolCompletes = events.filter((e) => e.type === "tool_call_completed");
	for (const start of toolStarts) {
		const callId = start.displayJson?.callId ?? start.displayJson?.name;
		const matchingComplete = toolCompletes.find((c) => c.displayJson?.callId === callId);
		if (matchingComplete && matchingComplete.createdAt < start.createdAt) {
			throw new Error(`tool_call_completed arrived before tool_call_started for ${callId}`);
		}
	}
	console.log(`✓ ${toolStarts.length} tool calls, all well-ordered`);

	// 5. Cleanup (prod only)
	if (target === "prod") {
		await deleteWorkspace({ baseUrl, apiToken, workspaceId: thread.workspaceId });
	}
}
```

(`sendMessage`, `waitForRunCompletion`, `fetchAgentEvents`, `deleteWorkspace` are helpers — implement inline based on existing tRPC client patterns.)

- [ ] **Step 3: Run locally**

```bash
cd autopep && bun run scripts/smoke-roundtrip.ts backend_streaming --target local
```

Expected: green with timing assertions.

- [ ] **Step 4: Commit**

```bash
git add autopep/scripts/smoke-roundtrip.ts
git commit -m "feat(autopep): smoke-roundtrip backend_streaming scenario (5s TTFD assertion)"
```

---

### Task 1.9: Phase 1 gate — deploy + multi-turn coherence + sandbox shell + streaming

**Sync point · ~30 min**

- [ ] **Step 1: Update `deploy-and-validate.sh` for Phase 1**

Append to the modal-deploy section:

```bash
modal deploy modal/autopep_agent/sandbox_image.py
```

- [ ] **Step 2: Run deploy-and-validate**

```bash
cd autopep && DATABASE_URL=<prod neon> ./scripts/deploy-and-validate.sh 1
```

This deploys schema, both Modal apps, and Vercel.

- [ ] **Step 3: Run the multi-turn coherence test on prod**

Open the deployed Vercel URL. In a fresh workspace ("workspace A"):

1. Send "Generate a binder for SARS-CoV-2 spike RBD". Wait for the agent to complete (it'll use the existing tools — Phase 2+ will swap them out).
2. Send "What was the top candidate's solubility score?". Verify the response references concrete numbers from turn 1.
3. Send "Now show me what residues 40-60 look like in the fold for that candidate". Verify it knows which candidate without you re-stating it.

Open a second workspace ("workspace B"). Send "hi". Get response.

Switch back to workspace A. Send "Remind me which PDB ID we used for the target." Verify it recalls the PDB ID from turn 1.

- [ ] **Step 4: Verify sandbox `Shell` was exercised**

```bash
psql "$PROD_DATABASE_URL" -c "SELECT type, summary FROM autopep_agent_event WHERE type IN ('sandbox_command_started','sandbox_command_completed') ORDER BY created_at DESC LIMIT 20;"
```

Expected: at least one started/completed pair with non-empty stdout.

- [ ] **Step 5: Verify SSE token streaming**

```bash
cd autopep && AUTOPEP_PROD_BASE_URL=<prod URL> AUTOPEP_PROD_API_TOKEN=<token> bun run scripts/smoke-roundtrip.ts backend_streaming --target prod
```

Expected: "first token-delta in <Xms" with X<5000.

- [ ] **Step 6: Verify the deleted webhook returns 404**

```bash
curl -i -X POST "$AUTOPEP_PROD_BASE_URL/api/agent/messages" -H "Content-Type: application/json" -d '{}'
```

Expected: HTTP 404.

- [ ] **Step 7: Paste green output into PR description; merge.**

- [ ] **Step 8: Phase 1 done.**

---
## Phase 2: literature_search consolidation + Skills capability

**Goal:** Replace the two literature tools with one `literature_search` that fans out to PubMed + Europe PMC in parallel and dedupes. Curate life-science-research skill markdown into the repo. Wire the `Skills` capability so the agent has discoverable working context.

**Spec reference:** §Tool surface (literature_search, Skills directory), §Phase plan Phase 2.

**Gate scenario (Phase 2, S1):** "Find literature about EGFR small-molecule inhibitor preprints from the last year." `literature_search` called once with sensible query. Results merge bioRxiv/medRxiv/PMC/PubMed with no duplicate DOIs. Final assistant message cites ≥3 references with DOIs and inline links. Skill markdown for citation-hygiene loaded (verified by `Skills` capability event in trace). Old tool names absent from new ledger rows.

**Parallelization:**
- **Track A:** Tasks 2.1 → 2.2 (curate skill markdown).
- **Track B:** Tasks 2.3 → 2.4 → 2.5 (`literature_search` failing test, impl, dedup test).
- **Then sequential:** Task 2.6 (wire `Skills` capability + swap tool list, depends on A + B).
- **Then sequential:** Task 2.7 (delete `research_tools.py`, depends on 2.6).
- **Then sequential:** Task 2.8 (Phase 2 gate).

---

### Task 2.1: Bootstrap the skills directory

**Files:**
- Create: `autopep/modal/autopep_agent/skills/life-science-research/SKILL.md`

**Track A · ~5 min**

- [ ] **Step 1: Make the directory**

```bash
mkdir -p autopep/modal/autopep_agent/skills/life-science-research
```

- [ ] **Step 2: Fetch the OpenAI plugin's skill index**

Use `mcp__plugin_context7_context7__query-docs` with query "openai plugins life-science-research skills directory contents" — or directly `WebFetch` <https://github.com/openai/plugins/tree/main/plugins/life-science-research/skills> to enumerate the skill files.

- [ ] **Step 3: Create a top-level SKILL.md index**

```markdown
# Life-Science Research Skills (Autopep curation)

Curated for the Autopep binder-design agent from
https://github.com/openai/plugins/tree/main/plugins/life-science-research/skills.

When the user asks a literature, structure-retrieval, or experimental-evidence
question, consult these skills before answering:

- [literature-evidence.md](./literature-evidence.md) — primary vs secondary
  sources, how to weigh preprints, when to cite uncertainty.
- [citation-hygiene.md](./citation-hygiene.md) — required citation format,
  inline DOI/PMCID linking, no fabricated references.
- [computational-screening.md](./computational-screening.md) — language to use
  about model output (no wet-lab claims, no clinical efficacy claims, always
  flag what was computed vs what was retrieved).

Read the relevant skill before answering questions in that domain.
```

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/skills/life-science-research/SKILL.md
git commit -m "feat(autopep): bootstrap life-science-research skills index"
```

---

### Task 2.2: Author the three skill files

**Files:**
- Create: `autopep/modal/autopep_agent/skills/life-science-research/literature-evidence.md`
- Create: `autopep/modal/autopep_agent/skills/life-science-research/citation-hygiene.md`
- Create: `autopep/modal/autopep_agent/skills/life-science-research/computational-screening.md`

**Track A · ~15 min**

- [ ] **Step 1: Read the upstream content**

Web-fetch each upstream file (e.g. `https://raw.githubusercontent.com/openai/plugins/main/plugins/life-science-research/skills/literature-evidence.md`) to ground your curation. Don't paste verbatim — adapt to our 6-tool surface.

- [ ] **Step 2: Author `literature-evidence.md`**

```markdown
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
```

- [ ] **Step 3: Author `citation-hygiene.md`**

```markdown
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
```

- [ ] **Step 4: Author `computational-screening.md`**

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/skills/life-science-research/
git commit -m "feat(autopep): author life-science-research skill markdown (3 skills)"
```

---

### Task 2.3: `literature_search` — failing tests first

**Files:**
- Create: `autopep/modal/tests/test_literature_tools.py`

**Track B · ~10 min**

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the unified literature_search tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from autopep_agent.literature_tools import _literature_search


@pytest.mark.asyncio
async def test_fans_out_to_pubmed_and_europe_pmc_in_parallel() -> None:
    pubmed_payload = {"results": [{"id": "pm1", "title": "EGFR review", "doi": "10.1/aaa", "url": "https://pubmed.ncbi.nlm.nih.gov/pm1/", "source": "pubmed"}]}
    europe_payload = {"results": [{"id": "ep1", "title": "EGFR preprint", "doi": "10.1/bbb", "url": "https://europepmc.org/article/PPR/ep1", "source": "PPR"}]}

    with (
        patch("autopep_agent.literature_tools._search_pubmed", new=AsyncMock(return_value=pubmed_payload)) as p,
        patch("autopep_agent.literature_tools._search_europe_pmc", new=AsyncMock(return_value=europe_payload)) as e,
    ):
        result = await _literature_search(query="EGFR inhibitors", max_results=8)

    p.assert_awaited_once()
    e.assert_awaited_once()
    assert result["query"] == "EGFR inhibitors"
    titles = {r["title"] for r in result["results"]}
    assert {"EGFR review", "EGFR preprint"}.issubset(titles)


@pytest.mark.asyncio
async def test_dedups_by_doi_keeping_first_source_seen() -> None:
    pubmed_payload = {"results": [{"id": "pm1", "title": "Same paper PubMed", "doi": "10.1/dup", "url": "u1", "source": "pubmed"}]}
    europe_payload = {"results": [{"id": "ep1", "title": "Same paper Europe", "doi": "10.1/dup", "url": "u2", "source": "PPR"}]}

    with (
        patch("autopep_agent.literature_tools._search_pubmed", new=AsyncMock(return_value=pubmed_payload)),
        patch("autopep_agent.literature_tools._search_europe_pmc", new=AsyncMock(return_value=europe_payload)),
    ):
        result = await _literature_search(query="x", max_results=8)

    dois = [r.get("doi") for r in result["results"]]
    assert dois.count("10.1/dup") == 1


@pytest.mark.asyncio
async def test_dedups_by_pmcid_when_no_doi() -> None:
    pubmed_payload = {"results": [{"id": "PMC123", "title": "By PMCID", "doi": None, "pmcid": "PMC123", "url": "u1", "source": "pubmed"}]}
    europe_payload = {"results": [{"id": "PMC123", "title": "By PMCID 2", "doi": None, "pmcid": "PMC123", "url": "u2", "source": "PMC"}]}

    with (
        patch("autopep_agent.literature_tools._search_pubmed", new=AsyncMock(return_value=pubmed_payload)),
        patch("autopep_agent.literature_tools._search_europe_pmc", new=AsyncMock(return_value=europe_payload)),
    ):
        result = await _literature_search(query="x", max_results=8)

    pmcids = [r.get("pmcid") for r in result["results"]]
    assert pmcids.count("PMC123") == 1


@pytest.mark.asyncio
async def test_when_one_source_fails_other_results_still_returned() -> None:
    europe_payload = {"results": [{"id": "ep1", "title": "Survivor", "doi": "10.1/x", "url": "u", "source": "PPR"}]}

    with (
        patch("autopep_agent.literature_tools._search_pubmed", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch("autopep_agent.literature_tools._search_europe_pmc", new=AsyncMock(return_value=europe_payload)),
    ):
        result = await _literature_search(query="x", max_results=8)

    assert any(r["title"] == "Survivor" for r in result["results"])
    assert "errors" in result and "pubmed" in result["errors"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_literature_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'autopep_agent.literature_tools'`.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_literature_tools.py
git commit -m "test(autopep): failing tests for literature_search tool"
```

---

### Task 2.4: `literature_search` — implementation

**Files:**
- Create: `autopep/modal/autopep_agent/literature_tools.py`

**Track B · ~20 min**

- [ ] **Step 1: Implement the tool**

```python
"""Unified literature_search tool — fans out to PubMed + Europe PMC.

Europe PMC's SRC:PPR filter covers bioRxiv + medRxiv + arXiv preprints,
plus PMC and PubMed records. We keep PubMed E-Utilities as a separate
source for peer-reviewed citations and merge dedup'd by DOI then PMCID.

Failures in one source do NOT abort the call; the merged response includes
an `errors` map naming any failed source so the agent can flag partial data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from agents import function_tool


PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DEFAULT_MAX_RESULTS = 8
MAX_RESULTS_LIMIT = 20


def _clamp_max_results(n: int) -> int:
    return max(1, min(MAX_RESULTS_LIMIT, int(n)))


def _strip(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _doi_from_articleids(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, Mapping) and item.get("idtype") == "doi":
            return _strip(item.get("value"))
    return None


def _pmcid_from_articleids(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, Mapping) and item.get("idtype") == "pmc":
            return _strip(item.get("value"))
    return None


async def _search_pubmed(query: str, max_results: int) -> dict[str, Any]:
    limit = _clamp_max_results(max_results)
    async with httpx.AsyncClient(timeout=60) as client:
        search = await client.get(
            PUBMED_SEARCH_URL,
            params={"db": "pubmed", "retmode": "json", "retmax": limit, "term": query},
        )
        search.raise_for_status()
        ids = [i for i in search.json().get("esearchresult", {}).get("idlist", []) if isinstance(i, str)]
        if not ids:
            return {"results": []}

        summary = await client.get(
            PUBMED_SUMMARY_URL,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        summary.raise_for_status()
        block = summary.json().get("result", {})

    results: list[dict[str, Any]] = []
    for uid in block.get("uids", ids):
        record = block.get(uid)
        if not isinstance(record, Mapping):
            continue
        results.append(
            {
                "id": uid,
                "title": _strip(record.get("title")) or f"PubMed {uid}",
                "doi": _doi_from_articleids(record.get("articleids")),
                "pmcid": _pmcid_from_articleids(record.get("articleids")),
                "journal": _strip(record.get("fulljournalname")),
                "published": _strip(record.get("pubdate")),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source": "pubmed",
            }
        )
    return {"results": results}


async def _search_europe_pmc(query: str, max_results: int) -> dict[str, Any]:
    limit = _clamp_max_results(max_results)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            EUROPE_PMC_SEARCH_URL,
            params={
                "format": "json",
                "pageSize": limit,
                "query": query,
                "resultType": "core",
                "sort": "FIRST_PDATE_D desc",
            },
        )
        response.raise_for_status()
        payload = response.json()

    results: list[dict[str, Any]] = []
    for record in payload.get("resultList", {}).get("result", []) or []:
        if not isinstance(record, Mapping):
            continue
        rid = _strip(record.get("id"))
        title = _strip(record.get("title"))
        if not rid or not title:
            continue
        doi = _strip(record.get("doi"))
        pmcid = _strip(record.get("pmcid"))
        source = _strip(record.get("source")) or "UNKNOWN"
        url = (
            f"https://doi.org/{doi}" if doi
            else f"https://europepmc.org/article/{source}/{rid}"
        )
        results.append(
            {
                "id": rid,
                "title": title,
                "doi": doi,
                "pmcid": pmcid,
                "journal": _strip(record.get("journalTitle")),
                "published": _strip(record.get("firstPublicationDate")),
                "authors": _strip(record.get("authorString")),
                "url": url,
                "source": source,
            }
        )
    return {"results": results, "hitCount": payload.get("hitCount")}


def _dedup_key(record: Mapping[str, Any]) -> str:
    """Stable dedup key — DOI when present, else PMCID, else (source, id)."""
    doi = record.get("doi")
    if isinstance(doi, str) and doi:
        return f"doi:{doi.lower()}"
    pmcid = record.get("pmcid")
    if isinstance(pmcid, str) and pmcid:
        return f"pmcid:{pmcid.upper()}"
    return f"src:{record.get('source')}:{record.get('id')}"


async def _literature_search(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> dict[str, Any]:
    """Search PubMed + Europe PMC in parallel; dedup; merge sorted by recency."""
    results = await asyncio.gather(
        _search_pubmed(query, max_results),
        _search_europe_pmc(query, max_results),
        return_exceptions=True,
    )
    errors: dict[str, str] = {}
    pubmed_records: list[dict[str, Any]] = []
    europe_records: list[dict[str, Any]] = []

    if isinstance(results[0], BaseException):
        errors["pubmed"] = str(results[0])
    else:
        pubmed_records = list(results[0].get("results", []))
    if isinstance(results[1], BaseException):
        errors["europe_pmc"] = str(results[1])
    else:
        europe_records = list(results[1].get("results", []))

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for source_records in (pubmed_records, europe_records):
        for record in source_records:
            key = _dedup_key(record)
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)

    merged.sort(key=lambda r: r.get("published") or "", reverse=True)

    response = {"query": query, "results": merged[:max_results]}
    if errors:
        response["errors"] = errors
    return response


literature_search = function_tool(
    _literature_search,
    name_override="literature_search",
    strict_mode=False,
)
```

- [ ] **Step 2: Run the tests**

```bash
cd autopep/modal && pytest tests/test_literature_tools.py -v
```

Expected: PASS for all four.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/literature_tools.py
git commit -m "feat(autopep): unified literature_search tool (PubMed + Europe PMC)"
```

---

### Task 2.5: Live integration test (optional but recommended)

**Files:**
- Modify: `autopep/modal/tests/test_literature_tools.py`

**Track B · ~5 min**

- [ ] **Step 1: Add a live test gated on env**

```python
import os

import pytest


@pytest.mark.skipif(
    os.environ.get("AUTOPEP_LIVE_NETWORK_TESTS") != "1",
    reason="Set AUTOPEP_LIVE_NETWORK_TESTS=1 to run live network tests.",
)
@pytest.mark.asyncio
async def test_live_egfr_query_returns_real_results() -> None:
    result = await _literature_search(query="EGFR small molecule inhibitor preprint", max_results=5)
    assert "results" in result
    assert len(result["results"]) >= 1
    titles = [r["title"] for r in result["results"]]
    assert any("EGFR" in t.upper() or "egfr" in t.lower() for t in titles)
```

- [ ] **Step 2: Run with live flag**

```bash
cd autopep/modal && AUTOPEP_LIVE_NETWORK_TESTS=1 pytest tests/test_literature_tools.py::test_live_egfr_query_returns_real_results -v
```

Expected: PASS (network-dependent).

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_literature_tools.py
git commit -m "test(autopep): live network test for literature_search (gated)"
```

---

### Task 2.6: Wire `Skills` capability + swap tool list in `build_autopep_agent`

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py`

**Sequential · after 2.2 + 2.4 · ~10 min**

- [ ] **Step 1: Update imports**

In `runner.py`, replace `from autopep_agent.research_tools import RESEARCH_TOOLS` with:

```python
from autopep_agent.literature_tools import literature_search
```

Drop the `RESEARCH_TOOLS` reference from the agent's `tools=[...]` list and add `literature_search`:

```python
tools=[
    literature_search,
    generate_binder_candidates,  # to be replaced in Phase 4
    fold_sequences_with_chai,    # to be replaced in Phase 4
    score_candidate_interactions,  # to be replaced in Phase 5
],
```

- [ ] **Step 2: Confirm `Skills(from_=LocalDir(src=SKILLS_DIR))` is in `capabilities`**

This was added in Task 1.6. Verify `SKILLS_DIR = "/app/autopep_agent/skills/life-science-research"` matches the path inside the Modal worker image (recall that `worker_image` adds `modal/autopep_agent` at `/app/autopep_agent`).

- [ ] **Step 3: Run the full test suite**

```bash
cd autopep/modal && pytest -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py
git commit -m "feat(autopep): wire literature_search + Skills capability into agent"
```

---

### Task 2.7: Delete `research_tools.py`

**Files:**
- Delete: `autopep/modal/autopep_agent/research_tools.py`

**Sequential · after 2.6 · ~3 min**

- [ ] **Step 1: Verify no callers**

```bash
grep -rn "research_tools\|search_pubmed_literature\|search_europe_pmc_literature" autopep/modal autopep/src
```

Expected: 0 results outside the file we're about to delete.

- [ ] **Step 2: Delete the file**

```bash
rm autopep/modal/autopep_agent/research_tools.py
```

- [ ] **Step 3: Run tests**

```bash
cd autopep/modal && pytest -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "refactor(autopep): delete research_tools.py (replaced by literature_tools.py)"
```

---

### Task 2.8: Phase 2 gate — deploy + S1 literature scenario on prod

**Sync point · ~15 min**

- [ ] **Step 1: Add S1 scenario to smoke-roundtrip.ts**

Append a `smoke_phase_2` / `literature_demo` scenario:

```ts
async function runLiteratureScenario({ baseUrl, apiToken, target }: ScenarioArgs): Promise<void> {
	const prompt = "Find literature about EGFR small-molecule inhibitor preprints from the last year.";
	const { run, thread } = await sendMessage({ baseUrl, apiToken, prompt });

	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 90_000 });

	const events = await fetchAgentEvents({ runId: run.id });
	const literatureCalls = events.filter((e) =>
		e.type === "tool_call_started" &&
		(e.displayJson as { name?: string })?.name === "literature_search",
	);
	if (literatureCalls.length === 0) {
		throw new Error("literature_search was not called");
	}

	const finalMessage = await fetchLatestAssistantMessage({ baseUrl, apiToken, threadId: thread.id });
	const doiCount = (finalMessage.content.match(/10\.\d{4,9}\/\S+/g) ?? []).length;
	if (doiCount < 3) {
		throw new Error(`Final message has only ${doiCount} DOIs, expected ≥3`);
	}

	const oldNames = events.filter((e) =>
		(e.displayJson as { name?: string })?.name?.startsWith("search_pubmed_literature") ||
		(e.displayJson as { name?: string })?.name?.startsWith("search_europe_pmc_literature"),
	);
	if (oldNames.length > 0) {
		throw new Error("Old literature tool names appeared in ledger");
	}

	if (target === "prod") {
		await deleteWorkspace({ baseUrl, apiToken, workspaceId: thread.workspaceId });
	}
}
```

- [ ] **Step 2: Run deploy-and-validate**

```bash
cd autopep && DATABASE_URL=<prod neon> ./scripts/deploy-and-validate.sh 2
```

This re-deploys schema (no-op if Phase 0 already pushed), Modal worker, sandbox image, Vercel.

- [ ] **Step 3: Run S1 against prod**

```bash
cd autopep && AUTOPEP_PROD_BASE_URL=<prod URL> AUTOPEP_PROD_API_TOKEN=<token> bun run scripts/smoke-roundtrip.ts smoke_phase_2 --target prod
```

Expected: green.

- [ ] **Step 4: Verify Skills was loaded**

```bash
psql "$PROD_DATABASE_URL" -c "SELECT type, summary FROM autopep_agent_event WHERE type LIKE '%skill%' OR summary LIKE '%skill%' ORDER BY created_at DESC LIMIT 10;"
```

Expected: at least one row showing the `Skills` capability injected the skill index. (If the SDK doesn't emit a dedicated skill event, the skill markdown should still appear in the agent's reasoning — verify by reading a few `function_call`/`message` rows from `thread_items`.)

- [ ] **Step 5: Paste green output into PR description; merge.**

- [ ] **Step 6: Phase 2 done.**

---
## Phase 3: PDB tools

**Goal:** Implement `pdb_search` (RCSB Search API with `max_chain_length` filter, default 500) and `pdb_fetch` (download PDB to `/workspace/runs/{run_id}/inputs/`, register artifact, return extracted sequence). Wire both into the agent.

**Spec reference:** §Tool surface (pdb_search, pdb_fetch), §Phase plan Phase 3.

**Gate scenario (Phase 3, S2):** "Search the PDB for human ACE2 ectodomain structures and show me the highest-resolution one." `pdb_search` returns ≥3 candidate IDs filtered by chain length <500. The agent calls `pdb_fetch`. A `pdb` artifact appears in the Files panel. Sequence in chat-panel response. Artifact opens in Mol*.

**Parallelization:**
- **Track A:** Tasks 3.1 → 3.2 → 3.3 (`pdb_search` failing tests, impl, RCSB-shape live test).
- **Track B:** Tasks 3.4 → 3.5 → 3.6 (`pdb_fetch` failing tests, impl, sequence-extraction test).
- **Then sequential:** Task 3.7 (wire both into agent's tool list).
- **Then sequential:** Task 3.8 (Phase 3 gate).

---

### Task 3.1: `pdb_search` — failing tests

**Files:**
- Create: `autopep/modal/tests/test_pdb_tools.py`

**Track A · ~10 min**

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for pdb_search and pdb_fetch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from autopep_agent.pdb_tools import _pdb_search, _build_rcsb_query


def test_build_rcsb_query_includes_max_chain_length_filter() -> None:
    q = _build_rcsb_query(query="ACE2", max_chain_length=500, top_k=10, organism=None)
    nodes = q["query"]["nodes"]
    assert any(
        n.get("type") == "terminal"
        and n.get("service") == "text"
        and n.get("parameters", {}).get("attribute") == "entity_poly.rcsb_sample_sequence_length"
        and n.get("parameters", {}).get("operator") == "less"
        for n in nodes
    ), "max_chain_length should produce a sequence-length terminal node"


def test_build_rcsb_query_with_organism_filter() -> None:
    q = _build_rcsb_query(query="ACE2", max_chain_length=500, top_k=10, organism="Homo sapiens")
    nodes = q["query"]["nodes"]
    assert any(
        n.get("parameters", {}).get("attribute") == "rcsb_entity_source_organism.ncbi_scientific_name"
        and n.get("parameters", {}).get("value") == "Homo sapiens"
        for n in nodes
    )


@pytest.mark.asyncio
async def test_pdb_search_returns_metadata_no_download() -> None:
    fake_search = {
        "result_set": [
            {"identifier": "6M0J"},
            {"identifier": "1R42"},
        ],
        "total_count": 2,
    }
    fake_meta_6m0j = {
        "rcsb_id": "6M0J",
        "struct": {"title": "ACE2-RBD complex"},
        "rcsb_entry_info": {"resolution_combined": [2.45]},
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "polymer_entities": [
            {"entity_poly": {"pdbx_seq_one_letter_code_can": "AAAA", "rcsb_sample_sequence_length": 400}, "rcsb_polymer_entity_container_identifiers": {"asym_ids": ["A"]}},
        ],
    }
    fake_meta_1r42 = {
        "rcsb_id": "1R42",
        "struct": {"title": "ACE2 ectodomain"},
        "rcsb_entry_info": {"resolution_combined": [3.0]},
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "polymer_entities": [
            {"entity_poly": {"pdbx_seq_one_letter_code_can": "BBBB", "rcsb_sample_sequence_length": 600}, "rcsb_polymer_entity_container_identifiers": {"asym_ids": ["B"]}},
        ],
    }

    with patch("autopep_agent.pdb_tools._fetch_rcsb_search", new=AsyncMock(return_value=fake_search)) as mock_search:
        with patch(
            "autopep_agent.pdb_tools._fetch_rcsb_entry_meta",
            new=AsyncMock(side_effect=[fake_meta_6m0j, fake_meta_1r42]),
        ):
            result = await _pdb_search(query="ACE2", max_chain_length=500, top_k=10, organism=None)

    mock_search.assert_awaited_once()
    ids = [r["pdb_id"] for r in result["results"]]
    assert "6M0J" in ids
    assert "1R42" in ids
    # 1R42's chain is 600 — should be flagged via the metadata, but the RCSB-side
    # filter is what enforces the 500 cap. We surface the chain length so the
    # agent can re-confirm.
    six_m0j = next(r for r in result["results"] if r["pdb_id"] == "6M0J")
    assert six_m0j["resolution"] == 2.45
    assert six_m0j["title"] == "ACE2-RBD complex"
    assert "A" in six_m0j["chain_lengths_by_id"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_pdb_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_pdb_tools.py
git commit -m "test(autopep): failing tests for pdb_search"
```

---

### Task 3.2: `pdb_search` — implementation

**Files:**
- Create: `autopep/modal/autopep_agent/pdb_tools.py`

**Track A · ~20 min**

- [ ] **Step 1: Confirm RCSB Search API attributes**

Run `mcp__plugin_context7_context7__query-docs` with "RCSB Search API entity_poly rcsb_sample_sequence_length" — or web-fetch <https://search.rcsb.org/index.html#search-attributes> to confirm the exact attribute name for chain length. As of 2025, `entity_poly.rcsb_sample_sequence_length` is the canonical attribute on polymer-entity scope. If your context7 result differs, use that.

- [ ] **Step 2: Implement `pdb_tools.py`**

```python
"""pdb_search and pdb_fetch tools.

pdb_search hits RCSB's Search API and returns metadata only (no PDB
downloads). Filters by chain length (default <500) and optional organism.

pdb_fetch downloads the chosen PDB into the workspace's R2-mounted
inputs/ directory and registers it as an `artifact` row.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from agents import function_tool

from autopep_agent.db import create_artifact
from autopep_agent.events import EventWriter
from autopep_agent.r2_client import put_object as r2_put_object
from autopep_agent.run_context import get_tool_run_context
from autopep_agent.structure_utils import extract_pdb_sequences


RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download"


def _build_rcsb_query(
    *,
    query: str,
    max_chain_length: int,
    top_k: int,
    organism: str | None,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "entity_poly.rcsb_sample_sequence_length",
                "operator": "less",
                "value": max_chain_length,
            },
        },
    ]
    if organism:
        nodes.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entity_source_organism.ncbi_scientific_name",
                    "operator": "exact_match",
                    "value": organism,
                },
            },
        )

    return {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": nodes,
        },
        "request_options": {
            "paginate": {"rows": top_k, "start": 0},
            "sort": [
                {
                    "direction": "asc",
                    "sort_by": "rcsb_entry_info.resolution_combined",
                },
            ],
        },
        "return_type": "entry",
    }


async def _fetch_rcsb_search(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(RCSB_SEARCH_URL, json=payload)
        response.raise_for_status()
        return response.json()


async def _fetch_rcsb_entry_meta(pdb_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{RCSB_DATA_URL}/{pdb_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def _flatten_meta(pdb_id: str, meta: Mapping[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {"pdb_id": pdb_id, "title": None, "resolution": None, "method": None, "chain_lengths_by_id": {}}
    title = (meta.get("struct") or {}).get("title")
    resolutions = (meta.get("rcsb_entry_info") or {}).get("resolution_combined") or []
    method = None
    for entry in meta.get("exptl") or []:
        if isinstance(entry, Mapping) and entry.get("method"):
            method = entry["method"]
            break
    chain_lengths: dict[str, int] = {}
    for entity in meta.get("polymer_entities") or []:
        ids = ((entity or {}).get("rcsb_polymer_entity_container_identifiers") or {}).get("asym_ids") or []
        length = ((entity or {}).get("entity_poly") or {}).get("rcsb_sample_sequence_length")
        if isinstance(length, int):
            for asym in ids:
                if isinstance(asym, str):
                    chain_lengths[asym] = length
    return {
        "pdb_id": pdb_id,
        "title": title,
        "resolution": resolutions[0] if resolutions else None,
        "method": method,
        "chain_lengths_by_id": chain_lengths,
    }


async def _pdb_search(
    query: str,
    max_chain_length: int = 500,
    top_k: int = 10,
    organism: str | None = None,
) -> dict[str, Any]:
    """Search RCSB by query + chain-length cap; return ranked metadata only."""
    payload = _build_rcsb_query(
        query=query, max_chain_length=max_chain_length, top_k=top_k, organism=organism
    )
    search_payload = await _fetch_rcsb_search(payload)
    identifiers = [
        row.get("identifier")
        for row in search_payload.get("result_set") or []
        if isinstance(row, Mapping) and row.get("identifier")
    ]
    metas = await asyncio.gather(
        *(_fetch_rcsb_entry_meta(str(i)) for i in identifiers),
        return_exceptions=True,
    )
    results: list[dict[str, Any]] = []
    for ident, meta in zip(identifiers, metas):
        if isinstance(meta, BaseException):
            continue
        results.append(_flatten_meta(str(ident), meta))
    return {
        "query": query,
        "max_chain_length": max_chain_length,
        "results": results,
        "total_count": search_payload.get("total_count"),
    }


pdb_search = function_tool(
    _pdb_search,
    name_override="pdb_search",
    strict_mode=False,
)
```

- [ ] **Step 2: Run the tests**

```bash
cd autopep/modal && pytest tests/test_pdb_tools.py -v
```

Expected: PASS (the search tests; `pdb_fetch` tests come in Task 3.4).

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/pdb_tools.py
git commit -m "feat(autopep): pdb_search tool with RCSB Search API + chain-length cap"
```

---

### Task 3.3: Live RCSB integration test (gated)

**Files:**
- Modify: `autopep/modal/tests/test_pdb_tools.py`

**Track A · ~5 min**

- [ ] **Step 1: Add a live test**

```python
import os


@pytest.mark.skipif(
    os.environ.get("AUTOPEP_LIVE_NETWORK_TESTS") != "1",
    reason="Set AUTOPEP_LIVE_NETWORK_TESTS=1 to run live network tests.",
)
@pytest.mark.asyncio
async def test_live_ace2_search_returns_filtered_results() -> None:
    result = await _pdb_search(query="ACE2 ectodomain", max_chain_length=500, top_k=5)
    assert len(result["results"]) >= 1
    for record in result["results"]:
        for length in (record.get("chain_lengths_by_id") or {}).values():
            assert length < 500, f"chain length {length} exceeded cap of 500"
```

- [ ] **Step 2: Run with live flag**

```bash
cd autopep/modal && AUTOPEP_LIVE_NETWORK_TESTS=1 pytest tests/test_pdb_tools.py::test_live_ace2_search_returns_filtered_results -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_pdb_tools.py
git commit -m "test(autopep): live RCSB chain-length-filter test (gated)"
```

---

### Task 3.4: `pdb_fetch` — failing tests

**Files:**
- Modify: `autopep/modal/tests/test_pdb_tools.py`

**Track B · ~10 min**

- [ ] **Step 1: Add failing tests**

```python
@pytest.mark.asyncio
async def test_pdb_fetch_writes_to_inputs_and_creates_artifact(
    tool_run_context, mock_r2, mock_db, monkeypatch,
) -> None:
    fake_pdb_text = "HEADER  TEST PROTEIN\nATOM      1  N   MET A   1      ...\nEND\n"
    mock_http = AsyncMock(return_value=type("R", (), {"status_code": 200, "text": fake_pdb_text, "raise_for_status": lambda self: None})())
    monkeypatch.setattr("autopep_agent.pdb_tools._download_pdb_text", mock_http)
    monkeypatch.setattr("autopep_agent.pdb_tools.extract_pdb_sequences", lambda txt: {"A": "MAGS"})

    from autopep_agent.pdb_tools import _pdb_fetch

    result = await _pdb_fetch(pdb_id="6M0J", chain_id="A")

    assert result["pdb_id"] == "6M0J"
    assert result["chain_id"] == "A"
    assert result["sequence"] == "MAGS"
    assert result["sandbox_path"].endswith("/inputs/6M0J.pdb")
    mock_r2.assert_awaited_once()  # uploaded
    mock_db.assert_awaited_once()   # artifact row created


@pytest.mark.asyncio
async def test_pdb_fetch_with_no_chain_id_returns_first_chain_sequence(
    tool_run_context, mock_r2, mock_db, monkeypatch,
) -> None:
    fake_pdb_text = "HEADER\nATOM\nEND\n"
    monkeypatch.setattr(
        "autopep_agent.pdb_tools._download_pdb_text",
        AsyncMock(return_value=type("R", (), {"text": fake_pdb_text, "raise_for_status": lambda self: None})()),
    )
    monkeypatch.setattr(
        "autopep_agent.pdb_tools.extract_pdb_sequences",
        lambda txt: {"A": "AAAA", "B": "BBBB"},
    )

    from autopep_agent.pdb_tools import _pdb_fetch

    result = await _pdb_fetch(pdb_id="X1Y2", chain_id=None)

    # When chain_id is None, return the first chain (insertion order preserves dict order).
    assert result["chain_id"] == "A"
    assert result["sequence"] == "AAAA"
    assert result["all_chains"] == {"A": "AAAA", "B": "BBBB"}
```

The `tool_run_context`, `mock_r2`, `mock_db` fixtures may need to be created in `autopep/modal/tests/conftest.py` — they install patches for `get_tool_run_context`, `r2_put_object`, and `create_artifact` respectively. Add them if absent following existing fixture patterns.

- [ ] **Step 2: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_pdb_tools.py::test_pdb_fetch_writes_to_inputs_and_creates_artifact -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_pdb_tools.py autopep/modal/tests/conftest.py
git commit -m "test(autopep): failing tests for pdb_fetch"
```

---

### Task 3.5: `pdb_fetch` — implementation

**Files:**
- Modify: `autopep/modal/autopep_agent/pdb_tools.py`

**Track B · ~15 min**

- [ ] **Step 1: Implement**

Append to `pdb_tools.py`:

```python
async def _download_pdb_text(pdb_id: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{RCSB_DOWNLOAD_URL}/{pdb_id}.pdb")
        response.raise_for_status()
        return response


def _r2_config_from_env() -> dict[str, str]:
    from autopep_agent.config import WorkerConfig

    cfg = WorkerConfig.from_env()
    return {
        "bucket": cfg.r2_bucket,
        "account_id": cfg.r2_account_id,
        "access_key_id": cfg.r2_access_key_id,
        "secret_access_key": cfg.r2_secret_access_key,
    }


def _pdb_storage_key(*, workspace_id: str, run_id: str, pdb_id: str) -> str:
    return f"workspaces/{workspace_id}/runs/{run_id}/inputs/{pdb_id}.pdb"


def _sandbox_path_for_pdb(*, run_id: str, pdb_id: str) -> str:
    return f"/workspace/runs/{run_id}/inputs/{pdb_id}.pdb"


async def _pdb_fetch(
    pdb_id: str,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Download a PDB from RCSB, mount it in the workspace, register an artifact."""
    ctx = get_tool_run_context()
    cfg = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    response = await _download_pdb_text(pdb_id)
    text = response.text
    if not text.startswith("HEADER") and "ATOM" not in text:
        raise RuntimeError(f"PDB download for {pdb_id} did not look like a PDB file")

    body = text.encode("utf-8")
    storage_key = _pdb_storage_key(
        workspace_id=ctx.workspace_id, run_id=ctx.run_id, pdb_id=pdb_id
    )
    sha256 = await r2_put_object(
        bucket=cfg["bucket"],
        account_id=cfg["account_id"],
        access_key_id=cfg["access_key_id"],
        secret_access_key=cfg["secret_access_key"],
        key=storage_key,
        body=body,
        content_type="chemical/x-pdb",
    )

    artifact_id = await create_artifact(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        kind="pdb",
        name=f"{pdb_id}.pdb",
        storage_key=storage_key,
        content_type="chemical/x-pdb",
        size_bytes=len(body),
        sha256=sha256,
        metadata_json={
            "pdbId": pdb_id,
            "source": "rcsb",
            "url": f"{RCSB_DOWNLOAD_URL}/{pdb_id}.pdb",
            "chainId": chain_id,
        },
    )
    await writer.append_event(
        run_id=ctx.run_id,
        event_type="artifact_created",
        title=f"Stored {pdb_id}.pdb",
        summary=f"Saved RCSB {pdb_id} into workspace inputs/.",
        display={"artifactId": artifact_id, "kind": "pdb", "pdbId": pdb_id},
    )

    sequences = extract_pdb_sequences(text)
    chosen_chain = chain_id or next(iter(sequences.keys()), None)
    if chosen_chain is None:
        raise RuntimeError(f"Could not extract any chain from {pdb_id}")
    sequence = sequences.get(chosen_chain, "")

    return {
        "pdb_id": pdb_id,
        "artifact_id": artifact_id,
        "sandbox_path": _sandbox_path_for_pdb(run_id=ctx.run_id, pdb_id=pdb_id),
        "chain_id": chosen_chain,
        "sequence": sequence,
        "all_chains": sequences,
    }


pdb_fetch = function_tool(
    _pdb_fetch,
    name_override="pdb_fetch",
    strict_mode=False,
)
```

- [ ] **Step 2: Run the tests**

```bash
cd autopep/modal && pytest tests/test_pdb_tools.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/pdb_tools.py
git commit -m "feat(autopep): pdb_fetch tool (download + artifact + sandbox path + sequence)"
```

---

### Task 3.6: Live RCSB download test (gated)

**Files:**
- Modify: `autopep/modal/tests/test_pdb_tools.py`

**Track B · ~5 min**

- [ ] **Step 1: Add the live test**

```python
@pytest.mark.skipif(
    os.environ.get("AUTOPEP_LIVE_NETWORK_TESTS") != "1",
    reason="Live network test gated.",
)
@pytest.mark.asyncio
async def test_live_download_pdb_text_for_6m0j() -> None:
    from autopep_agent.pdb_tools import _download_pdb_text

    response = await _download_pdb_text("6M0J")
    assert response.status_code == 200
    assert "ATOM" in response.text
    assert "ACE2" in response.text or "ANGIOTENSIN" in response.text.upper()
```

- [ ] **Step 2: Run with live flag**

```bash
cd autopep/modal && AUTOPEP_LIVE_NETWORK_TESTS=1 pytest tests/test_pdb_tools.py::test_live_download_pdb_text_for_6m0j -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_pdb_tools.py
git commit -m "test(autopep): live PDB download test for 6M0J (gated)"
```

---

### Task 3.7: Wire `pdb_search` + `pdb_fetch` into the agent

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py`

**Sequential · after 3.2 + 3.5 · ~5 min**

- [ ] **Step 1: Update imports + tool list**

In `runner.py`:

```python
from autopep_agent.pdb_tools import pdb_fetch, pdb_search

# inside build_autopep_agent:
tools=[
    literature_search,
    pdb_search,
    pdb_fetch,
    generate_binder_candidates,
    fold_sequences_with_chai,
    score_candidate_interactions,
],
```

- [ ] **Step 2: Update system prompt to mention the new tools**

In `build_agent_instructions()`, update the workflow paragraph (it should already mention `pdb_search` / `pdb_fetch` per the spec — verify and tighten):

```python
"For binder-design tasks, the typical loop is literature_search → "
"pdb_search → pdb_fetch → optionally inspect the structure with shell "
"+ BioPython to identify hotspots → proteina_design → "
"chai_fold_complex → score_candidates → present a ranked summary "
"citing the literature you found and the artifacts you produced. "
"You may iterate (e.g., warm-start Proteina from your best fold) "
"within the same run."
```

(Note: tool names like `proteina_design` won't exist until Phase 4 — this is fine; the agent's instructions can reference future names because the tool list it actually has is what matters, and the agent will fall back to current names until Phase 4.)

Actually — to avoid confusing the model with phantom tool names, **only mention names that exist as of this phase**. Update the prompt to reference `generate_binder_candidates`, `fold_sequences_with_chai`, `score_candidate_interactions` for now. Phase 4 and 5 will swap each name as the corresponding tool changes.

- [ ] **Step 3: Run the suite**

```bash
cd autopep/modal && pytest -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py
git commit -m "feat(autopep): wire pdb_search + pdb_fetch into agent tool list"
```

---

### Task 3.8: Phase 3 gate — deploy + S2 PDB scenario on prod

**Sync point · ~15 min**

- [ ] **Step 1: Add S2 scenario to smoke-roundtrip.ts**

```ts
async function runPdbScenario({ baseUrl, apiToken, target }: ScenarioArgs): Promise<void> {
	const prompt = "Search the PDB for human ACE2 ectodomain structures and show me the highest-resolution one.";
	const { run, thread } = await sendMessage({ baseUrl, apiToken, prompt });

	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 90_000 });

	const events = await fetchAgentEvents({ runId: run.id });
	const searchCalls = events.filter((e) => e.type === "tool_call_started" && (e.displayJson as { name?: string })?.name === "pdb_search");
	if (searchCalls.length === 0) throw new Error("pdb_search not called");

	const fetchCalls = events.filter((e) => e.type === "tool_call_started" && (e.displayJson as { name?: string })?.name === "pdb_fetch");
	if (fetchCalls.length === 0) throw new Error("pdb_fetch not called");

	const artifactEvents = events.filter((e) => e.type === "artifact_created" && (e.displayJson as { kind?: string })?.kind === "pdb");
	if (artifactEvents.length === 0) throw new Error("no pdb artifact created");

	if (target === "prod") {
		await deleteWorkspace({ baseUrl, apiToken, workspaceId: thread.workspaceId });
	}
}
```

- [ ] **Step 2: Run deploy-and-validate**

```bash
cd autopep && DATABASE_URL=<prod neon> ./scripts/deploy-and-validate.sh 3
```

- [ ] **Step 3: Run S2 against prod**

```bash
cd autopep && AUTOPEP_PROD_BASE_URL=<prod URL> bun run scripts/smoke-roundtrip.ts smoke_phase_3 --target prod
```

Expected: green.

- [ ] **Step 4: Manual verification**

Open prod URL. Send the S2 prompt. Verify:
- Tool-call card for `pdb_search` appears with ≥3 candidates in its result.
- Tool-call card for `pdb_fetch` appears.
- Files panel shows a new `.pdb` artifact.
- Click the artifact → it opens in Mol*.

- [ ] **Step 5: Paste green output into PR description; merge.**

- [ ] **Step 6: Phase 3 done.**

---
## Phase 4: Proteina batch-of-5 + warm-start, parallel Chai

**Goal:** Bump Proteina from `nsamples=1` to 5 in one batched call. Add `warm_start_structure_path` arg so the agent can refine from a prior fold. Convert Chai's sequential per-candidate loop into `asyncio.gather`. Always fold target+binder as a complex so Mol* renders both chains together. Rename the tools in the agent's tool list to `proteina_design` and `chai_fold_complex`.

**Spec reference:** §Tool surface (proteina_design, chai_fold_complex), §Phase plan Phase 4.

**Gate scenario (Phase 4, S3):** Upload a `.pdb` file via chat composer's Paperclip control. Send: "Fold this sequence with Chai and visualise the result alongside the target sequence: \[paste a binder candidate sequence\]." Plus the dual proteina batch test: a separate prompt "design 5 binders for \[target\]" must produce 5 distinct candidates from one Proteina call.

**Parallelization:**
- **Track A:** Tasks 4.1 → 4.2 → 4.3 (Proteina overrides bump + `warm_start_structure_path` + tests).
- **Track B:** Tasks 4.4 → 4.5 → 4.6 (Chai parallelization + always-complex + tests).
- **Then sequential:** Task 4.7 (rename tools in agent + tests + system prompt).
- **Then sequential:** Task 4.8 (Phase 4 gate).

---

### Task 4.1: Bump Proteina batch overrides 1 → 5

**Files:**
- Modify: `autopep/modal/autopep_agent/endpoint_clients.py:8-15`

**Track A · ~3 min**

- [ ] **Step 1: Read the current overrides**

```bash
sed -n '8,16p' autopep/modal/autopep_agent/endpoint_clients.py
```

- [ ] **Step 2: Update**

```python
PROTEINA_DESIGN_STEPS = ["generate"]
PROTEINA_BATCH_SIZE = 5
PROTEINA_FAST_GENERATION_OVERRIDES = [
    "++generation.search.algorithm=single-pass",
    "++generation.reward_model=null",
    f"++generation.dataloader.batch_size={PROTEINA_BATCH_SIZE}",
    f"++generation.dataloader.dataset.nres.nsamples={PROTEINA_BATCH_SIZE}",
    "++generation.args.nsteps=20",
]
```

- [ ] **Step 3: Run existing biology-tools tests**

```bash
cd autopep/modal && pytest tests/test_biology_tools.py -v
```

Expected: PASS (or fail in ways unrelated to overrides).

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/endpoint_clients.py
git commit -m "feat(autopep): bump Proteina batch to 5 candidates per call"
```

---

### Task 4.2: Add `warm_start_structure` to `ProteinaClient.design`

**Files:**
- Modify: `autopep/modal/autopep_agent/endpoint_clients.py:41-65`

**Track A · ~5 min**

- [ ] **Step 1: Update the client**

Replace `ProteinaClient.design` with:

```python
class ProteinaClient(ModalEndpointClient):
    async def design(
        self,
        target_structure: str,
        target_filename: str,
        target_input: str | None,
        hotspot_residues: Sequence[str],
        binder_length: Sequence[int],
        warm_start_structure: str | None = None,
        warm_start_filename: str | None = None,
    ) -> Any:
        target_payload: dict[str, Any] = {
            "structure": target_structure,
            "filename": target_filename,
            "target_input": target_input,
            "hotspot_residues": list(hotspot_residues),
            "binder_length": list(binder_length),
        }
        if warm_start_structure is not None:
            target_payload["warm_start_structure"] = warm_start_structure
            target_payload["warm_start_filename"] = warm_start_filename or "warm_start.pdb"

        return await self.post_json(
            "/design",
            {
                "action": "design-cif",
                "design_steps": PROTEINA_DESIGN_STEPS,
                "overrides": PROTEINA_FAST_GENERATION_OVERRIDES,
                "target": target_payload,
            },
        )
```

(The Modal endpoint already supports `warm_start_overrides` per `tools/proteina-complexa/proteina_complexa/warm_start.py:141`. The endpoint's payload contract — exact field names — should be confirmed against `tools/proteina-complexa/proteina_complexa/http_server.py` before merging. If the field name on the endpoint side is `warm_start_pdb` rather than `warm_start_structure`, rename here accordingly.)

- [ ] **Step 2: Verify endpoint-side contract**

```bash
grep -nE "warm_start" autopep/../tools/proteina-complexa/proteina_complexa/http_server.py 2>&1 | head -10
# (path adjusted relative to repo root)
grep -nE "warm_start" tools/proteina-complexa/proteina_complexa/http_server.py | head -10
```

Match the wire field name. If the server expects `warm_start_pdb`, change the Python client to send `warm_start_pdb`.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/endpoint_clients.py
git commit -m "feat(autopep): ProteinaClient.design accepts warm_start_structure"
```

---

### Task 4.3: Rename `_generate_binder_candidates` → `_proteina_design`, update signature

**Files:**
- Modify: `autopep/modal/autopep_agent/biology_tools.py:53-222`
- Modify: `autopep/modal/tests/test_biology_tools.py`

**Track A · ~20 min**

- [ ] **Step 1: Read existing `_generate_binder_candidates`**

```bash
sed -n '53,222p' autopep/modal/autopep_agent/biology_tools.py
```

- [ ] **Step 2: Rewrite signature to read PDB from sandbox path**

The new signature:

```python
async def _proteina_design(
    target_pdb_path: str,
    hotspot_residues: list[str] | None = None,
    binder_length_min: int = 60,
    binder_length_max: int = 90,
    num_candidates: int = 5,
    warm_start_structure_path: str | None = None,
) -> dict[str, Any]:
    """Generate `num_candidates` binders for the target at `target_pdb_path`.

    `target_pdb_path` is a path inside the mounted workspace, e.g.
    `/workspace/runs/<run_id>/inputs/6M0J.pdb`. The tool reads the PDB
    text from R2-mounted storage rather than receiving it as an argument.
    `warm_start_structure_path`, if provided, is also a sandbox path —
    the tool reads it and threads it through Proteina's warm_start_overrides.
    """
```

- [ ] **Step 3: Implement**

```python
import asyncio
from pathlib import Path

WORKSPACE_ROOT = "/workspace"


def _resolve_workspace_path(path: str) -> Path:
    """Translate the sandbox-side path the LLM passed into a host-side path the worker can read.

    Paths the LLM gives are relative to the mounted workspace at /workspace/.
    The Modal worker has the same R2 mount available at /autopep-workspaces/...
    via the existing workspace volume; OR — preferred — the worker fetches via
    R2 directly using the storage_key derived from the path.

    For the MVP we read via R2 using the existing r2_client; the sandbox-side
    path is purely informational for the LLM.
    """
    if not path.startswith(WORKSPACE_ROOT):
        raise ValueError(f"Workspace path must start with {WORKSPACE_ROOT}, got {path}")
    return Path(path)


def _storage_key_from_workspace_path(*, workspace_id: str, sandbox_path: str) -> str:
    """`/workspace/runs/X/inputs/Y.pdb` → `workspaces/<workspace_id>/runs/X/inputs/Y.pdb`."""
    rel = sandbox_path[len(WORKSPACE_ROOT):].lstrip("/")
    return f"workspaces/{workspace_id}/{rel}"


async def _read_workspace_text(*, workspace_id: str, sandbox_path: str) -> str:
    from autopep_agent.r2_client import get_object as r2_get_object

    cfg = _r2_config_from_env()
    storage_key = _storage_key_from_workspace_path(
        workspace_id=workspace_id, sandbox_path=sandbox_path
    )
    body = await r2_get_object(
        bucket=cfg["bucket"],
        account_id=cfg["account_id"],
        access_key_id=cfg["access_key_id"],
        secret_access_key=cfg["secret_access_key"],
        key=storage_key,
    )
    return body.decode("utf-8")


async def _proteina_design(
    target_pdb_path: str,
    hotspot_residues: list[str] | None = None,
    binder_length_min: int = 60,
    binder_length_max: int = 90,
    num_candidates: int = 5,
    warm_start_structure_path: str | None = None,
) -> dict[str, Any]:
    ctx = get_tool_run_context()
    cfg = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    target_text = await _read_workspace_text(
        workspace_id=ctx.workspace_id, sandbox_path=target_pdb_path
    )
    target_filename = Path(target_pdb_path).name

    warm_start_text: str | None = None
    warm_start_filename: str | None = None
    if warm_start_structure_path:
        warm_start_text = await _read_workspace_text(
            workspace_id=ctx.workspace_id, sandbox_path=warm_start_structure_path
        )
        warm_start_filename = Path(warm_start_structure_path).name

    target_input = _target_input_from_pdb(target_text)

    request_payload = {
        "target_filename": target_filename,
        "target_input": target_input,
        "hotspot_residues": list(hotspot_residues or []),
        "binder_length": [binder_length_min, binder_length_max],
        "num_candidates": num_candidates,
        "warm_start_filename": warm_start_filename,
    }
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="proteina_complexa",
        request_json=request_payload,
        endpoint_url=ctx.proteina_base_url,
    )

    try:
        client = ProteinaClient(ctx.proteina_base_url, ctx.proteina_api_key)
        response = await client.design(
            target_structure=target_text,
            target_filename=target_filename,
            target_input=target_input,
            hotspot_residues=list(hotspot_residues or []),
            binder_length=[binder_length_min, binder_length_max],
            warm_start_structure=warm_start_text,
            warm_start_filename=warm_start_filename,
        )
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        raise

    candidates: list[dict[str, Any]] = []
    try:
        for rank, pdb_record in enumerate(_extract_pdb_records(response), start=1):
            pdb_text = pdb_record["pdb"]
            filename = pdb_record["filename"]
            sequences = extract_pdb_sequences(pdb_text)
            target_sequence = sequences.get("A", "")
            sequence = sequences.get("B") or next(iter(sequences.values()), "")
            body = pdb_text.encode("utf-8")
            storage_key = _candidate_artifact_key(
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                filename=filename,
            )
            sha256 = await r2_put_object(
                bucket=cfg["bucket"],
                account_id=cfg["account_id"],
                access_key_id=cfg["access_key_id"],
                secret_access_key=cfg["secret_access_key"],
                key=storage_key,
                body=body,
                content_type="chemical/x-pdb",
            )
            artifact_id = await create_artifact(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                kind="proteina_result",
                name=filename,
                storage_key=storage_key,
                content_type="chemical/x-pdb",
                size_bytes=len(body),
                sha256=sha256,
            )
            await writer.append_event(
                run_id=ctx.run_id,
                event_type="artifact_created",
                title=f"Stored {filename}",
                summary=f"Saved Proteina design {filename}",
                display={"artifactId": artifact_id, "kind": "proteina_result"},
            )
            candidate_db_id = await create_candidate(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                rank=rank,
                source="proteina_complexa",
                title=f"Proteina design #{rank}",
                sequence=sequence,
                chain_ids=sorted(sequences.keys()),
                artifact_id=artifact_id,
                parent_inference_id=inference_id,
            )
            await writer.append_event(
                run_id=ctx.run_id,
                event_type="candidate_ranked",
                title=f"Candidate #{rank} stored",
                summary=f"Persisted Proteina candidate {rank}",
                display={
                    "candidateId": candidate_db_id,
                    "rank": rank,
                    "source": "proteina_complexa",
                },
            )
            candidates.append({
                "rank": rank,
                "filename": filename,
                "sandbox_path": f"/workspace/runs/{ctx.run_id}/proteina/{filename}",
                "sequence": sequence,
                "target_sequence": target_sequence,
                "candidate_id": candidate_db_id,
                "artifact_id": artifact_id,
            })
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={"raw": response} if not isinstance(response, dict) else response,
            error_summary=_summarize_error(exc),
        )
        raise

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"raw": response} if not isinstance(response, dict) else response,
    )

    return {"num_candidates": len(candidates), "candidates": candidates}


def _target_input_from_pdb(pdb_text: str) -> str:
    """Build a Proteina target_input selector from the first chain in the PDB."""
    sequences = extract_pdb_sequences(pdb_text)
    if not sequences:
        raise RuntimeError("PDB has no extractable chain")
    chain_id, sequence = next(iter(sequences.items()))
    return f"{chain_id}1-{len(sequence)}"


# Replace the old function_tool wrapper:
proteina_design = function_tool(
    _proteina_design,
    name_override="proteina_design",
    strict_mode=False,
)

# DELETE the old `generate_binder_candidates = function_tool(...)` export.
```

(`r2_get_object` is a new helper — add it to `r2_client.py` mirroring `r2_put_object`.)

- [ ] **Step 4: Add `r2_get_object`**

```bash
grep -n "put_object\|get_object" autopep/modal/autopep_agent/r2_client.py
```

If `get_object` doesn't exist, add it next to `put_object`:

```python
async def get_object(
    *, bucket: str, account_id: str, access_key_id: str, secret_access_key: str, key: str
) -> bytes:
    import boto3

    def _sync_get() -> bytes:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    return await asyncio.to_thread(_sync_get)
```

- [ ] **Step 5: Update tests**

In `test_biology_tools.py`, rename existing tests for `_generate_binder_candidates` to `_proteina_design`. Update fixtures: tests now mock `_read_workspace_text` instead of passing raw `target_structure` text. Add a new test:

```python
@pytest.mark.asyncio
async def test_proteina_design_threads_warm_start_path_through_to_endpoint(monkeypatch, ...) -> None:
    captured = {}
    async def fake_design(self, **kwargs):
        captured.update(kwargs)
        return {"pdbs": [{"filename": "candidate-1.pdb", "pdb": "ATOM..."}]}
    monkeypatch.setattr("autopep_agent.endpoint_clients.ProteinaClient.design", fake_design)
    monkeypatch.setattr(
        "autopep_agent.biology_tools._read_workspace_text",
        AsyncMock(side_effect=["TARGET_PDB_TEXT", "WARM_START_PDB_TEXT"]),
    )
    # ... tool_run_context, mock_db setup ...
    await _proteina_design(
        target_pdb_path="/workspace/runs/r1/inputs/6M0J.pdb",
        warm_start_structure_path="/workspace/runs/r1/folds/best.pdb",
    )
    assert captured["warm_start_structure"] == "WARM_START_PDB_TEXT"
    assert captured["warm_start_filename"] == "best.pdb"
```

Plus a test asserting `num_candidates=5` produces 5 candidate rows in the response when the endpoint returns 5 records.

- [ ] **Step 6: Run tests**

```bash
cd autopep/modal && pytest tests/test_biology_tools.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/modal/autopep_agent/biology_tools.py autopep/modal/autopep_agent/r2_client.py autopep/modal/tests/test_biology_tools.py
git commit -m "feat(autopep): rename to proteina_design, add warm_start_structure_path, batch-of-5"
```

---

### Task 4.4: Parallelize Chai folds with `asyncio.gather`

**Files:**
- Modify: `autopep/modal/autopep_agent/biology_tools.py:229-423`

**Track B · ~15 min**

- [ ] **Step 1: Read the existing `_fold_sequences_with_chai`**

```bash
sed -n '229,423p' autopep/modal/autopep_agent/biology_tools.py
```

You'll see the sequential `for request in complex_requests: ... await client.predict(...)` loop.

- [ ] **Step 2: Rewrite as `_chai_fold_complex` with `asyncio.gather`**

```python
async def _chai_fold_complex(
    candidate_ids: list[str],
    target_sequence: str | None = None,
    target_name: str = "target",
) -> dict[str, Any]:
    """Fold each candidate in parallel as a target+binder complex.

    Args:
      candidate_ids: protein_candidate row IDs to fold.
      target_sequence: Optional explicit target sequence; if None, each
        candidate's stored target_sequence is used (set when the candidate
        was created by proteina_design).
      target_name: FASTA record name for the target chain.
    """
    ctx = get_tool_run_context()
    cfg = _r2_config_from_env()
    writer = EventWriter(ctx.database_url)

    candidates = await load_candidates_by_id(
        ctx.database_url, workspace_id=ctx.workspace_id, candidate_ids=candidate_ids,
    )
    if not candidates:
        raise RuntimeError(f"No candidates found for ids {candidate_ids}")

    fold_requests = []
    shared_target = _clean_sequence(target_sequence)
    for candidate in candidates:
        target_seq = shared_target or _clean_sequence(candidate.get("target_sequence"))
        if target_seq is None:
            raise ValueError(
                f"target_sequence required (none on candidate {candidate['id']})"
            )
        fold_requests.append({
            "candidate": candidate,
            "fasta": build_complex_fasta(
                target_id=target_name.strip() or "target",
                target_sequence=target_seq,
                binder_id=str(candidate["id"]),
                binder_sequence=str(candidate["sequence"]).strip().upper(),
            ),
        })

    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="chai_1",
        request_json={
            "complexes": [
                {"candidate_id": str(r["candidate"]["id"]), "fasta": r["fasta"]}
                for r in fold_requests
            ],
            "num_diffn_samples": 1,
        },
        endpoint_url=ctx.chai_base_url,
    )

    client = ChaiClient(ctx.chai_base_url, ctx.chai_api_key)

    async def fold_one(request: dict[str, Any]) -> dict[str, Any]:
        candidate = request["candidate"]
        try:
            response = await client.predict(fasta=request["fasta"], num_diffn_samples=1)
            await _persist_chai_response(
                ctx=ctx,
                config=cfg,
                writer=writer,
                response=response,
                candidate_db_id=candidate["id"],
                filename_prefix=str(candidate["id"]),
            )
            return {"candidate_id": str(candidate["id"]), "ok": True, "response": response}
        except BaseException as exc:
            return {
                "candidate_id": str(candidate["id"]),
                "ok": False,
                "error": _summarize_error(exc),
            }

    try:
        results = await asyncio.gather(*(fold_one(r) for r in fold_requests))
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        raise

    failed = [r for r in results if not r["ok"]]
    succeeded = [r for r in results if r["ok"]]

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed" if not failed else "partial",
        response_json={"results": [{"candidate_id": r["candidate_id"]} for r in results]},
        error_summary="; ".join(r["error"] for r in failed)[:1400] if failed else None,
    )

    return {
        "succeeded": len(succeeded),
        "failed": len(failed),
        "candidates": [{"candidate_id": r["candidate_id"], "ok": r["ok"]} for r in results],
    }


chai_fold_complex = function_tool(
    _chai_fold_complex,
    name_override="chai_fold_complex",
    strict_mode=False,
)

# DELETE the old `fold_sequences_with_chai = function_tool(...)` export.
```

(`load_candidates_by_id` is a new db helper — add to `db.py`.)

- [ ] **Step 3: Add `load_candidates_by_id` to `db.py`**

```python
async def load_candidates_by_id(
    database_url: str,
    *,
    workspace_id: str,
    candidate_ids: list[str],
) -> list[dict[str, Any]]:
    if not candidate_ids:
        return []
    async with _connect(database_url) as conn:
        rows = await conn.fetch(
            """
            SELECT id, sequence, metadata_json
            FROM autopep_protein_candidate
            WHERE workspace_id = $1 AND id = ANY($2)
            """,
            workspace_id, candidate_ids,
        )
    return [
        {
            "id": str(r["id"]),
            "sequence": r["sequence"],
            "target_sequence": (r["metadata_json"] or {}).get("target_sequence"),
        }
        for r in rows
    ]
```

(Adapt the SQL column name `target_sequence` source — it may live in `metadata_json` or as a separate column. Check the existing schema.)

- [ ] **Step 4: Run tests**

```bash
cd autopep/modal && pytest tests/test_biology_tools.py -v
```

Expected: PASS (or fail in shape that points at the test fixture not being updated; fix and rerun).

- [ ] **Step 5: Add a parallel-fan-out test**

```python
@pytest.mark.asyncio
async def test_chai_fold_complex_runs_concurrently(monkeypatch, ...) -> None:
    """Fold-one calls overlap in time, not sequential."""
    import time
    call_starts = []

    async def slow_predict(self, fasta: str, num_diffn_samples: int = 1):
        call_starts.append(time.time())
        await asyncio.sleep(0.5)
        return {"cifs": [{"filename": f"x.cif", "cif": "data_x"}]}

    monkeypatch.setattr("autopep_agent.endpoint_clients.ChaiClient.predict", slow_predict)
    monkeypatch.setattr(
        "autopep_agent.db.load_candidates_by_id",
        AsyncMock(return_value=[
            {"id": "c1", "sequence": "AAA", "target_sequence": "TTT"},
            {"id": "c2", "sequence": "BBB", "target_sequence": "TTT"},
            {"id": "c3", "sequence": "CCC", "target_sequence": "TTT"},
        ]),
    )
    # ... tool_run_context, mock_persist setup ...

    start = time.time()
    await _chai_fold_complex(candidate_ids=["c1", "c2", "c3"], target_sequence="TTT")
    elapsed = time.time() - start

    # Sequential would take ≥1.5s; parallel should be ~0.5s.
    assert elapsed < 1.0, f"Chai folds appear to run sequentially ({elapsed:.2f}s)"
    assert max(call_starts) - min(call_starts) < 0.2, "Fold calls did not overlap"
```

- [ ] **Step 6: Run the parallel test**

```bash
cd autopep/modal && pytest tests/test_biology_tools.py::test_chai_fold_complex_runs_concurrently -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/modal/autopep_agent/biology_tools.py autopep/modal/autopep_agent/db.py autopep/modal/tests/test_biology_tools.py
git commit -m "feat(autopep): chai_fold_complex with asyncio.gather + load_candidates_by_id helper"
```

---

### Task 4.5: Verify "always-complex" folding behavior

**Track B · ~5 min**

- [ ] **Step 1: Add a test asserting the FASTA always contains both chains**

```python
@pytest.mark.asyncio
async def test_chai_fold_complex_always_includes_target_chain_in_fasta(monkeypatch, ...) -> None:
    captured = {}
    async def capture_predict(self, fasta: str, num_diffn_samples: int = 1):
        captured["fasta"] = fasta
        return {"cifs": []}
    monkeypatch.setattr("autopep_agent.endpoint_clients.ChaiClient.predict", capture_predict)
    # ... fixture setup ...

    await _chai_fold_complex(candidate_ids=["c1"], target_sequence="MAGTGT")

    assert ">target" in captured["fasta"]
    assert "MAGTGT" in captured["fasta"]
    assert ">c1" in captured["fasta"]
```

- [ ] **Step 2: Run**

```bash
cd autopep/modal && pytest tests/test_biology_tools.py::test_chai_fold_complex_always_includes_target_chain_in_fasta -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_biology_tools.py
git commit -m "test(autopep): assert chai_fold_complex always builds target+binder FASTA"
```

---

### Task 4.6: Mol* renders the complex with two chains

**Files:**
- Verify: `autopep/src/app/_components/molstar-viewer.tsx` and CIF assignment

**Track B · ~10 min**

- [ ] **Step 1: Verify the existing viewer can render a multi-chain CIF**

```bash
grep -nE "polymerColor|chainId|representation" autopep/src/app/_components/molstar-viewer.tsx | head -10
```

The Mol* default `polymer-cartoon` representation already colors by chain. Verify by hand: load any 2-chain CIF (e.g. 6M0J) — chains should be different colors.

- [ ] **Step 2: If needed, set `colorTheme` to `chain-id`**

Search for the representation builder:

```bash
grep -nE "PluginCommands|StateActions|StateTransforms" autopep/src/app/_components/molstar-viewer.tsx
```

If the viewer uses `pluginContext.behaviors.layout.leftPanelTabName` or similar — look for the `{ color: 'chain-id' }` setting and ensure it's set when loading the CIF. If not, add it.

(For MVP, if the default rendering already differentiates chains, skip this step. Only modify the viewer if the gate scenario shows monochrome rendering.)

- [ ] **Step 3: No commit unless changes were necessary.**

---

### Task 4.7: Swap Proteina + Chai tools in agent's tool list, update system prompt

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py`

**Sequential · after 4.3 + 4.4 · ~5 min**

- [ ] **Step 1: Update imports**

```python
from autopep_agent.biology_tools import (
    chai_fold_complex,
    proteina_design,
    score_candidate_interactions,  # still old name; Phase 5 swaps it
)
```

Drop the old `generate_binder_candidates` and `fold_sequences_with_chai` imports.

- [ ] **Step 2: Update tool list**

```python
tools=[
    literature_search,
    pdb_search,
    pdb_fetch,
    proteina_design,
    chai_fold_complex,
    score_candidate_interactions,
],
```

- [ ] **Step 3: Update system prompt to mention `proteina_design` and `chai_fold_complex`**

In `build_agent_instructions()`, replace any `generate_binder_candidates` / `fold_sequences_with_chai` references with `proteina_design` / `chai_fold_complex`.

- [ ] **Step 4: Run the suite**

```bash
cd autopep/modal && pytest -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py
git commit -m "feat(autopep): wire proteina_design + chai_fold_complex into agent tool list"
```

---

### Task 4.8: Phase 4 gate — deploy + S3 (uploaded-sequence fold) + batch-of-5 verification

**Sync point · ~25 min**

- [ ] **Step 1: Add S3 + batch-5 scenarios to smoke-roundtrip.ts**

```ts
async function runFoldUploadedScenario({ baseUrl, apiToken, target }: ScenarioArgs): Promise<void> {
	// 1. Create a workspace, upload a known PDB attachment.
	const { workspaceId } = await createWorkspace({ baseUrl, apiToken });
	const attachmentId = await uploadAttachment({
		baseUrl, apiToken, workspaceId,
		filePath: "test-fixtures/6M0J.pdb",
	});

	// 2. Send the prompt referencing the attachment.
	const prompt = "Fold this sequence with Chai and visualise the result alongside the target sequence: GVQPKNLSEIVNHIQQATLDLVKEAFLLPGRWDPHFG (binder candidate).";
	const { run } = await sendMessage({
		baseUrl, apiToken, workspaceId,
		prompt, attachmentRefs: [attachmentId],
	});
	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 360_000 });

	const events = await fetchAgentEvents({ runId: run.id });
	const chaiCalls = events.filter((e) =>
		e.type === "tool_call_started" &&
		(e.displayJson as { name?: string })?.name === "chai_fold_complex",
	);
	if (chaiCalls.length === 0) throw new Error("chai_fold_complex not called");

	const cifArtifacts = events.filter((e) =>
		e.type === "artifact_created" &&
		(e.displayJson as { kind?: string })?.kind === "chai_result",
	);
	if (cifArtifacts.length === 0) throw new Error("no chai_result artifact created");

	if (target === "prod") await deleteWorkspace({ baseUrl, apiToken, workspaceId });
}

async function runProteinaBatch5Scenario({ baseUrl, apiToken, target }: ScenarioArgs): Promise<void> {
	const prompt = "Design 5 binders for SARS-CoV-2 spike RBD, return all 5 candidates with sequences.";
	const { run, thread } = await sendMessage({ baseUrl, apiToken, prompt });
	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 360_000 });

	const candidateEvents = (await fetchAgentEvents({ runId: run.id })).filter(
		(e) => e.type === "candidate_ranked",
	);
	if (candidateEvents.length < 5) {
		throw new Error(`Only ${candidateEvents.length} candidates ranked (expected 5)`);
	}

	if (target === "prod") await deleteWorkspace({ baseUrl, apiToken, workspaceId: thread.workspaceId });
}
```

- [ ] **Step 2: Run deploy-and-validate**

```bash
cd autopep && DATABASE_URL=<prod neon> ./scripts/deploy-and-validate.sh 4
```

Append to `deploy-and-validate.sh` for Phase 4: `modal deploy tools/proteina-complexa/modal_app.py` (in case overrides need redeploy of the endpoint).

- [ ] **Step 3: Run S3 scenario against prod**

```bash
cd autopep && AUTOPEP_PROD_BASE_URL=<prod URL> bun run scripts/smoke-roundtrip.ts smoke_phase_4_s3 --target prod
```

Expected: green; chai_result CIF artifact created.

- [ ] **Step 4: Run batch-5 verification**

```bash
cd autopep && bun run scripts/smoke-roundtrip.ts smoke_phase_4_batch5 --target prod
```

Expected: green; 5 candidate rows in DB.

- [ ] **Step 5: Manual UI smoke for Mol* multi-chain rendering**

Open prod, find a workspace from the S3 run, open the chai_result CIF artifact in Mol*. Verify both chains visible in distinct colors.

- [ ] **Step 6: Paste green output into PR description; merge.**

- [ ] **Step 7: Phase 4 done.**

---
## Phase 5: Parallel score wiring + ranking final message

**Goal:** Wire `tools/quality-scorers` (solubility, expressibility, plausibility — currently orphaned) into the `score_candidates` tool. Fan out via `asyncio.gather` to both the protein-interaction scoring endpoint AND the quality-scorers endpoint. Persist per-scorer rows. Update the system prompt so the LLM produces a final ranked summary referencing each scorer dimension.

**Spec reference:** §Tool surface (score_candidates), §Phase plan Phase 5.

**Gate scenario (Phase 5, S4):** Full demo: "Generate a protein that binds to SARS-CoV-2 main protease (3CL-protease)." Tool-call sequence: `literature_search`, `pdb_search`, `pdb_fetch`, (optional `Shell`), `proteina_design` (returns 5), `chai_fold_complex` (5 parallel folds), `score_candidates` (one call, both scorers parallel), final assistant message. Final message names a top candidate, lists scores by scorer, cites ≥2 literature references, mentions the PDB target ID. Candidates table shows all 5 with all score columns populated. Run completes in <8 minutes.

**Parallelization:**
- **Track A (gating, runs first):** Tasks 5.1 → 5.2 (smoke-test + repair the quality-scorers Modal app).
- **Track B (after A):** Tasks 5.3 → 5.4 → 5.5 (rewrite `score_candidates` to fan out, persist per-scorer rows, fail-tolerant).
- **Track C (independent):** Task 5.6 (system-prompt rewrite for ranking).
- **Then sequential:** Task 5.7 (Phase 5 gate — full S4 scenario).

---

### Task 5.1: Smoke-test the quality-scorers Modal app

**Track A · gating · ~10 min**

- [ ] **Step 1: Read the existing Modal app**

```bash
head -100 tools/quality-scorers/inference_modal_app.py
grep -nE "@app\.|@web|fastapi_endpoint" tools/quality-scorers/inference_modal_app.py | head
```

Locate the HTTP endpoint(s) the app exposes (likely `/score` or similar).

- [ ] **Step 2: Deploy the app to Modal (if not already deployed)**

```bash
cd <repo-root>
modal deploy tools/quality-scorers/inference_modal_app.py
modal app list | grep quality
```

Note the deployed URL pattern.

- [ ] **Step 3: Hit the endpoint with a known-good sequence**

Use a sequence with established solubility/expressibility characteristics — e.g. ubiquitin (`MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG`) is highly soluble:

```bash
curl -X POST "$QUALITY_SCORERS_URL/score" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $QUALITY_SCORERS_API_KEY" \
  -d '{"sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"}'
```

Expected: a JSON response with `solubility`, `expressibility`, `plausibility` numeric scores (or whatever the actual schema is — confirm and document).

- [ ] **Step 4: If `joblib` loading fails on the deployed app**

The risk flagged in the spec: classifier-head joblib files at `tools/quality-scorers/.../*.joblib` may not load with the current `scikit-learn` version. If the deployed endpoint returns a 500, inspect the Modal logs:

```bash
modal app logs <quality-scorers-app-name> 2>&1 | tail -100
```

Common fixes:
- Pin `scikit-learn` to the version the joblibs were saved under (find the version in the joblib file header or the original training script).
- Re-train the classifier heads with a current scikit-learn (out of scope for this plan; if needed, capture as a follow-up issue).
- Replace failing scorer with a stub that returns a fixed neutral score (last-resort to unblock Phase 5; document the gap).

- [ ] **Step 5: Document the deployed URL + API key in env**

Add to `autopep/modal/autopep_agent/config.py` if not present:

```python
modal_quality_scorers_url: str = field_from_env("AUTOPEP_MODAL_QUALITY_SCORERS_URL")
modal_quality_scorers_api_key: str = field_from_env("AUTOPEP_MODAL_QUALITY_SCORERS_API_KEY")
```

Wire into `ToolRunContext` in `run_context.py` so the new tool fan-out can read them.

- [ ] **Step 6: Commit (config + ToolRunContext changes)**

```bash
git add autopep/modal/autopep_agent/config.py autopep/modal/autopep_agent/run_context.py
git commit -m "feat(autopep): config + ToolRunContext exposes quality-scorers endpoint"
```

---

### Task 5.2: Add `QualityScorersClient`

**Files:**
- Modify: `autopep/modal/autopep_agent/endpoint_clients.py`

**Track A · gating · ~5 min**

- [ ] **Step 1: Add the client**

Append to `endpoint_clients.py`:

```python
class QualityScorersClient(ModalEndpointClient):
    async def score(self, sequence: str) -> dict[str, Any]:
        return await self.post_json(
            "/score",  # confirm path against tools/quality-scorers/inference_modal_app.py
            {"sequence": sequence},
        )

    async def score_batch(self, sequences: Sequence[str]) -> dict[str, Any]:
        # If the Modal app exposes a batch endpoint, use it. Otherwise gather one-at-a-time.
        # Confirm path with the Modal app source.
        return await self.post_json(
            "/score_batch",
            {"sequences": list(sequences)},
        )
```

- [ ] **Step 2: Confirm the endpoint paths**

```bash
grep -nE "@app\.function\|@web_endpoint\|fastapi_endpoint" tools/quality-scorers/inference_modal_app.py
grep -nE "POST|score|batch" tools/quality-scorers/inference_modal_app.py | head -10
```

Adjust the client's URL paths to match.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/endpoint_clients.py
git commit -m "feat(autopep): add QualityScorersClient"
```

---

### Task 5.3: `score_candidates` — failing tests

**Files:**
- Create: `autopep/modal/tests/test_scoring_tools.py`

**Track B · after A · ~10 min**

- [ ] **Step 1: Write failing tests**

```python
"""Tests for the unified score_candidates tool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_score_candidates_fans_out_in_parallel(monkeypatch, tool_run_context, mock_db) -> None:
    interaction_payload = {
        "results": [
            {"id": "cand-1", "scores": {"dscript": {"interaction_probability": 0.91}, "prodigy": {"delta_g_kcal_mol": -10.2}}},
        ],
    }
    quality_payload = {
        "results": [
            {"id": "cand-1", "scores": {"solubility": 0.78, "expressibility": 0.65, "plausibility": 0.81}},
        ],
    }

    interaction_mock = AsyncMock(return_value=interaction_payload)
    quality_mock = AsyncMock(return_value=quality_payload)
    monkeypatch.setattr("autopep_agent.endpoint_clients.ScoringClient.score_batch", interaction_mock)
    monkeypatch.setattr("autopep_agent.endpoint_clients.QualityScorersClient.score_batch", quality_mock)
    monkeypatch.setattr(
        "autopep_agent.db.load_candidates_by_id",
        AsyncMock(return_value=[{"id": "cand-1", "sequence": "AAA", "target_sequence": "TTT"}]),
    )

    from autopep_agent.scoring_tools import _score_candidates

    result = await _score_candidates(
        target_name="3CL-protease",
        target_sequence="MAGVQ",
        candidate_ids=["cand-1"],
    )

    interaction_mock.assert_awaited_once()
    quality_mock.assert_awaited_once()
    assert "cand-1" in {r["candidate_id"] for r in result["results"]}
    cand_1 = next(r for r in result["results"] if r["candidate_id"] == "cand-1")
    assert cand_1["scores"]["dscript"]["interaction_probability"] == 0.91
    assert cand_1["scores"]["solubility"] == 0.78


@pytest.mark.asyncio
async def test_score_candidates_persists_per_scorer_rows(monkeypatch, tool_run_context, mock_db) -> None:
    inserted_rows = []

    async def fake_insert_scores(database_url, *, workspace_id, run_id, candidate_id, model_inference_id, rows):
        inserted_rows.extend(rows)
    monkeypatch.setattr("autopep_agent.db.insert_candidate_scores", fake_insert_scores)
    # ... mocks for endpoint clients ...

    from autopep_agent.scoring_tools import _score_candidates
    await _score_candidates(target_name="t", target_sequence="T", candidate_ids=["c1"])

    scorers = {row["scorer"] for row in inserted_rows}
    assert {"dscript", "prodigy", "solubility", "expressibility", "plausibility"}.issubset(scorers)


@pytest.mark.asyncio
async def test_score_candidates_partial_when_one_endpoint_fails(monkeypatch, tool_run_context, mock_db) -> None:
    monkeypatch.setattr(
        "autopep_agent.endpoint_clients.QualityScorersClient.score_batch",
        AsyncMock(side_effect=RuntimeError("quality scorer down")),
    )
    monkeypatch.setattr(
        "autopep_agent.endpoint_clients.ScoringClient.score_batch",
        AsyncMock(return_value={"results": [{"id": "c1", "scores": {"dscript": {"interaction_probability": 0.7}}}]}),
    )
    monkeypatch.setattr(
        "autopep_agent.db.load_candidates_by_id",
        AsyncMock(return_value=[{"id": "c1", "sequence": "A", "target_sequence": "T"}]),
    )

    from autopep_agent.scoring_tools import _score_candidates
    result = await _score_candidates(target_name="t", target_sequence="T", candidate_ids=["c1"])

    assert "errors" in result and "quality_scorers" in result["errors"]
    cand = next(r for r in result["results"] if r["candidate_id"] == "c1")
    assert cand["scores"]["dscript"]["interaction_probability"] == 0.7
    assert cand["scores"].get("solubility") is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd autopep/modal && pytest tests/test_scoring_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/tests/test_scoring_tools.py
git commit -m "test(autopep): failing tests for unified score_candidates"
```

---

### Task 5.4: `score_candidates` — implementation

**Files:**
- Create: `autopep/modal/autopep_agent/scoring_tools.py`

**Track B · ~20 min**

- [ ] **Step 1: Implement**

```python
"""score_candidates — fan-out scoring across interaction + quality endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from agents import function_tool

from autopep_agent.db import (
    complete_model_inference,
    create_model_inference,
    insert_candidate_scores,
    load_candidates_by_id,
)
from autopep_agent.endpoint_clients import (
    QualityScorersClient,
    ScoringClient,
)
from autopep_agent.run_context import get_tool_run_context


def _summarize_error(exc: BaseException) -> str:
    return (str(exc).strip() or exc.__class__.__name__)[:1400]


def _build_interaction_items(
    candidates: list[dict[str, Any]],
    *,
    target_name: str,
    target_sequence: str,
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(c["id"]),
            "protein_a": {"name": target_name, "sequence": target_sequence},
            "protein_b": {"name": str(c["id"]), "sequence": (c["sequence"] or "").upper()},
        }
        for c in candidates
    ]


def _interaction_rows(
    candidate_id: str,
    model_inference_id: str,
    scores: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dscript = scores.get("dscript")
    if isinstance(dscript, Mapping):
        rows.append({
            "scorer": "dscript",
            "value": float(dscript.get("interaction_probability", 0.0)),
            "unit": "probability",
            "label": dscript.get("label"),
            "values": dict(dscript),
            "model_inference_id": model_inference_id,
            "status": "ok",
        })
    prodigy = scores.get("prodigy")
    if isinstance(prodigy, Mapping):
        rows.append({
            "scorer": "prodigy",
            "value": float(prodigy.get("delta_g_kcal_mol", 0.0)),
            "unit": "kcal/mol",
            "label": prodigy.get("label"),
            "values": dict(prodigy),
            "model_inference_id": model_inference_id,
            "status": "ok",
        })
    return rows


def _quality_rows(
    candidate_id: str,
    model_inference_id: str,
    scores: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scorer in ("solubility", "expressibility", "plausibility"):
        value = scores.get(scorer)
        if value is None:
            continue
        rows.append({
            "scorer": scorer,
            "value": float(value),
            "unit": "probability",
            "label": None,
            "values": {scorer: value},
            "model_inference_id": model_inference_id,
            "status": "ok",
        })
    return rows


async def _run_interaction_scoring(
    ctx: Any,
    items: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, str]:
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="protein_interaction_scoring",
        request_json={"items": items},
        endpoint_url=ctx.scoring_base_url,
    )
    try:
        client = ScoringClient(ctx.scoring_base_url, ctx.scoring_api_key)
        response = await client.score_batch(items)
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        return None, _summarize_error(exc), inference_id

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"raw": response} if not isinstance(response, dict) else response,
    )
    return response, None, inference_id


async def _run_quality_scoring(
    ctx: Any,
    sequences: list[tuple[str, str]],
) -> tuple[dict[str, Any] | None, str | None, str]:
    inference_id = await create_model_inference(
        ctx.database_url,
        workspace_id=ctx.workspace_id,
        run_id=ctx.run_id,
        model_name="quality_scorers",
        request_json={"sequences": [s[1] for s in sequences]},
        endpoint_url=ctx.quality_scorers_base_url,
    )
    try:
        client = QualityScorersClient(ctx.quality_scorers_base_url, ctx.quality_scorers_api_key)
        response = await client.score_batch([s[1] for s in sequences])
    except BaseException as exc:
        await complete_model_inference(
            ctx.database_url,
            inference_id=inference_id,
            status="failed",
            response_json={},
            error_summary=_summarize_error(exc),
        )
        return None, _summarize_error(exc), inference_id

    await complete_model_inference(
        ctx.database_url,
        inference_id=inference_id,
        status="completed",
        response_json={"raw": response} if not isinstance(response, dict) else response,
    )
    return response, None, inference_id


def _index_quality_response(
    response: Mapping[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map candidate_id → quality scores dict."""
    if not response:
        return {}
    by_index: list[Mapping[str, Any]] = response.get("results") or []
    indexed: dict[str, dict[str, Any]] = {}
    for i, cand in enumerate(candidates):
        if i < len(by_index) and isinstance(by_index[i], Mapping):
            indexed[str(cand["id"])] = dict(by_index[i].get("scores") or {})
    # If the endpoint returns by id, prefer that
    for entry in by_index:
        if isinstance(entry, Mapping) and entry.get("id"):
            indexed[str(entry["id"])] = dict(entry.get("scores") or {})
    return indexed


async def _score_candidates(
    target_name: str,
    target_sequence: str,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Score candidates in parallel across interaction + quality endpoints."""
    ctx = get_tool_run_context()

    candidates = await load_candidates_by_id(
        ctx.database_url, workspace_id=ctx.workspace_id, candidate_ids=candidate_ids
    )
    if not candidates:
        raise RuntimeError(f"No candidates found for ids {candidate_ids}")

    interaction_items = _build_interaction_items(
        candidates, target_name=target_name, target_sequence=target_sequence
    )
    sequences = [(str(c["id"]), (c["sequence"] or "").upper()) for c in candidates]

    interaction_result, quality_result = await asyncio.gather(
        _run_interaction_scoring(ctx, interaction_items),
        _run_quality_scoring(ctx, sequences),
        return_exceptions=False,
    )
    interaction_response, interaction_error, interaction_inference_id = interaction_result
    quality_response, quality_error, quality_inference_id = quality_result

    by_id = _index_quality_response(quality_response, candidates)

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        cid = str(candidate["id"])
        # interaction
        interaction_scores: dict[str, Any] = {}
        if interaction_response:
            for row in interaction_response.get("results") or []:
                if isinstance(row, Mapping) and str(row.get("id")) == cid:
                    interaction_scores = dict(row.get("scores") or {})
                    break
        quality_scores = by_id.get(cid, {})
        merged = {**interaction_scores, **quality_scores}
        results.append({"candidate_id": cid, "scores": merged})

        # persist
        rows = (
            _interaction_rows(cid, interaction_inference_id, interaction_scores)
            + _quality_rows(cid, quality_inference_id, quality_scores)
        )
        if rows:
            await insert_candidate_scores(
                ctx.database_url,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                candidate_id=cid,
                model_inference_id=interaction_inference_id,
                rows=rows,
            )

    response: dict[str, Any] = {
        "target_name": target_name,
        "results": results,
    }
    errors: dict[str, str] = {}
    if interaction_error:
        errors["interaction"] = interaction_error
    if quality_error:
        errors["quality_scorers"] = quality_error
    if errors:
        response["errors"] = errors

    return response


score_candidates = function_tool(
    _score_candidates,
    name_override="score_candidates",
    strict_mode=False,
)
```

(`ToolRunContext` needs new fields `quality_scorers_base_url`, `quality_scorers_api_key` — add them in `run_context.py` and populate from `WorkerConfig` in `runner.py`'s `set_tool_run_context` call.)

- [ ] **Step 2: Update `run_context.py`**

```python
@dataclass(frozen=True)
class ToolRunContext:
    workspace_id: str
    run_id: str
    database_url: str
    proteina_base_url: str
    proteina_api_key: str
    chai_base_url: str
    chai_api_key: str
    scoring_base_url: str
    scoring_api_key: str
    quality_scorers_base_url: str
    quality_scorers_api_key: str
```

Update the two `set_tool_run_context` calls in `runner.py` to pass the new fields from `config`.

- [ ] **Step 3: Run tests**

```bash
cd autopep/modal && pytest tests/test_scoring_tools.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/scoring_tools.py autopep/modal/autopep_agent/run_context.py autopep/modal/autopep_agent/runner.py
git commit -m "feat(autopep): unified score_candidates with parallel interaction + quality fan-out"
```

---

### Task 5.5: Wire `score_candidates` into agent + delete `score_candidate_interactions`

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py`
- Modify: `autopep/modal/autopep_agent/biology_tools.py` (delete `_score_candidate_interactions` + its `function_tool` export)

**Track B · ~5 min**

- [ ] **Step 1: Update agent imports + tool list**

```python
from autopep_agent.scoring_tools import score_candidates

tools=[
    literature_search,
    pdb_search,
    pdb_fetch,
    proteina_design,
    chai_fold_complex,
    score_candidates,
],
```

Drop the import of `score_candidate_interactions` from `biology_tools`.

- [ ] **Step 2: Delete `_score_candidate_interactions` from `biology_tools.py`**

```bash
grep -n "_score_candidate_interactions\|score_candidate_interactions" autopep/modal/autopep_agent/biology_tools.py
```

Remove the function and its `function_tool` export.

- [ ] **Step 3: Run the suite**

```bash
cd autopep/modal && pytest -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/autopep_agent/biology_tools.py
git commit -m "feat(autopep): wire score_candidates into agent; delete old interaction-only tool"
```

---

### Task 5.6: System-prompt rewrite for ranking final message

**Files:**
- Modify: `autopep/modal/autopep_agent/runner.py:289-326`

**Track C · independent · ~5 min**

- [ ] **Step 1: Rewrite `build_agent_instructions`**

Replace the function body with:

```python
def build_agent_instructions(enabled_recipes: list[str] | None = None) -> str:
    recipe_bodies = [r.strip() for r in (enabled_recipes or []) if r.strip()]
    recipes_text = "\n\n".join(f"Recipe:\n{r}" for r in recipe_bodies)

    sections = [
        "You are Autopep, an agent for protein binder design and analysis.",
        (
            "Use life-science-research discipline: cite uncertainty, prefer "
            "primary biomedical evidence, and distinguish literature evidence "
            "from model output. Read /skills/life-science-research/ before "
            "answering literature, structure-retrieval, or experimental-evidence "
            "questions."
        ),
        (
            "Tool surface: literature_search (PubMed + Europe PMC + preprints), "
            "pdb_search (RCSB, chain length capped at 500), pdb_fetch (download "
            "+ register artifact + extract sequence), proteina_design (5 "
            "candidates per call, optional warm-start), chai_fold_complex "
            "(parallel target+binder folds), score_candidates (interaction + "
            "quality scorers in parallel)."
        ),
        (
            "Sandbox: you have Shell + Filesystem + Compaction capabilities. "
            "Workspace is mounted at /workspace/. Use `python -c \"from Bio.PDB ...\"` "
            "for ad-hoc structural analysis (compute hotspots from SITE "
            "records, extract specific residue ranges, splice motifs)."
        ),
        (
            "Typical binder-design loop: literature_search → pdb_search → "
            "pdb_fetch → optionally inspect with shell+BioPython for hotspots "
            "→ proteina_design → chai_fold_complex → score_candidates → "
            "present a ranked summary. You may iterate within the same run "
            "(e.g., warm-start Proteina from your best fold)."
        ),
        (
            "Final message format for binder runs: rank candidates by combined "
            "evidence (interaction probability, ΔG, solubility, expressibility, "
            "plausibility). Name the top candidate. Justify the ranking with "
            "concrete numbers from score_candidates. Cite the literature you "
            "retrieved with DOIs and the PDB target ID. Distinguish what was "
            "computed (Proteina/Chai/scorers) from what was retrieved "
            "(literature/structure)."
        ),
        (
            "Use computational screening language only. Do not claim wet-lab "
            "validation, clinical efficacy, safety, or therapeutic readiness."
        ),
    ]

    if recipes_text:
        sections.append("Enabled recipes:\n" + recipes_text)

    return "\n\n".join(sections)
```

- [ ] **Step 2: Run the test that asserts instructions content**

```bash
cd autopep/modal && pytest tests/test_runner.py -k instructions -v
```

Update any test assertions that look for old strings (e.g. "MVP one-loop workflow") — change them to look for the new tool names.

- [ ] **Step 3: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_runner.py
git commit -m "feat(autopep): rewrite system prompt for the 6-tool surface + ranked final summary"
```

---

### Task 5.7: Phase 5 gate — full S4 demo on prod

**Sync point · ~30 min**

- [ ] **Step 1: Add S4 scenario to smoke-roundtrip.ts**

```ts
async function runFullDemoScenario({ baseUrl, apiToken, target }: ScenarioArgs): Promise<void> {
	const prompt = "Generate a protein that binds to SARS-CoV-2 main protease (3CL-protease).";
	const start = Date.now();
	const { run, thread } = await sendMessage({ baseUrl, apiToken, prompt });

	await waitForRunCompletion({ baseUrl, apiToken, runId: run.id, timeoutMs: 8 * 60_000 });
	const elapsed = Date.now() - start;
	if (elapsed > 8 * 60_000) {
		throw new Error(`Run took ${(elapsed / 1000).toFixed(0)}s, expected <480s`);
	}

	const events = await fetchAgentEvents({ runId: run.id });
	const toolNames = events
		.filter((e) => e.type === "tool_call_started")
		.map((e) => (e.displayJson as { name?: string })?.name);

	for (const required of ["literature_search", "pdb_search", "pdb_fetch", "proteina_design", "chai_fold_complex", "score_candidates"]) {
		if (!toolNames.includes(required)) {
			throw new Error(`Required tool ${required} not called`);
		}
	}

	const candidates = await fetchCandidates({ baseUrl, apiToken, runId: run.id });
	if (candidates.length < 5) {
		throw new Error(`Only ${candidates.length} candidates produced (expected ≥5)`);
	}
	for (const cand of candidates) {
		const requiredScorers = ["dscript", "prodigy", "solubility", "expressibility", "plausibility"];
		const present = new Set(cand.scores.map((s: { scorer: string }) => s.scorer));
		for (const s of requiredScorers) {
			if (!present.has(s)) {
				throw new Error(`Candidate ${cand.id} missing scorer ${s}`);
			}
		}
	}

	const finalMessage = await fetchLatestAssistantMessage({ baseUrl, apiToken, threadId: thread.id });
	if (!finalMessage.content.match(/10\.\d{4,9}\/\S+/g)?.length || finalMessage.content.match(/10\.\d{4,9}\/\S+/g)!.length < 2) {
		throw new Error("Final message has <2 DOI citations");
	}
	if (!/\bcandidate-?\d+\b/i.test(finalMessage.content)) {
		throw new Error("Final message does not name a top candidate");
	}
	if (!/6LU7|6Y2E|6Y84/.test(finalMessage.content)) {
		throw new Error("Final message does not mention a 3CL-protease PDB target ID");
	}

	if (target === "prod") await deleteWorkspace({ baseUrl, apiToken, workspaceId: thread.workspaceId });
}
```

- [ ] **Step 2: Run deploy-and-validate**

```bash
cd autopep && DATABASE_URL=<prod neon> ./scripts/deploy-and-validate.sh 5
```

Append to `deploy-and-validate.sh` for Phase 5: `modal deploy tools/quality-scorers/inference_modal_app.py`.

- [ ] **Step 3: Run S4 against prod**

```bash
cd autopep && AUTOPEP_PROD_BASE_URL=<prod URL> bun run scripts/smoke-roundtrip.ts smoke_phase_5 --target prod
```

Expected: green within <8 minutes.

- [ ] **Step 4: Manual UI verification**

Open prod, watch the run live. Verify:
- All 6 tool-call cards appear in chat-stream order.
- Files panel populates: PDB target, 5 Proteina candidates, 5 Chai folds.
- Candidates table shows 5 rows with all 5 score columns populated.
- Final assistant message names the top candidate with concrete scores + DOIs.

- [ ] **Step 5: Paste green output into PR description; merge.**

- [ ] **Step 6: Phase 5 done.**

---
## Phase 6: UI acceptance

**Goal:** No new code unless Phases 0–5 reveal UI defects. Pure validation phase. Drive the deployed UI through the full demo, capture screenshots, and add a Playwright test that re-runs the critical path on every PR going forward.

**Spec reference:** §Phase plan Phase 6.

**Gate scenario (Phase 6):** End-to-end UI walkthrough on prod. Run S4 (full demo). Run S5 follow-up. Open second workspace, run S1, switch back, verify state preserved. Screenshots committed. Playwright test green.

**Parallelization:**
- **Track A:** Tasks 6.1 → 6.2 → 6.3 (Playwright bootstrap + write the test + run it).
- **Track B:** Tasks 6.4 → 6.5 (manual walkthrough + capture screenshots).
- **Track C:** Task 6.6 (multi-workspace switch verification).
- **Sync:** Task 6.7 (Phase 6 gate).

---

### Task 6.1: Bootstrap Playwright

**Files:**
- Create: `autopep/playwright.config.ts`
- Create: `autopep/tests/e2e/full-demo.spec.ts`

**Track A · ~10 min**

- [ ] **Step 1: Confirm Playwright is installed**

```bash
grep -E "playwright" autopep/package.json
```

If absent:

```bash
cd autopep && bun add -D @playwright/test
bunx playwright install chromium
```

- [ ] **Step 2: Create `playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
	testDir: "./tests/e2e",
	timeout: 10 * 60_000, // 10min runs allowed for full demo
	use: {
		baseURL: process.env.AUTOPEP_E2E_BASE_URL ?? "http://localhost:3000",
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
		video: "retain-on-failure",
	},
	reporter: [["html", { outputFolder: "playwright-report" }]],
});
```

- [ ] **Step 3: Add `package.json` script**

```json
"e2e": "playwright test",
"e2e:ui": "playwright test --ui",
```

- [ ] **Step 4: Commit**

```bash
git add autopep/playwright.config.ts autopep/package.json autopep/bun.lock
git commit -m "feat(autopep): bootstrap Playwright config for e2e tests"
```

---

### Task 6.2: Write the full-demo Playwright test

**Files:**
- Create: `autopep/tests/e2e/full-demo.spec.ts`

**Track A · ~25 min**

- [ ] **Step 1: Implement the test**

```ts
import { test, expect } from "@playwright/test";

const TEST_EMAIL = process.env.AUTOPEP_E2E_TEST_EMAIL!;
const TEST_PASSWORD = process.env.AUTOPEP_E2E_TEST_PASSWORD!;

const PROMPT_BINDER = "Generate a protein that binds to SARS-CoV-2 main protease (3CL-protease).";
const PROMPT_FOLLOWUP_1 = "What was the top candidate's solubility score?";
const PROMPT_FOLLOWUP_2 = "Now show me what residues 40-60 look like in the fold for that candidate.";
const PROMPT_LITERATURE = "Find literature about EGFR small-molecule inhibitor preprints from the last year.";
const PROMPT_PDB_TARGET = "Remind me which PDB ID we used for the target.";

test.beforeEach(async ({ page }) => {
	await page.goto("/");
	await page.getByRole("link", { name: /sign in/i }).click();
	await page.getByLabel(/email/i).fill(TEST_EMAIL);
	await page.getByLabel(/password/i).fill(TEST_PASSWORD);
	await page.getByRole("button", { name: /sign in/i }).click();
	await expect(page).toHaveURL(/\/$/);
});

test("Phase 6 — full demo end-to-end on prod", async ({ page }) => {
	// 1. Send the binder-design prompt and watch live streaming.
	const startTime = Date.now();
	const composer = page.getByRole("textbox", { name: /message/i });
	await composer.fill(PROMPT_BINDER);
	await composer.press("Enter");

	// Token streaming: an assistant text update should appear in <5s.
	await expect(page.getByTestId("assistant-message").first()).toBeVisible({ timeout: 5_000 });

	// Tool-call cards: at least 6 should appear before the run completes.
	const toolCallCards = page.getByTestId("tool-call-card");
	await expect.poll(async () => await toolCallCards.count(), { timeout: 8 * 60_000 }).toBeGreaterThanOrEqual(6);

	// Files panel: at least 5 chai_result CIFs.
	const cifFiles = page.locator("[data-artifact-kind='chai_result']");
	await expect.poll(async () => await cifFiles.count(), { timeout: 8 * 60_000 }).toBeGreaterThanOrEqual(5);

	// Candidates table: 5 rows, all score columns populated.
	const candidateRows = page.getByTestId("candidate-row");
	await expect.poll(async () => await candidateRows.count(), { timeout: 8 * 60_000 }).toBeGreaterThanOrEqual(5);
	for (const scorer of ["dscript", "prodigy", "solubility", "expressibility", "plausibility"]) {
		const cells = page.locator(`[data-scorer='${scorer}']`);
		await expect.poll(async () => await cells.count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(5);
	}

	// Mol* viewer opens at least one candidate.
	await page.getByTestId("candidate-row").first().click();
	await expect(page.getByTestId("molstar-canvas")).toBeVisible({ timeout: 30_000 });

	const elapsed = Date.now() - startTime;
	expect(elapsed).toBeLessThan(8 * 60_000);

	// 2. Multi-turn S5 follow-ups.
	await composer.fill(PROMPT_FOLLOWUP_1);
	await composer.press("Enter");
	const followupMessage = page.getByTestId("assistant-message").last();
	await expect(followupMessage).toContainText(/0\.\d+/, { timeout: 60_000 }); // some numeric score

	await composer.fill(PROMPT_FOLLOWUP_2);
	await composer.press("Enter");
	const residueMessage = page.getByTestId("assistant-message").last();
	await expect(residueMessage).toContainText(/residue|Met|Ala|Gly|Lys|Cys/i, { timeout: 60_000 });
});

test("Phase 6 — multi-workspace switch preserves state", async ({ page }) => {
	// Workspace A: binder run
	const composer = page.getByRole("textbox", { name: /message/i });
	await composer.fill(PROMPT_LITERATURE);
	await composer.press("Enter");
	await expect(page.getByTestId("assistant-message").last()).toBeVisible({ timeout: 90_000 });
	const workspaceASelector = page.getByTestId("workspace-rail-active");
	await expect(workspaceASelector).toBeVisible();

	// Open new workspace (Workspace B)
	await page.getByTestId("new-workspace-button").click();
	await composer.fill("hi");
	await composer.press("Enter");
	await expect(page.getByTestId("assistant-message").last()).toBeVisible({ timeout: 30_000 });

	// Switch back to workspace A
	await page.getByTestId("workspace-rail").locator("button").first().click();
	// Send PDB-recall prompt
	await composer.fill(PROMPT_PDB_TARGET);
	await composer.press("Enter");
	const pdbMessage = page.getByTestId("assistant-message").last();
	// Should reference one of the 3CL-protease PDB IDs from the prior turn
	// — but only if Workspace A had a prior binder run. If it only had a
	// literature search, the agent should say it didn't fetch a PDB yet.
	await expect(pdbMessage).toBeVisible({ timeout: 60_000 });
});
```

(The `data-testid` attributes referenced — `assistant-message`, `tool-call-card`, `candidate-row`, `molstar-canvas`, `workspace-rail-active`, `new-workspace-button`, `workspace-rail`, `data-artifact-kind`, `data-scorer` — must exist on the corresponding components. If they don't, add them in this task.)

- [ ] **Step 2: Add `data-testid` attributes to UI components**

For each missing `data-testid`, find the relevant component and add the attribute:

```bash
grep -rnE "ChatStreamItem|CandidatesTable|MolstarStage|WorkspaceRail" autopep/src/app/_components | head -10
```

Example: in `chat-stream-item.tsx`, on the assistant-message render branch, add `data-testid="assistant-message"` to the outer container.

Be conservative — only add `data-testid` where the test references it. Each attribute add is a small commit.

- [ ] **Step 3: Run the test against local dev**

```bash
cd autopep && bun run dev &  # in background
sleep 10
AUTOPEP_E2E_BASE_URL=http://localhost:3000 \
AUTOPEP_E2E_TEST_EMAIL=<test email> \
AUTOPEP_E2E_TEST_PASSWORD=<test password> \
bun run e2e tests/e2e/full-demo.spec.ts
```

Expected: PASS (likely with one or two iterations to fix selectors).

- [ ] **Step 4: Commit**

```bash
git add autopep/tests/e2e/full-demo.spec.ts autopep/src/app/_components/
git commit -m "test(autopep): Playwright e2e full-demo + multi-workspace test"
```

---

### Task 6.3: Run Playwright against prod

**Track A · ~10 min**

- [ ] **Step 1: Run with prod URL**

```bash
cd autopep && \
AUTOPEP_E2E_BASE_URL=<prod URL> \
AUTOPEP_E2E_TEST_EMAIL=<test email> \
AUTOPEP_E2E_TEST_PASSWORD=<test password> \
bun run e2e tests/e2e/full-demo.spec.ts
```

Expected: PASS within 10 minutes.

- [ ] **Step 2: If failures, debug**

```bash
bun run e2e:ui  # interactive debugger
```

Common failures:
- Selectors that worked locally don't work on prod — add data-testids.
- Auth flow differs (e.g., prod uses passkey not password) — adjust login flow.
- Latency on prod is higher than local — bump per-step timeouts.

Fix and re-run.

- [ ] **Step 3: Save the trace + report**

Playwright auto-saves to `playwright-report/`. Don't check in the full report (large), but reference its location in the PR description.

- [ ] **Step 4: No commit unless code changed.**

---

### Task 6.4: Manual demo walkthrough on prod

**Track B · ~20 min**

Run the same demo by hand and capture screenshots. The screenshots become the visual record committed to the repo.

- [ ] **Step 1: Open prod URL, sign in**

- [ ] **Step 2: Send the S4 prompt**

"Generate a protein that binds to SARS-CoV-2 main protease (3CL-protease)."

- [ ] **Step 3: Capture key moments**

For each, take a screenshot at native resolution (Cmd+Shift+4 on macOS):

1. **`chat-streaming.png`** — chat panel mid-run, with token deltas visibly rendering (a partial assistant text + ≥1 tool-call card with status "running").
2. **`tool-cards-complete.png`** — all 6 tool-call cards visible after run completes.
3. **`files-panel-populated.png`** — files panel showing the PDB target + 5 Proteina candidates + 5 Chai CIFs.
4. **`candidates-table.png`** — candidates table with 5 rows and all 5 score columns populated.
5. **`molstar-complex.png`** — Mol* viewer rendering one of the chai_result CIFs with two chains in distinct colors.
6. **`final-summary.png`** — final assistant message with ranked candidates, DOIs, PDB target ID.

- [ ] **Step 4: Save into the spec screenshots directory**

```bash
mkdir -p docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline
mv ~/Desktop/chat-streaming.png docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/01-chat-streaming.png
# ... etc for all six
```

- [ ] **Step 5: Verify and commit**

```bash
ls docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/
git add docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/
git commit -m "docs(autopep): Phase 6 acceptance screenshots from prod"
```

---

### Task 6.5: Multi-turn S5 walkthrough screenshots

**Track B · ~10 min**

- [ ] **Step 1: Continue the same workspace**

- [ ] **Step 2: Send "What was the top candidate's solubility score?"**

Wait for response. Capture **`07-followup-solubility.png`** showing the assistant's response with a concrete numeric score (verifying it remembered the candidate from turn 1).

- [ ] **Step 3: Send "Now show me what residues 40-60 look like in the fold for that candidate."**

Wait for response. Likely the agent uses Shell + BioPython (`python -c "from Bio.PDB ..."`) — capture **`08-shell-residues.png`** showing the sandbox-command card in the chat with the BioPython output.

- [ ] **Step 4: Commit screenshots**

```bash
git add docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/
git commit -m "docs(autopep): multi-turn coherence walkthrough screenshots"
```

---

### Task 6.6: Multi-workspace switch verification

**Track C · ~10 min**

- [ ] **Step 1: Open a second workspace (workspace B)**

Click the "+ New workspace" button.

- [ ] **Step 2: Send a literature prompt**

"Find literature about EGFR small-molecule inhibitor preprints from the last year."

Wait for response.

- [ ] **Step 3: Switch back to workspace A**

Verify the previous binder-design conversation is fully visible (user messages, assistant messages, tool-call cards, files panel populated, candidates table populated).

Capture **`09-workspace-switch-back.png`** showing workspace A with the prior conversation intact.

- [ ] **Step 4: Send the recall prompt in workspace A**

"Remind me which PDB ID we used for the target."

Verify the agent responds with the correct PDB ID (one of `6LU7`, `6Y2E`, `6Y84` — whichever it picked in the original run).

Capture **`10-pdb-recall.png`**.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/
git commit -m "docs(autopep): multi-workspace switch verification screenshots"
```

---

### Task 6.7: Phase 6 gate — final acceptance

**Sync point · ~10 min**

- [ ] **Step 1: All Playwright tests green against prod**

```bash
cd autopep && \
AUTOPEP_E2E_BASE_URL=<prod URL> \
AUTOPEP_E2E_TEST_EMAIL=<test> \
AUTOPEP_E2E_TEST_PASSWORD=<test> \
bun run e2e
```

Expected: green for all tests in `tests/e2e/`.

- [ ] **Step 2: All 10 screenshots committed and visible in the PR diff**

```bash
ls docs/superpowers/specs/screenshots/2026-04-30-autopep-agent-pipeline/ | wc -l
```

Expected: ≥10 files.

- [ ] **Step 3: Open the final PR**

Title: `feat(autopep): phase 6 — UI acceptance + Playwright e2e`.
Description includes:
- Link to Playwright report (or a relevant subset).
- Inline preview of the 10 screenshots.
- Note that all six previous phases' gates are also green (cross-link the PRs).

- [ ] **Step 4: Merge.**

- [ ] **Step 5: Phase 6 done. The full demo works end-to-end on prod.**

---

## Plan completion checklist

Before declaring the plan executed, verify:

- [ ] All 7 phases (0 through 6) merged to main.
- [ ] All gate scenarios green on the deployed Neon + Modal + Vercel stack.
- [ ] `deploy-and-validate.sh <N>` green output pasted into each phase's PR description.
- [ ] `grep -nE 'messagesTable|from "@/server/db/schema".*\bmessages\b' autopep/src` returns 0 results.
- [ ] `/api/agent/messages` returns 404 on prod.
- [ ] `Capabilities.default()` is the agent's capabilities base, plus `Skills(from_=LocalDir(...))` for life-science-research.
- [ ] R2Mount is the artifact transport (no manual `_download_attachments_to_inputs`).
- [ ] 6 tools wired: `literature_search`, `pdb_search`, `pdb_fetch`, `proteina_design`, `chai_fold_complex`, `score_candidates`.
- [ ] `PostgresSession` is the SDK Session backend; `_flush_assistant_message` is deleted.
- [ ] Proteina returns 5 candidates per call.
- [ ] Chai folds in parallel via `asyncio.gather`.
- [ ] `score_candidates` fans out across interaction + quality endpoints in parallel.
- [ ] Final assistant messages name a top candidate, list scores by scorer, cite ≥2 DOIs.
- [ ] Playwright e2e green against prod.
- [ ] 10 screenshots committed.

---
