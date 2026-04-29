# Autopep Agent Runtime MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Autopep MVP runtime and product shell for one complete 3CL-protease binder loop: research, PDB target preparation, Proteina candidate generation, Chai folding, interaction scoring, and ranked UI display.

**Architecture:** Keep Next.js/Vercel as the authenticated UI and short-lived run launcher. Replace the Codex harness path with a Python OpenAI Agents SDK worker on Modal that uses SDK streaming, Modal sandbox support, durable Neon state, and R2 artifacts. The frontend renders the event ledger and artifact/candidate tables through tRPC polling; no browser code receives Modal/OpenAI/R2 secrets.

**Tech Stack:** Next.js 16, React 19, tRPC 11, Drizzle/Postgres, Better Auth, Cloudflare R2 through S3 APIs, Mol*, Bun, Vitest, Python 3.12, OpenAI Agents SDK with `openai-agents[modal]`, Modal, FastAPI, httpx, psycopg, pytest.

---

## Scope Check

The design spec spans runtime, biology tools, workspace UX, recipes, and Mol* selection. This plan keeps them in one MVP because the acceptance test is a single user workflow that crosses all of those boundaries. The tree/BFS discovery sequence is intentionally excluded from execution here; the schema preserves lineage fields so Phase 2 can branch without another destructive data-model change.

## File Structure

- Modify `autopep/package.json`: add Python worker helper scripts and keep the existing Bun checks.
- Modify `autopep/drizzle.config.ts`: keep Better Auth tables and include every `autopep_*` table.
- Modify `autopep/src/env.js`: keep existing endpoint env vars and verify `AUTOPEP_RUNNER_BACKEND`, `AUTOPEP_MODAL_START_URL`, `AUTOPEP_MODAL_WEBHOOK_SECRET`, and `OPENAI_DEFAULT_MODEL`.
- Replace Autopep-specific parts of `autopep/src/server/db/schema.ts`: destructive schema for workspaces, threads, messages, runs, events, artifacts, candidates, model inferences, candidate scores, context references, recipes, recipe versions, and run recipes. Keep Better Auth tables unchanged.
- Modify `autopep/src/server/agent/contracts.ts`: shared Zod contracts for run status, events, artifacts, candidates, scores, messages, recipes, and endpoint payloads.
- Create `autopep/src/server/agent/contracts.test.ts`: contract acceptance tests.
- Create `autopep/src/server/workspaces/repository.ts`: typed helpers for creating/listing workspaces, threads, messages, runs, and event cursors.
- Create `autopep/src/server/workspaces/repository.test.ts`: mock-DB tests for repository behavior.
- Modify `autopep/src/server/agent/events.ts`: append-only event helper using the new `summary`, `displayJson`, and `rawJson` columns.
- Modify `autopep/src/server/agent/modal-launcher.ts`: launch Modal with `workspaceId`, `threadId`, and `runId`.
- Modify `autopep/src/server/agent/run-launcher.ts`: mark launch failures with the new run statuses.
- Modify `autopep/src/server/api/routers/workspace.ts`: workspace CRUD, message send, run creation, cursor event polling, artifact URLs, context references, and recipes.
- Create `autopep/src/server/api/routers/workspace.test.ts`: router/service tests with mocked DB and launchers.
- Modify `autopep/src/server/api/root.ts`: keep registering `workspace`.
- Modify `autopep/src/server/artifacts/r2.ts`: add object read helpers and keep signed/public URL behavior.
- Create `autopep/src/server/artifacts/artifact-service.ts`: central metadata helpers for uploaded objects and signed URLs.
- Create `autopep/src/server/artifacts/artifact-service.test.ts`: key, metadata, and read URL tests.
- Replace `autopep/modal/autopep_worker.py`: FastAPI launcher for the new Python worker.
- Create `autopep/modal/requirements.txt`: Modal image dependencies.
- Create `autopep/modal/requirements-dev.txt`: local worker test dependencies.
- Create `autopep/modal/autopep_agent/__init__.py`: Python package marker.
- Create `autopep/modal/autopep_agent/config.py`: env parsing.
- Create `autopep/modal/autopep_agent/db.py`: Neon access and row helpers.
- Create `autopep/modal/autopep_agent/events.py`: durable event writer.
- Create `autopep/modal/autopep_agent/artifacts.py`: R2 upload/download helpers.
- Create `autopep/modal/autopep_agent/endpoint_clients.py`: Proteina, Chai, and interaction scoring clients.
- Create `autopep/modal/autopep_agent/structure_utils.py`: PDB/CIF/FASTA helpers and sequence extraction.
- Create `autopep/modal/autopep_agent/research_tools.py`: RCSB, PubMed, and bioRxiv tools.
- Create `autopep/modal/autopep_agent/biology_tools.py`: Autopep function tools for prepare, inspect, mutate, generate, fold, and score.
- Create `autopep/modal/autopep_agent/streaming.py`: Agents SDK stream-event normalization.
- Create `autopep/modal/autopep_agent/runner.py`: top-level SDK agent, `SandboxAgent`, Modal sandbox config, run claim/execute/finalize flow.
- Create `autopep/modal/tests/*.py`: Python tests for endpoint clients, event normalization, workflow orchestration, and structure utilities.
- Replace `autopep/src/app/_components/workspace-shell.tsx`: smaller shell that composes focused components.
- Modify `autopep/src/app/_components/autopep-workspace.tsx`: map workspace payloads, context refs, recipes, events, artifacts, candidates, and scores.
- Modify `autopep/src/app/_components/molstar-viewer.tsx`: larger viewer surface, compact controls, and selection callback.
- Create `autopep/src/app/_components/chat-panel.tsx`: unified chat/progress panel.
- Create `autopep/src/app/_components/trace-event-card.tsx`: collapsible event/tool/artifact/score cards.
- Create `autopep/src/app/_components/molstar-stage.tsx`: center viewer stage and actions.
- Create `autopep/src/app/_components/journey-panel.tsx`: compact milestones and candidate tree.
- Create `autopep/src/app/_components/workspace-rail.tsx`: workspace navigation and CRUD affordances.
- Create `autopep/src/app/_components/recipe-manager.tsx`: recipe list/create/edit/enable controls.
- Create component tests next to each new component using React Testing Library.

## Task 1: Shared Runtime Contracts

**Files:**
- Modify: `autopep/src/server/agent/contracts.ts`
- Create: `autopep/src/server/agent/contracts.test.ts`

- [ ] **Step 1: Write the failing contract tests**

```ts
import { describe, expect, it } from "vitest";

import {
	agentEventTypeSchema,
	artifactKindSchema,
	candidateScoreSchema,
	endpointModelNameSchema,
	runStatusSchema,
	scoreLabelSchema,
} from "./contracts";

describe("Autopep runtime contracts", () => {
	it("accepts the run statuses used by the MVP event ledger", () => {
		expect(runStatusSchema.options).toEqual([
			"queued",
			"running",
			"paused",
			"completed",
			"failed",
			"cancelled",
		]);
	});

	it("accepts event types for chat, tools, sandbox output, candidates, and scores", () => {
		for (const type of [
			"assistant_token_delta",
			"tool_call_started",
			"sandbox_stdout_delta",
			"artifact_created",
			"candidate_ranked",
			"run_completed",
		]) {
			expect(agentEventTypeSchema.parse(type)).toBe(type);
		}
	});

	it("accepts model inference names for all deployed Modal endpoints", () => {
		expect(endpointModelNameSchema.parse("proteina_complexa")).toBe(
			"proteina_complexa",
		);
		expect(endpointModelNameSchema.parse("chai_1")).toBe("chai_1");
		expect(endpointModelNameSchema.parse("protein_interaction_scoring")).toBe(
			"protein_interaction_scoring",
		);
	});

	it("validates candidate score rows for D-SCRIPT, PRODIGY, and aggregate labels", () => {
		expect(
			candidateScoreSchema.parse({
				candidateId: "11111111-1111-4111-8111-111111111111",
				label: "possible_binder",
				scorer: "protein_interaction_aggregate",
				status: "ok",
				unit: null,
				value: null,
				values: { notes: ["D-SCRIPT-only result"] },
			}),
		).toMatchObject({
			label: "possible_binder",
			scorer: "protein_interaction_aggregate",
		});
		expect(scoreLabelSchema.parse("insufficient_data")).toBe("insufficient_data");
	});

	it("keeps structure artifacts broad enough for source, generated, folded, and scored outputs", () => {
		for (const kind of ["mmcif", "pdb", "proteina_result", "chai_result", "score_report"]) {
			expect(artifactKindSchema.parse(kind)).toBe(kind);
		}
	});
});
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd autopep
bunx vitest run src/server/agent/contracts.test.ts
```

Expected: FAIL because the new schemas and event/model values are missing.

- [ ] **Step 3: Replace the contract module**

Replace `autopep/src/server/agent/contracts.ts` with:

```ts
import { z } from "zod";

export const runStatusSchema = z.enum([
	"queued",
	"running",
	"paused",
	"completed",
	"failed",
	"cancelled",
]);

export const taskKindSchema = z.enum([
	"chat",
	"research",
	"structure_search",
	"prepare_structure",
	"mutate_structure",
	"branch_design",
]);

export const agentEventTypeSchema = z.enum([
	"run_started",
	"assistant_message_started",
	"assistant_token_delta",
	"assistant_message_completed",
	"reasoning_step",
	"tool_call_started",
	"tool_call_delta",
	"tool_call_completed",
	"tool_call_failed",
	"sandbox_command_started",
	"sandbox_stdout_delta",
	"sandbox_stderr_delta",
	"sandbox_command_completed",
	"artifact_created",
	"candidate_ranked",
	"approval_requested",
	"agent_changed",
	"run_paused",
	"run_failed",
	"run_cancelled",
	"run_completed",
]);

export const artifactKindSchema = z.enum([
	"cif",
	"mmcif",
	"pdb",
	"fasta",
	"sequence",
	"pdb_metadata",
	"literature_snapshot",
	"biopython_script",
	"proteina_result",
	"chai_result",
	"mutated_structure",
	"score_report",
	"log",
	"image",
	"other",
]);

export const endpointModelNameSchema = z.enum([
	"proteina_complexa",
	"chai_1",
	"protein_interaction_scoring",
	"future_scorer",
]);

export const scoreLabelSchema = z.enum([
	"likely_binder",
	"possible_binder",
	"unlikely_binder",
	"insufficient_data",
]);

export const scoreStatusSchema = z.enum([
	"ok",
	"partial",
	"failed",
	"unavailable",
]);

export const scoreScorerSchema = z.enum([
	"dscript",
	"prodigy",
	"protein_interaction_aggregate",
	"future_scorer",
]);

export const contextReferenceSchema = z.object({
	artifactId: z.string().uuid().nullable(),
	candidateId: z.string().uuid().nullable(),
	kind: z.enum(["protein_selection", "artifact", "candidate", "literature", "note"]),
	label: z.string().min(1),
	selector: z.record(z.unknown()).default({}),
});

export const candidateScoreSchema = z.object({
	candidateId: z.string().uuid(),
	label: scoreLabelSchema.nullable(),
	scorer: scoreScorerSchema,
	status: scoreStatusSchema,
	unit: z.string().nullable(),
	value: z.number().nullable(),
	values: z.record(z.unknown()).default({}),
});

export type AgentEventType = z.infer<typeof agentEventTypeSchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type CandidateScore = z.infer<typeof candidateScoreSchema>;
export type ContextReference = z.infer<typeof contextReferenceSchema>;
export type EndpointModelName = z.infer<typeof endpointModelNameSchema>;
export type RunStatus = z.infer<typeof runStatusSchema>;
```

- [ ] **Step 4: Run the contract test**

Run:

```bash
cd autopep
bunx vitest run src/server/agent/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autopep/src/server/agent/contracts.ts autopep/src/server/agent/contracts.test.ts
git commit -m "feat: define autopep runtime contracts"
```

## Task 2: Destructive Autopep Schema

**Files:**
- Modify: `autopep/src/server/db/schema.ts`
- Modify: `autopep/drizzle.config.ts`
- Create generated migration: `autopep/drizzle/0003_*.sql`
- Test: `autopep/src/server/db/schema.test.ts`

- [ ] **Step 1: Write a schema smoke test**

```ts
import { getTableName } from "drizzle-orm";
import { describe, expect, it } from "vitest";

import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	contextReferences,
	messages,
	modelInferences,
	recipeVersions,
	recipes,
	runRecipes,
	threads,
	workspaces,
} from "./schema";

describe("Autopep schema", () => {
	it("uses the new workspace-centered table names", () => {
		expect(getTableName(workspaces)).toBe("autopep_workspace");
		expect(getTableName(threads)).toBe("autopep_thread");
		expect(getTableName(messages)).toBe("autopep_message");
		expect(getTableName(agentRuns)).toBe("autopep_agent_run");
		expect(getTableName(agentEvents)).toBe("autopep_agent_event");
		expect(getTableName(artifacts)).toBe("autopep_artifact");
		expect(getTableName(modelInferences)).toBe("autopep_model_inference");
		expect(getTableName(candidateScores)).toBe("autopep_candidate_score");
		expect(getTableName(contextReferences)).toBe("autopep_context_reference");
		expect(getTableName(recipes)).toBe("autopep_recipe");
		expect(getTableName(recipeVersions)).toBe("autopep_recipe_version");
		expect(getTableName(runRecipes)).toBe("autopep_run_recipe");
	});
});
```

- [ ] **Step 2: Run the failing schema test**

Run:

```bash
cd autopep
bunx vitest run src/server/db/schema.test.ts
```

Expected: FAIL because the current schema still uses `autopep_project` and older narrow tables.

- [ ] **Step 3: Replace Autopep enums and tables**

In `autopep/src/server/db/schema.ts`, keep `posts`, `user`, `session`, `account`, and `verification`. Replace the existing Autopep-specific enums/tables/relations beginning at `agentRunStatus` and ending at `artifactRelations` with definitions that follow this shape:

```ts
export const agentRunStatus = pgEnum("agent_run_status", [
	"queued",
	"running",
	"paused",
	"completed",
	"failed",
	"cancelled",
]);

export const agentTaskKind = pgEnum("agent_task_kind", [
	"chat",
	"research",
	"structure_search",
	"prepare_structure",
	"mutate_structure",
	"branch_design",
]);

export const artifactKind = pgEnum("artifact_kind", [
	"cif",
	"mmcif",
	"pdb",
	"fasta",
	"sequence",
	"pdb_metadata",
	"literature_snapshot",
	"biopython_script",
	"proteina_result",
	"chai_result",
	"mutated_structure",
	"score_report",
	"log",
	"image",
	"other",
]);

export const workspaces = createAutopepTable(
	"workspace",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		ownerId: text("owner_id").notNull().references(() => user.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		description: text("description"),
		activeThreadId: uuid("active_thread_id"),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().$onUpdate(() => new Date()).notNull(),
		archivedAt: timestamp("archived_at", { withTimezone: true }),
	},
	(t) => [index("autopep_workspace_owner_idx").on(t.ownerId)],
);

export const threads = createAutopepTable(
	"thread",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		title: text("title").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().$onUpdate(() => new Date()).notNull(),
	},
	(t) => [index("autopep_thread_workspace_idx").on(t.workspaceId)],
);

export const messages = createAutopepTable(
	"message",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		threadId: uuid("thread_id").notNull().references(() => threads.id, { onDelete: "cascade" }),
		runId: uuid("run_id"),
		role: text("role", { enum: ["user", "assistant", "system"] }).notNull(),
		content: text("content").notNull(),
		contextRefsJson: jsonb("context_refs_json").$type<string[]>().default(sql`'[]'::jsonb`).notNull(),
		recipeRefsJson: jsonb("recipe_refs_json").$type<string[]>().default(sql`'[]'::jsonb`).notNull(),
		attachmentRefsJson: jsonb("attachment_refs_json").$type<string[]>().default(sql`'[]'::jsonb`).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [index("autopep_message_thread_idx").on(t.threadId)],
);

export const agentRuns = createAutopepTable(
	"agent_run",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		threadId: uuid("thread_id").notNull().references(() => threads.id, { onDelete: "cascade" }),
		parentRunId: uuid("parent_run_id"),
		rootRunId: uuid("root_run_id"),
		createdById: text("created_by_id").notNull().references(() => user.id, { onDelete: "cascade" }),
		status: agentRunStatus("status").default("queued").notNull(),
		taskKind: agentTaskKind("task_kind").default("chat").notNull(),
		prompt: text("prompt").notNull(),
		model: text("model").notNull().default("gpt-5.5"),
		agentName: text("agent_name").notNull().default("Autopep"),
		modalCallId: text("modal_call_id"),
		sandboxSessionStateJson: jsonb("sandbox_session_state_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		sdkStateJson: jsonb("sdk_state_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		lastResponseId: text("last_response_id"),
		startedAt: timestamp("started_at", { withTimezone: true }),
		finishedAt: timestamp("finished_at", { withTimezone: true }),
		errorSummary: text("error_summary"),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().$onUpdate(() => new Date()).notNull(),
	},
	(t) => [
		index("autopep_agent_run_workspace_idx").on(t.workspaceId),
		index("autopep_agent_run_thread_idx").on(t.threadId),
		index("autopep_agent_run_status_idx").on(t.status),
	],
);
```

Add the remaining MVP tables in the same Autopep section:

```ts
export const agentEvents = createAutopepTable(
	"agent_event",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
		sequence: integer("sequence").notNull(),
		type: text("type").notNull(),
		title: text("title").notNull(),
		summary: text("summary"),
		displayJson: jsonb("display_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		rawJson: jsonb("raw_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [
		index("autopep_agent_event_run_idx").on(t.runId),
		unique("autopep_agent_event_run_sequence_unique").on(t.runId, t.sequence),
	],
);

export const artifacts = createAutopepTable(
	"artifact",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id").references(() => agentRuns.id, { onDelete: "set null" }),
		sourceArtifactId: uuid("source_artifact_id"),
		kind: artifactKind("kind").notNull(),
		name: text("name").notNull(),
		storageProvider: text("storage_provider").notNull().default("r2"),
		storageKey: text("storage_key").notNull(),
		contentType: text("content_type").notNull(),
		sizeBytes: integer("size_bytes").notNull(),
		sha256: text("sha256"),
		metadataJson: jsonb("metadata_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [
		index("autopep_artifact_workspace_idx").on(t.workspaceId),
		index("autopep_artifact_run_idx").on(t.runId),
		index("autopep_artifact_source_idx").on(t.sourceArtifactId),
	],
);

export const proteinCandidates = createAutopepTable(
	"protein_candidate",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
		parentCandidateId: uuid("parent_candidate_id"),
		rank: integer("rank").notNull(),
		source: text("source", { enum: ["rcsb_pdb", "alphafold", "proteina_complexa", "chai_1", "generated", "uploaded", "mutated"] }).notNull(),
		structureId: text("structure_id"),
		chainIdsJson: jsonb("chain_ids_json").$type<string[]>().default(sql`'[]'::jsonb`).notNull(),
		sequence: text("sequence"),
		title: text("title").notNull(),
		scoreJson: jsonb("score_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		whySelected: text("why_selected"),
		artifactId: uuid("artifact_id").references(() => artifacts.id, { onDelete: "set null" }),
		foldArtifactId: uuid("fold_artifact_id").references(() => artifacts.id, { onDelete: "set null" }),
		parentInferenceId: uuid("parent_inference_id"),
		metadataJson: jsonb("metadata_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [
		index("autopep_candidate_workspace_idx").on(t.workspaceId),
		index("autopep_candidate_run_idx").on(t.runId),
		index("autopep_candidate_parent_idx").on(t.parentCandidateId),
	],
);

export const modelInferences = createAutopepTable(
	"model_inference",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
		parentInferenceId: uuid("parent_inference_id"),
		provider: text("provider").notNull().default("modal"),
		modelName: text("model_name", { enum: ["proteina_complexa", "chai_1", "protein_interaction_scoring", "future_scorer"] }).notNull(),
		status: agentRunStatus("status").default("queued").notNull(),
		endpointUrlSnapshot: text("endpoint_url_snapshot"),
		requestJson: jsonb("request_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		responseJson: jsonb("response_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		externalRequestId: text("external_request_id"),
		startedAt: timestamp("started_at", { withTimezone: true }),
		finishedAt: timestamp("finished_at", { withTimezone: true }),
		errorSummary: text("error_summary"),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [
		index("autopep_model_inference_workspace_idx").on(t.workspaceId),
		index("autopep_model_inference_run_idx").on(t.runId),
	],
);

export const candidateScores = createAutopepTable(
	"candidate_score",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
		candidateId: uuid("candidate_id").notNull().references(() => proteinCandidates.id, { onDelete: "cascade" }),
		modelInferenceId: uuid("model_inference_id").references(() => modelInferences.id, { onDelete: "set null" }),
		scorer: text("scorer", { enum: ["dscript", "prodigy", "protein_interaction_aggregate", "future_scorer"] }).notNull(),
		status: text("status", { enum: ["ok", "partial", "failed", "unavailable"] }).notNull(),
		label: text("label"),
		value: real("value"),
		unit: text("unit"),
		valuesJson: jsonb("values_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		warningsJson: jsonb("warnings_json").$type<unknown[]>().default(sql`'[]'::jsonb`).notNull(),
		errorsJson: jsonb("errors_json").$type<unknown[]>().default(sql`'[]'::jsonb`).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [
		index("autopep_candidate_score_candidate_idx").on(t.candidateId),
		index("autopep_candidate_score_run_idx").on(t.runId),
	],
);

export const contextReferences = createAutopepTable(
	"context_reference",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id").notNull().references(() => workspaces.id, { onDelete: "cascade" }),
		artifactId: uuid("artifact_id").references(() => artifacts.id, { onDelete: "set null" }),
		candidateId: uuid("candidate_id").references(() => proteinCandidates.id, { onDelete: "set null" }),
		kind: text("kind", { enum: ["protein_selection", "artifact", "candidate", "literature", "note"] }).notNull(),
		label: text("label").notNull(),
		selectorJson: jsonb("selector_json").$type<Record<string, unknown>>().default(sql`'{}'::jsonb`).notNull(),
		createdById: text("created_by_id").notNull().references(() => user.id, { onDelete: "cascade" }),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [index("autopep_context_reference_workspace_idx").on(t.workspaceId)],
);

export const recipes = createAutopepTable(
	"recipe",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		ownerId: text("owner_id").notNull().references(() => user.id, { onDelete: "cascade" }),
		workspaceId: uuid("workspace_id").references(() => workspaces.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		description: text("description"),
		bodyMarkdown: text("body_markdown").notNull(),
		isGlobal: boolean("is_global").default(false).notNull(),
		enabledByDefault: boolean("enabled_by_default").default(false).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().$onUpdate(() => new Date()).notNull(),
		archivedAt: timestamp("archived_at", { withTimezone: true }),
	},
	(t) => [index("autopep_recipe_workspace_idx").on(t.workspaceId)],
);

export const recipeVersions = createAutopepTable(
	"recipe_version",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		recipeId: uuid("recipe_id").notNull().references(() => recipes.id, { onDelete: "cascade" }),
		version: integer("version").notNull(),
		bodyMarkdown: text("body_markdown").notNull(),
		createdById: text("created_by_id").notNull().references(() => user.id, { onDelete: "cascade" }),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [unique("autopep_recipe_version_unique").on(t.recipeId, t.version)],
);

export const runRecipes = createAutopepTable(
	"run_recipe",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
		recipeId: uuid("recipe_id").notNull().references(() => recipes.id, { onDelete: "cascade" }),
		recipeVersionId: uuid("recipe_version_id").notNull().references(() => recipeVersions.id, { onDelete: "cascade" }),
		nameSnapshot: text("name_snapshot").notNull(),
		bodySnapshot: text("body_snapshot").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true }).defaultNow().notNull(),
	},
	(t) => [index("autopep_run_recipe_run_idx").on(t.runId)],
);
```

- [ ] **Step 4: Add relations**

Use relations with these names so router code can query predictably:

```ts
export const workspaceRelations = relations(workspaces, ({ one, many }) => ({
	owner: one(user, { fields: [workspaces.ownerId], references: [user.id] }),
	threads: many(threads),
	runs: many(agentRuns),
	artifacts: many(artifacts),
	recipes: many(recipes),
}));

export const threadRelations = relations(threads, ({ one, many }) => ({
	workspace: one(workspaces, { fields: [threads.workspaceId], references: [workspaces.id] }),
	messages: many(messages),
	runs: many(agentRuns),
}));

export const agentRunRelations = relations(agentRuns, ({ one, many }) => ({
	workspace: one(workspaces, { fields: [agentRuns.workspaceId], references: [workspaces.id] }),
	thread: one(threads, { fields: [agentRuns.threadId], references: [threads.id] }),
	createdBy: one(user, { fields: [agentRuns.createdById], references: [user.id] }),
	events: many(agentEvents),
	artifacts: many(artifacts),
	candidates: many(proteinCandidates),
	modelInferences: many(modelInferences),
}));
```

- [ ] **Step 5: Generate the destructive migration**

Run:

```bash
cd autopep
bun run db:generate
```

Expected: a new SQL migration under `autopep/drizzle/` that drops/recreates Autopep-specific tables/enums and leaves Better Auth tables intact.

- [ ] **Step 6: Run tests and typecheck**

Run:

```bash
cd autopep
bunx vitest run src/server/db/schema.test.ts
bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/server/db/schema.ts autopep/src/server/db/schema.test.ts autopep/drizzle autopep/drizzle.config.ts
git commit -m "feat: replace autopep schema with workspace runtime model"
```

## Task 3: Workspace Repository And Event Ledger

**Files:**
- Create: `autopep/src/server/workspaces/repository.ts`
- Create: `autopep/src/server/workspaces/repository.test.ts`
- Modify: `autopep/src/server/agent/events.ts`

- [ ] **Step 1: Write repository tests**

```ts
import { describe, expect, it, vi } from "vitest";

import { appendRunEvent, deriveNextSequence } from "@/server/agent/events";

describe("deriveNextSequence", () => {
	it("starts at 1 when no events exist", () => {
		expect(deriveNextSequence(undefined)).toBe(1);
	});

	it("increments the latest sequence", () => {
		expect(deriveNextSequence(41)).toBe(42);
	});
});

describe("appendRunEvent", () => {
	it("stores compact display JSON and raw JSON separately", async () => {
		const returning = vi.fn().mockResolvedValue([
			{
				id: "event-1",
				sequence: 1,
				type: "tool_call_started",
			},
		]);
		const onConflictDoNothing = vi.fn(() => ({ returning }));
		const values = vi.fn(() => ({ onConflictDoNothing }));
		const insert = vi.fn(() => ({ values }));
		const db = {
			insert,
			select: vi.fn(() => ({
				from: () => ({
					where: () => ({
						orderBy: () => ({
							limit: () => Promise.resolve([]),
						}),
					}),
				}),
			})),
		};

		await appendRunEvent({
			db: db as never,
			display: { toolName: "search_structures" },
			raw: { provider: "agents-sdk", item: { name: "tool_called" } },
			runId: "11111111-1111-4111-8111-111111111111",
			summary: "Searching RCSB",
			title: "Search structures",
			type: "tool_call_started",
		});

		expect(values).toHaveBeenCalledWith(
			expect.objectContaining({
				displayJson: { toolName: "search_structures" },
				rawJson: { provider: "agents-sdk", item: { name: "tool_called" } },
				sequence: 1,
				summary: "Searching RCSB",
			}),
		);
	});
});
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd autopep
bunx vitest run src/server/workspaces/repository.test.ts src/server/agent/events.test.ts
```

Expected: FAIL until the new helper signatures exist.

- [ ] **Step 3: Update the event helper**

Use this implementation pattern in `autopep/src/server/agent/events.ts`:

```ts
import { desc, eq } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import { agentEvents } from "@/server/db/schema";
import type { AgentEventType } from "./contracts";

type AppendRunEventInput = {
	db: typeof appDb;
	runId: string;
	type: AgentEventType;
	title: string;
	summary?: string | null;
	display?: Record<string, unknown>;
	raw?: Record<string, unknown>;
};

export const deriveNextSequence = (latestSequence: number | undefined) =>
	(latestSequence ?? 0) + 1;

export const appendRunEvent = async ({
	db,
	runId,
	type,
	title,
	summary = null,
	display = {},
	raw = {},
}: AppendRunEventInput) => {
	for (let attempt = 0; attempt < 5; attempt += 1) {
		const [latestEvent] = await db
			.select({ sequence: agentEvents.sequence })
			.from(agentEvents)
			.where(eq(agentEvents.runId, runId))
			.orderBy(desc(agentEvents.sequence))
			.limit(1);

		const [event] = await db
			.insert(agentEvents)
			.values({
				displayJson: display,
				rawJson: raw,
				runId,
				sequence: deriveNextSequence(latestEvent?.sequence),
				summary,
				title,
				type,
			})
			.onConflictDoNothing({
				target: [agentEvents.runId, agentEvents.sequence],
			})
			.returning();

		if (event) return event;
	}

	throw new Error("Failed to append run event after sequence retries.");
};
```

- [ ] **Step 4: Create workspace repository functions**

Create `autopep/src/server/workspaces/repository.ts` with exported helpers:

```ts
import { and, asc, desc, eq, gt, isNull } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	contextReferences,
	messages,
	proteinCandidates,
	recipeVersions,
	recipes,
	runRecipes,
	threads,
	workspaces,
} from "@/server/db/schema";

type Db = typeof appDb;

export const listWorkspacesForOwner = (db: Db, ownerId: string) =>
	db.query.workspaces.findMany({
		where: and(eq(workspaces.ownerId, ownerId), isNull(workspaces.archivedAt)),
		orderBy: [desc(workspaces.updatedAt)],
	});

export const createWorkspaceWithThread = async ({
	db,
	description = null,
	name,
	ownerId,
}: {
	db: Db;
	description?: string | null;
	name: string;
	ownerId: string;
}) => {
	const [workspace] = await db.insert(workspaces).values({ description, name, ownerId }).returning();
	if (!workspace) throw new Error("Failed to create workspace.");

	const [thread] = await db
		.insert(threads)
		.values({ title: "Main thread", workspaceId: workspace.id })
		.returning();
	if (!thread) throw new Error("Failed to create thread.");

	const [updatedWorkspace] = await db
		.update(workspaces)
		.set({ activeThreadId: thread.id })
		.where(eq(workspaces.id, workspace.id))
		.returning();
	return { thread, workspace: updatedWorkspace ?? workspace };
};

export const getWorkspacePayload = async ({
	db,
	ownerId,
	workspaceId,
}: {
	db: Db;
	ownerId: string;
	workspaceId: string;
}) => {
	const workspace = await db.query.workspaces.findFirst({
		where: and(eq(workspaces.id, workspaceId), eq(workspaces.ownerId, ownerId)),
	});
	if (!workspace) return null;

	const threadRows = await db.query.threads.findMany({
		where: eq(threads.workspaceId, workspace.id),
		orderBy: [desc(threads.updatedAt)],
	});
	const activeThread = threadRows.find((thread) => thread.id === workspace.activeThreadId) ?? threadRows[0] ?? null;
	const runRows = await db.query.agentRuns.findMany({
		where: eq(agentRuns.workspaceId, workspace.id),
		orderBy: [desc(agentRuns.createdAt)],
		limit: 20,
	});
	const activeRun = runRows[0] ?? null;

	const [messageRows, eventRows, artifactRows, candidateRows, scoreRows, recipeRows, contextRows] =
		await Promise.all([
			activeThread
				? db.query.messages.findMany({ where: eq(messages.threadId, activeThread.id), orderBy: [asc(messages.createdAt)] })
				: Promise.resolve([]),
			activeRun
				? db.query.agentEvents.findMany({ where: eq(agentEvents.runId, activeRun.id), orderBy: [asc(agentEvents.sequence)] })
				: Promise.resolve([]),
			db.query.artifacts.findMany({ where: eq(artifacts.workspaceId, workspace.id), orderBy: [desc(artifacts.createdAt)] }),
			db.query.proteinCandidates.findMany({ where: eq(proteinCandidates.workspaceId, workspace.id), orderBy: [asc(proteinCandidates.rank)] }),
			activeRun
				? db.query.candidateScores.findMany({ where: eq(candidateScores.runId, activeRun.id), orderBy: [asc(candidateScores.createdAt)] })
				: Promise.resolve([]),
			db.query.recipes.findMany({ where: eq(recipes.workspaceId, workspace.id), orderBy: [asc(recipes.name)] }),
			db.query.contextReferences.findMany({ where: eq(contextReferences.workspaceId, workspace.id), orderBy: [desc(contextReferences.createdAt)] }),
		]);

	return {
		activeRun,
		activeThread,
		artifacts: artifactRows,
		candidateScores: scoreRows,
		candidates: candidateRows,
		contextReferences: contextRows,
		events: eventRows,
		messages: messageRows,
		recipes: recipeRows,
		runs: runRows,
		threads: threadRows,
		workspace,
	};
};

export const getRunEventsAfter = ({ afterSequence, db, runId }: { afterSequence: number; db: Db; runId: string }) =>
	db.query.agentEvents.findMany({
		where: and(eq(agentEvents.runId, runId), gt(agentEvents.sequence, afterSequence)),
		orderBy: [asc(agentEvents.sequence)],
	});
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd autopep
bunx vitest run src/server/workspaces/repository.test.ts src/server/agent/events.test.ts
bun run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/src/server/workspaces/repository.ts autopep/src/server/workspaces/repository.test.ts autopep/src/server/agent/events.ts
git commit -m "feat: add workspace repository and event ledger"
```

## Task 4: Workspace tRPC API And Modal Launch Contract

**Files:**
- Modify: `autopep/src/server/api/routers/workspace.ts`
- Modify: `autopep/src/server/agent/modal-launcher.ts`
- Modify: `autopep/src/server/agent/run-launcher.ts`
- Modify: `autopep/src/server/agent/project-run-creator.ts`
- Modify tests under `autopep/src/server/agent/*.test.ts`

- [ ] **Step 1: Write launcher contract tests**

Update `autopep/src/server/agent/modal-launcher.test.ts` so the payload includes the new identifiers:

```ts
it("sends workspace, thread, and run identifiers to Modal with bearer auth", async () => {
	const fetchImpl = vi.fn().mockResolvedValue(
		new Response(JSON.stringify({ accepted: true, functionCallId: "fc-1" }), {
			headers: { "content-type": "application/json" },
			status: 202,
		}),
	);
	const { startModalRun } = await importModalLauncher();

	await startModalRun({
		fetchImpl,
		runId: "11111111-1111-4111-8111-111111111111",
		threadId: "33333333-3333-4333-8333-333333333333",
		workspaceId: "22222222-2222-4222-8222-222222222222",
	});

	expect(fetchImpl).toHaveBeenCalledWith(
		"https://autopep--start-run.modal.run",
		expect.objectContaining({
			body: JSON.stringify({
				runId: "11111111-1111-4111-8111-111111111111",
				threadId: "33333333-3333-4333-8333-333333333333",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
			headers: expect.objectContaining({
				authorization: "Bearer secret-token",
				"content-type": "application/json",
			}),
			method: "POST",
		}),
	);
});
```

- [ ] **Step 2: Run failing launcher tests**

Run:

```bash
cd autopep
bunx vitest run src/server/agent/modal-launcher.test.ts src/server/agent/run-launcher.test.ts
```

Expected: FAIL because the launcher still sends `projectId`.

- [ ] **Step 3: Update `startModalRun`**

```ts
type StartModalRunInput = {
	fetchImpl?: typeof fetch;
	runId: string;
	threadId: string;
	workspaceId: string;
};

export const startModalRun = async ({
	fetchImpl = fetch,
	runId,
	threadId,
	workspaceId,
}: StartModalRunInput) => {
	if (!env.AUTOPEP_MODAL_START_URL) {
		throw new Error("AUTOPEP_MODAL_START_URL is required when AUTOPEP_RUNNER_BACKEND=modal.");
	}
	if (!env.AUTOPEP_MODAL_WEBHOOK_SECRET) {
		throw new Error("AUTOPEP_MODAL_WEBHOOK_SECRET is required when AUTOPEP_RUNNER_BACKEND=modal.");
	}

	const response = await fetchImpl(env.AUTOPEP_MODAL_START_URL, {
		body: JSON.stringify({ runId, threadId, workspaceId }),
		headers: {
			authorization: `Bearer ${env.AUTOPEP_MODAL_WEBHOOK_SECRET}`,
			"content-type": "application/json",
		},
		method: "POST",
	});

	if (!response.ok) {
		const body = await response.text().catch(() => "");
		throw new Error(`Modal launcher failed with ${response.status} ${response.statusText}: ${body || "(empty response)"}`);
	}

	const contentType = response.headers.get("content-type") ?? "";
	return contentType.includes("application/json") ? response.json() : null;
};
```

- [ ] **Step 4: Replace project run creation with message/run creation**

Create a service function in `project-run-creator.ts` or rename the file to `run-creator.ts`. The function must:

```ts
export const createMessageRunWithLaunch = async ({
	db,
	input,
	launchRun = launchCreatedRun,
	ownerId,
}: CreateMessageRunWithLaunchInput) => {
	const workspaceBundle = input.workspaceId
		? await ensureOwnedWorkspace({ db, ownerId, workspaceId: input.workspaceId })
		: await createWorkspaceWithThread({
				db,
				name: input.name ?? inferWorkspaceName(input.prompt),
				ownerId,
			});

	const [message] = await db
		.insert(messages)
		.values({
			attachmentRefsJson: input.attachmentRefs ?? [],
			contextRefsJson: input.contextRefs ?? [],
			recipeRefsJson: input.recipeRefs ?? [],
			content: input.prompt,
			role: "user",
			threadId: workspaceBundle.thread.id,
		})
		.returning();
	if (!message) throw new Error("Failed to create user message.");

	const [run] = await db
		.insert(agentRuns)
		.values({
			createdById: ownerId,
			prompt: input.prompt,
			rootRunId: null,
			status: "queued",
			taskKind: input.taskKind ?? "chat",
			threadId: workspaceBundle.thread.id,
			workspaceId: workspaceBundle.workspace.id,
		})
		.returning();
	if (!run) throw new Error("Failed to create agent run.");

	const [linkedMessage] = await db
		.update(messages)
		.set({ runId: run.id })
		.where(eq(messages.id, message.id))
		.returning();

	const launch = await launchRun({
		db,
		runId: run.id,
		threadId: workspaceBundle.thread.id,
		workspaceId: workspaceBundle.workspace.id,
	});

	return {
		message: linkedMessage ?? message,
		run: launch.run ?? run,
		thread: workspaceBundle.thread,
		workspace: workspaceBundle.workspace,
	};
};
```

- [ ] **Step 5: Replace workspace router procedures**

Use this `workspaceRouter` shape:

```ts
const workspaceIdInput = z.object({ workspaceId: z.string().uuid() });

export const workspaceRouter = createTRPCRouter({
	listWorkspaces: protectedProcedure.query(async ({ ctx }) =>
		listWorkspacesForOwner(ctx.db, ctx.session.user.id),
	),

	createWorkspace: protectedProcedure
		.input(z.object({
			description: z.string().max(1000).nullable().optional(),
			name: z.string().min(1).max(120),
		}))
		.mutation(async ({ ctx, input }) =>
			createWorkspaceWithThread({
				db: ctx.db,
				description: input.description ?? null,
				name: input.name,
				ownerId: ctx.session.user.id,
			}),
		),

	renameWorkspace: protectedProcedure
		.input(workspaceIdInput.extend({ name: z.string().min(1).max(120) }))
		.mutation(async ({ ctx, input }) => {
			const [workspace] = await ctx.db
				.update(workspaces)
				.set({ name: input.name })
				.where(and(eq(workspaces.id, input.workspaceId), eq(workspaces.ownerId, ctx.session.user.id)))
				.returning();
			if (!workspace) throw new TRPCError({ code: "NOT_FOUND", message: "Workspace not found." });
			return workspace;
		}),

	archiveWorkspace: protectedProcedure.input(workspaceIdInput).mutation(async ({ ctx, input }) => {
		const [workspace] = await ctx.db
			.update(workspaces)
			.set({ archivedAt: new Date() })
			.where(and(eq(workspaces.id, input.workspaceId), eq(workspaces.ownerId, ctx.session.user.id)))
			.returning();
		if (!workspace) throw new TRPCError({ code: "NOT_FOUND", message: "Workspace not found." });
		return workspace;
	}),

	getWorkspace: protectedProcedure.input(workspaceIdInput).query(async ({ ctx, input }) =>
		getWorkspacePayload({ db: ctx.db, ownerId: ctx.session.user.id, workspaceId: input.workspaceId }),
	),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const workspace = await ctx.db.query.workspaces.findFirst({
			where: and(eq(workspaces.ownerId, ctx.session.user.id), isNull(workspaces.archivedAt)),
			orderBy: [desc(workspaces.updatedAt)],
		});
		return workspace
			? getWorkspacePayload({ db: ctx.db, ownerId: ctx.session.user.id, workspaceId: workspace.id })
			: null;
	}),

	sendMessage: protectedProcedure
		.input(z.object({
			attachmentRefs: z.array(z.string().uuid()).default([]),
			contextRefs: z.array(z.string().uuid()).default([]),
			prompt: z.string().min(1).max(12000),
			recipeRefs: z.array(z.string().uuid()).default([]),
			taskKind: taskKindSchema.default("chat"),
			workspaceId: z.string().uuid().optional(),
		}))
		.mutation(async ({ ctx, input }) =>
			createMessageRunWithLaunch({ db: ctx.db, input, ownerId: ctx.session.user.id }),
		),

	getRunEvents: protectedProcedure
		.input(z.object({ afterSequence: z.number().int().min(0).default(0), runId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			const run = await ctx.db
				.select({ id: agentRuns.id })
				.from(agentRuns)
				.innerJoin(workspaces, eq(agentRuns.workspaceId, workspaces.id))
				.where(and(eq(agentRuns.id, input.runId), eq(workspaces.ownerId, ctx.session.user.id)))
				.limit(1);
			if (!run[0]) return [];
			return getRunEventsAfter({ afterSequence: input.afterSequence, db: ctx.db, runId: input.runId });
		}),
});
```

- [ ] **Step 6: Run API tests**

Run:

```bash
cd autopep
bunx vitest run src/server/agent/modal-launcher.test.ts src/server/agent/run-launcher.test.ts src/server/agent/project-run-creator.test.ts
bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/server/api/routers/workspace.ts autopep/src/server/agent/modal-launcher.ts autopep/src/server/agent/run-launcher.ts autopep/src/server/agent/project-run-creator.ts autopep/src/server/agent/*.test.ts
git commit -m "feat: add workspace message run api"
```

## Task 5: Artifact Service And R2 Read Support

**Files:**
- Modify: `autopep/src/server/artifacts/r2.ts`
- Create: `autopep/src/server/artifacts/artifact-service.ts`
- Create: `autopep/src/server/artifacts/artifact-service.test.ts`

- [ ] **Step 1: Write artifact service tests**

```ts
import { describe, expect, it, vi } from "vitest";

import { createR2ArtifactStore } from "./r2";
import { buildArtifactMetadata } from "./artifact-service";

describe("buildArtifactMetadata", () => {
	it("creates workspace-scoped metadata for generated PDB artifacts", async () => {
		expect(
			buildArtifactMetadata({
				byteSize: 120,
				candidateId: "33333333-3333-4333-8333-333333333333",
				contentType: "chemical/x-pdb",
				fileName: "candidate-1.pdb",
				kind: "pdb",
				runId: "22222222-2222-4222-8222-222222222222",
				sha256: "abc123",
				storageKey: "workspaces/w/runs/r/candidate-1.pdb",
				workspaceId: "11111111-1111-4111-8111-111111111111",
			}),
		).toMatchObject({
			kind: "pdb",
			name: "candidate-1.pdb",
			storageKey: "workspaces/w/runs/r/candidate-1.pdb",
		});
	});
});

describe("createR2ArtifactStore readObjectText", () => {
	it("reads UTF-8 object bodies from the configured bucket", async () => {
		const send = vi.fn().mockResolvedValue({
			Body: {
				transformToString: () => Promise.resolve("data_autopep"),
			},
		});
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: { send },
			presigner: vi.fn(),
			publicBaseUrl: null,
		});

		await expect(store.readObjectText({ key: "runs/r/source.cif" })).resolves.toBe("data_autopep");
	});
});
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd autopep
bunx vitest run src/server/artifacts/artifact-service.test.ts src/server/artifacts/r2.test.ts
```

Expected: FAIL because `readObjectText` and `buildArtifactMetadata` do not exist.

- [ ] **Step 3: Extend R2 store**

Add `GetObjectCommand` read behavior:

```ts
type ReadObjectTextInput = {
	key: string;
};

export const createR2ArtifactStore = ({
	bucket,
	client,
	presigner = defaultPresigner,
	publicBaseUrl = env.R2_PUBLIC_BASE_URL,
}: R2ArtifactStoreConfig) => ({
	upload: async ({ key, body, contentType }: UploadInput) => {
		await client.send(new PutObjectCommand({ Body: body, Bucket: bucket, ContentType: contentType, Key: key }));
	},
	readObjectText: async ({ key }: ReadObjectTextInput) => {
		const result = await client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
		const body = (result as { Body?: { transformToString?: () => Promise<string> } }).Body;
		if (!body?.transformToString) throw new Error(`R2 object ${key} did not return a readable body.`);
		return body.transformToString();
	},
	getReadUrl: async ({ key, expiresInSeconds = defaultReadUrlExpirySeconds }: GetReadUrlInput) => {
		if (publicBaseUrl) return buildPublicReadUrl(publicBaseUrl, key);
		return presigner(client, new GetObjectCommand({ Bucket: bucket, Key: key }), { expiresIn: expiresInSeconds });
	},
});
```

- [ ] **Step 4: Create metadata helper**

```ts
import type { ArtifactKind } from "@/server/agent/contracts";

export type ArtifactMetadataInput = {
	byteSize: number;
	candidateId?: string | null;
	contentType: string;
	fileName: string;
	kind: ArtifactKind;
	runId: string;
	sha256?: string | null;
	sourceArtifactId?: string | null;
	storageKey: string;
	workspaceId: string;
};

export const buildArtifactMetadata = ({
	byteSize,
	candidateId = null,
	contentType,
	fileName,
	kind,
	runId,
	sha256 = null,
	sourceArtifactId = null,
	storageKey,
	workspaceId,
}: ArtifactMetadataInput) => ({
	byteSize,
	candidateId,
	contentType,
	kind,
	metadataJson: {},
	name: fileName,
	sha256,
	sourceArtifactId,
	storageKey,
	storageProvider: "r2" as const,
	workspaceId,
	runId,
});
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd autopep
bunx vitest run src/server/artifacts/artifact-service.test.ts src/server/artifacts/r2.test.ts
bun run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/src/server/artifacts/r2.ts autopep/src/server/artifacts/artifact-service.ts autopep/src/server/artifacts/*.test.ts
git commit -m "feat: add artifact service read support"
```

## Task 6: Python Worker Package And Modal Launcher

**Model selection policy (applies to every task that picks a model):**

- Real demo runs (the 3CL-protease workflow, anything user-facing, anything that has to actually reason about biology): use `gpt-5.5`. This is the latest model and the production default.
- Cheap roundtrip/smoke runs that only need to prove plumbing works (Task 11.5, future CI smokes): use a `gpt-5.x-mini` variant — for example `gpt-5.5-mini`. **Do not use Anthropic Haiku or any non-OpenAI model** — the worker is built around the OpenAI Agents SDK and Haiku will not work.

`OPENAI_DEFAULT_MODEL` may override the default. Smoke harnesses should pass an explicit model rather than relying on the default so a misconfigured env var cannot silently turn a real run into a mini run or vice versa.

**Files:**
- Replace: `autopep/modal/autopep_worker.py`
- Create: `autopep/modal/requirements.txt`
- Create: `autopep/modal/requirements-dev.txt`
- Create: `autopep/modal/autopep_agent/__init__.py`
- Create: `autopep/modal/autopep_agent/config.py`
- Create: `autopep/modal/tests/test_config.py`

- [ ] **Step 1: Add Python dependency manifests**

Create `autopep/modal/requirements.txt`:

```txt
fastapi[standard]
modal
openai-agents[modal]
httpx
psycopg[binary]
boto3
pydantic
biopython
```

Create `autopep/modal/requirements-dev.txt`:

```txt
-r requirements.txt
pytest
pytest-asyncio
respx
```

- [ ] **Step 2: Write config tests**

```py
import os

from autopep_agent.config import WorkerConfig


def test_worker_config_reads_required_runtime_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@example.com:5432/db")
    monkeypatch.setenv("R2_BUCKET", "autopep-test")
    monkeypatch.setenv("R2_ACCOUNT_ID", "account")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("MODAL_PROTEINA_URL", "https://proteina.example")
    monkeypatch.setenv("MODAL_PROTEINA_API_KEY", "proteina-key")
    monkeypatch.setenv("MODAL_CHAI_URL", "https://chai.example")
    monkeypatch.setenv("MODAL_CHAI_API_KEY", "chai-key")
    monkeypatch.setenv("MODAL_PROTEIN_INTERACTION_SCORING_URL", "https://score.example")
    monkeypatch.setenv("MODAL_PROTEIN_INTERACTION_SCORING_API_KEY", "score-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = WorkerConfig.from_env()

    assert config.database_url.startswith("postgres://")
    assert config.proteina_url == "https://proteina.example"
    assert config.scoring_api_key == "score-key"
```

- [ ] **Step 3: Run failing Python test**

Run:

```bash
cd autopep
python3 -m pip install -r modal/requirements-dev.txt
PYTHONPATH=modal python3 -m pytest modal/tests/test_config.py -q
```

Expected: FAIL because `autopep_agent.config` does not exist.

- [ ] **Step 4: Create config module**

```py
from __future__ import annotations

import os
from dataclasses import dataclass


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for the Autopep worker.")
    return value


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    r2_bucket: str
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    proteina_url: str
    proteina_api_key: str
    chai_url: str
    chai_api_key: str
    scoring_url: str
    scoring_api_key: str
    openai_api_key: str
    default_model: str = "gpt-5.5"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        return cls(
            database_url=_required_env("DATABASE_URL"),
            r2_bucket=_required_env("R2_BUCKET"),
            r2_account_id=_required_env("R2_ACCOUNT_ID"),
            r2_access_key_id=_required_env("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=_required_env("R2_SECRET_ACCESS_KEY"),
            proteina_url=_required_env("MODAL_PROTEINA_URL").rstrip("/"),
            proteina_api_key=_required_env("MODAL_PROTEINA_API_KEY"),
            chai_url=_required_env("MODAL_CHAI_URL").rstrip("/"),
            chai_api_key=_required_env("MODAL_CHAI_API_KEY"),
            scoring_url=_required_env("MODAL_PROTEIN_INTERACTION_SCORING_URL").rstrip("/"),
            scoring_api_key=_required_env("MODAL_PROTEIN_INTERACTION_SCORING_API_KEY"),
            openai_api_key=_required_env("OPENAI_API_KEY"),
            default_model=os.environ.get("OPENAI_DEFAULT_MODEL", "gpt-5.5"),
        )
```

- [ ] **Step 5: Replace Modal launcher**

Use the existing `start-run` FastAPI endpoint shape, but spawn `run_autopep_agent` instead of the Codex/Bun harness. The endpoint validates `workspaceId`, `threadId`, and `runId`.

```py
@app.function(
    image=worker_image,
    secrets=[runtime_secret],
    timeout=60 * 60,
    volumes={WORKSPACE_DIR: workspace_volume},
    cpu=1.0,
    memory=2048,
)
def run_autopep_agent(workspace_id: str, thread_id: str, run_id: str) -> str:
    import asyncio

    from autopep_agent.runner import execute_run

    asyncio.run(
        execute_run(
            run_id=run_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
    )
    return run_id


@app.function(image=control_image, secrets=[webhook_secret], timeout=120)
@modal.fastapi_endpoint(method="POST", docs=False, label="start-run")
async def start_run(request: Request) -> Any:
    from fastapi.responses import JSONResponse

    _require_bearer(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise _http_error(status_code=422, detail="Expected a JSON object.")

    workspace_id = _require_uuid(payload, "workspaceId")
    thread_id = _require_uuid(payload, "threadId")
    run_id = _require_uuid(payload, "runId")
    function_call = run_autopep_agent.spawn(
        workspace_id=workspace_id,
        thread_id=thread_id,
        run_id=run_id,
    )
    return JSONResponse(
        content={"accepted": True, "functionCallId": function_call.object_id},
        status_code=202,
    )
```

- [ ] **Step 6: Run Python tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/modal/autopep_worker.py autopep/modal/requirements.txt autopep/modal/requirements-dev.txt autopep/modal/autopep_agent autopep/modal/tests/test_config.py
git commit -m "feat: scaffold python agents worker"
```

## Task 7: Python Endpoint Clients For Proteina, Chai, And Scoring

**Files:**
- Create: `autopep/modal/autopep_agent/endpoint_clients.py`
- Create: `autopep/modal/tests/test_endpoint_clients.py`

- [ ] **Step 1: Write mocked endpoint client tests**

```py
import base64

import httpx
import pytest
import respx

from autopep_agent.endpoint_clients import ChaiClient, ProteinaClient, ScoringClient


@pytest.mark.asyncio
async def test_proteina_design_posts_target_structure():
    route = respx.post("https://proteina.example/design").mock(
        return_value=httpx.Response(
            200,
            json={
                "format": "pdb",
                "count": 1,
                "pdbs": [{"rank": 1, "filename": "candidate_1.pdb", "pdb": "ATOM\n"}],
            },
        )
    )
    client = ProteinaClient(base_url="https://proteina.example", api_key="key")

    result = await client.design(
        target_structure="data_target\n",
        target_filename="target.cif",
        target_input="A1-306",
        hotspot_residues=["A41", "A145"],
        binder_length=[60, 120],
    )

    request = route.calls[0].request
    assert request.headers["X-API-Key"] == "key"
    assert request.json()["target"]["structure"] == "data_target\n"
    assert result["pdbs"][0]["filename"] == "candidate_1.pdb"


@pytest.mark.asyncio
async def test_chai_predict_posts_fasta_and_sampling():
    respx.post("https://chai.example/predict").mock(
        return_value=httpx.Response(
            200,
            json={
                "format": "cif",
                "count": 1,
                "cifs": [{"rank": 1, "filename": "fold_1.cif", "cif": "data_fold", "mean_plddt": 82.1}],
            },
        )
    )
    client = ChaiClient(base_url="https://chai.example", api_key="key")

    result = await client.predict(fasta=">candidate\nACDE\n", num_diffn_samples=1)

    assert result["cifs"][0]["mean_plddt"] == 82.1


@pytest.mark.asyncio
async def test_scoring_batch_sends_base64_structure():
    route = respx.post("https://score.example/score_batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "pair-1",
                        "status": "ok",
                        "scores": {
                            "dscript": {"available": True, "interaction_probability": 0.74},
                            "prodigy": {"available": True, "delta_g_kcal_per_mol": -7.4, "kd_molar": 3.8e-6},
                        },
                        "aggregate": {"available": True, "label": "likely_binder", "notes": []},
                        "errors": [],
                        "warnings": [],
                    }
                ],
                "batch_summary": {"submitted": 1, "succeeded": 1, "partial": 0, "failed": 0},
            },
        )
    )
    client = ScoringClient(base_url="https://score.example", api_key="key")

    result = await client.score_batch(
        items=[
            {
                "id": "pair-1",
                "protein_a": {"name": "3CLpro", "sequence": "ACDE"},
                "protein_b": {"name": "binder", "sequence": "FGHI"},
                "structure": {
                    "format": "pdb",
                    "content_base64": base64.b64encode(b"ATOM\n").decode("ascii"),
                    "chain_a": "A",
                    "chain_b": "B",
                },
            }
        ]
    )

    assert route.calls[0].request.headers["X-API-Key"] == "key"
    assert result["results"][0]["aggregate"]["label"] == "likely_binder"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_endpoint_clients.py -q
```

Expected: FAIL because the clients do not exist.

- [ ] **Step 3: Implement endpoint clients**

```py
from __future__ import annotations

from typing import Any

import httpx


class ModalEndpointClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                headers={"X-API-Key": self.api_key, "content-type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()


class ProteinaClient(ModalEndpointClient):
    async def design(
        self,
        *,
        target_structure: str,
        target_filename: str,
        target_input: str | None,
        hotspot_residues: list[str],
        binder_length: list[int],
    ) -> dict[str, Any]:
        return await self.post_json(
            "/design",
            {
                "action": "design-cif",
                "target": {
                    "structure": target_structure,
                    "filename": target_filename,
                    "target_input": target_input,
                    "hotspot_residues": hotspot_residues,
                    "binder_length": binder_length,
                },
            },
        )


class ChaiClient(ModalEndpointClient):
    async def predict(self, *, fasta: str, num_diffn_samples: int = 1) -> dict[str, Any]:
        return await self.post_json(
            "/predict",
            {
                "fasta": fasta,
                "num_trunk_recycles": 3,
                "num_diffn_timesteps": 200,
                "num_diffn_samples": num_diffn_samples,
                "seed": 42,
                "include_pdb": False,
                "include_viewer_html": False,
            },
        )


class ScoringClient(ModalEndpointClient):
    async def score_batch(self, *, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.post_json(
            "/score_batch",
            {
                "items": items,
                "options": {
                    "run_dscript": True,
                    "run_prodigy": True,
                    "temperature_celsius": 25.0,
                    "fail_fast": False,
                },
            },
        )
```

- [ ] **Step 4: Run endpoint tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_endpoint_clients.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autopep/modal/autopep_agent/endpoint_clients.py autopep/modal/tests/test_endpoint_clients.py
git commit -m "feat: add modal inference endpoint clients"
```

## Task 8: Python Event Normalization And DB Writer

**Files:**
- Create: `autopep/modal/autopep_agent/events.py`
- Create: `autopep/modal/autopep_agent/db.py`
- Create: `autopep/modal/autopep_agent/streaming.py`
- Create: `autopep/modal/tests/test_streaming.py`

- [ ] **Step 1: Write stream normalization tests**

```py
from types import SimpleNamespace

from autopep_agent.streaming import normalize_stream_event


def test_normalize_text_delta_event():
    event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.output_text.delta", delta="hello"),
    )

    normalized = normalize_stream_event(event)

    assert normalized["type"] == "assistant_token_delta"
    assert normalized["display"]["delta"] == "hello"


def test_normalize_tool_call_event():
    event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(type="tool_call_item", raw_item={"name": "search_structures"}),
    )

    normalized = normalize_stream_event(event)

    assert normalized["type"] == "tool_call_started"
    assert normalized["title"] == "Tool call started"
    assert normalized["display"]["name"] == "search_structures"


def test_normalize_agent_update():
    event = SimpleNamespace(
        type="agent_updated_stream_event",
        new_agent=SimpleNamespace(name="Autopep structure agent"),
    )

    normalized = normalize_stream_event(event)

    assert normalized["type"] == "agent_changed"
    assert normalized["summary"] == "Autopep structure agent"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_streaming.py -q
```

Expected: FAIL because stream normalization does not exist.

- [ ] **Step 3: Implement stream normalization**

```py
from __future__ import annotations

from typing import Any


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _as_jsonable(value.model_dump())
    return repr(value)


def normalize_stream_event(event: Any) -> dict[str, Any] | None:
    raw = _as_jsonable(event)
    event_type = getattr(event, "type", None)

    if event_type == "raw_response_event":
        data = getattr(event, "data", None)
        if getattr(data, "type", None) == "response.output_text.delta":
            delta = getattr(data, "delta", "")
            if delta:
                return {
                    "type": "assistant_token_delta",
                    "title": "Assistant token",
                    "summary": None,
                    "display": {"delta": delta},
                    "raw": raw,
                }
        return None

    if event_type == "agent_updated_stream_event":
        name = getattr(getattr(event, "new_agent", None), "name", "Agent")
        return {
            "type": "agent_changed",
            "title": "Agent changed",
            "summary": name,
            "display": {"agentName": name},
            "raw": raw,
        }

    if event_type == "run_item_stream_event":
        name = getattr(event, "name", "")
        item = getattr(event, "item", None)
        raw_item = getattr(item, "raw_item", {}) or {}
        tool_name = raw_item.get("name") if isinstance(raw_item, dict) else None
        if name == "tool_called":
            return {
                "type": "tool_call_started",
                "title": "Tool call started",
                "summary": tool_name,
                "display": {"name": tool_name},
                "raw": raw,
            }
        if name == "tool_output":
            return {
                "type": "tool_call_completed",
                "title": "Tool call completed",
                "summary": tool_name,
                "display": {"name": tool_name},
                "raw": raw,
            }
        if name == "reasoning_item_created":
            return {
                "type": "reasoning_step",
                "title": "Reasoning step",
                "summary": None,
                "display": {},
                "raw": raw,
            }
    return None
```

- [ ] **Step 4: Implement DB writer**

Create a minimal `EventWriter` using psycopg parameterized SQL:

```py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg


@dataclass
class EventWriter:
    database_url: str

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        title: str,
        summary: str | None = None,
        display: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into autopep_agent_event (run_id, sequence, type, title, summary, display_json, raw_json)
                    values (
                        %s,
                        coalesce((select max(sequence) from autopep_agent_event where run_id = %s), 0) + 1,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::jsonb
                    )
                    """,
                    (
                        run_id,
                        run_id,
                        event_type,
                        title,
                        summary,
                        json.dumps(display or {}),
                        json.dumps(raw or {}),
                    ),
                )
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_streaming.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/modal/autopep_agent/events.py autopep/modal/autopep_agent/db.py autopep/modal/autopep_agent/streaming.py autopep/modal/tests/test_streaming.py
git commit -m "feat: normalize agents sdk stream events"
```

## Task 9: Structure Utilities And Biology Tool Wrappers

**Files:**
- Create: `autopep/modal/autopep_agent/structure_utils.py`
- Create: `autopep/modal/autopep_agent/research_tools.py`
- Create: `autopep/modal/autopep_agent/biology_tools.py`
- Create: `autopep/modal/tests/test_structure_utils.py`
- Create: `autopep/modal/tests/test_biology_tools.py`

- [ ] **Step 1: Write structure utility tests**

```py
import base64

from autopep_agent.structure_utils import build_fasta, encode_structure_base64, extract_pdb_sequences


PDB_TEXT = """\
ATOM      1  N   ALA A   1      11.104  13.207   9.104  1.00 20.00           N
ATOM      2  CA  ALA A   1      12.104  13.207   9.104  1.00 20.00           C
ATOM      3  N   GLY B   1      15.104  10.207   7.104  1.00 20.00           N
ATOM      4  CA  GLY B   1      16.104  10.207   7.104  1.00 20.00           C
END
"""


def test_extract_pdb_sequences_by_chain():
    assert extract_pdb_sequences(PDB_TEXT) == {"A": "A", "B": "G"}


def test_build_fasta_from_candidates():
    fasta = build_fasta([{"id": "candidate-1", "sequence": "ACDE"}])
    assert fasta == ">candidate-1\nACDE\n"


def test_encode_structure_base64():
    encoded = encode_structure_base64("ATOM\n")
    assert base64.b64decode(encoded.encode("ascii")) == b"ATOM\n"
```

- [ ] **Step 2: Run failing utility tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_structure_utils.py -q
```

Expected: FAIL because the utilities do not exist.

- [ ] **Step 3: Implement structure utilities**

```py
from __future__ import annotations

import base64


THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def extract_pdb_sequences(pdb_text: str) -> dict[str, str]:
    residues: dict[str, list[tuple[int, str]]] = {}
    seen: set[tuple[str, int, str]] = set()
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        residue_name = line[17:20].strip()
        chain_id = line[21].strip() or "_"
        residue_number_text = line[22:26].strip()
        if not residue_number_text.lstrip("-").isdigit():
            continue
        residue_number = int(residue_number_text)
        key = (chain_id, residue_number, residue_name)
        if key in seen:
            continue
        seen.add(key)
        residues.setdefault(chain_id, []).append((residue_number, THREE_TO_ONE.get(residue_name, "X")))
    return {
        chain_id: "".join(code for _number, code in sorted(chain_residues))
        for chain_id, chain_residues in residues.items()
    }


def build_fasta(candidates: list[dict[str, str]]) -> str:
    return "".join(f">{candidate['id']}\n{candidate['sequence'].strip().upper()}\n" for candidate in candidates)


def encode_structure_base64(structure_text: str) -> str:
    return base64.b64encode(structure_text.encode("utf-8")).decode("ascii")
```

- [ ] **Step 4: Create biology tool wrappers**

Wrap endpoint calls and emit domain-shaped results:

```py
from __future__ import annotations

from typing import Any

from agents import function_tool

from .endpoint_clients import ChaiClient, ProteinaClient, ScoringClient
from .structure_utils import build_fasta, encode_structure_base64, extract_pdb_sequences


@function_tool
async def generate_binder_candidates(
    target_structure: str,
    target_filename: str,
    target_input: str | None,
    hotspot_residues: list[str],
    binder_length_min: int,
    binder_length_max: int,
    proteina_base_url: str,
    proteina_api_key: str,
) -> dict[str, Any]:
    client = ProteinaClient(base_url=proteina_base_url, api_key=proteina_api_key)
    response = await client.design(
        target_structure=target_structure,
        target_filename=target_filename,
        target_input=target_input,
        hotspot_residues=hotspot_residues,
        binder_length=[binder_length_min, binder_length_max],
    )
    candidates = []
    for item in response.get("pdbs", []):
        sequences = extract_pdb_sequences(item["pdb"])
        binder_sequence = sequences.get("B") or next(iter(sequences.values()), "")
        candidates.append(
            {
                "rank": item["rank"],
                "filename": item["filename"],
                "pdb": item["pdb"],
                "sequence": binder_sequence,
            }
        )
    return {"raw": response, "candidates": candidates}


@function_tool
async def fold_sequences_with_chai(
    sequence_candidates: list[dict[str, str]],
    chai_base_url: str,
    chai_api_key: str,
) -> dict[str, Any]:
    client = ChaiClient(base_url=chai_base_url, api_key=chai_api_key)
    return await client.predict(fasta=build_fasta(sequence_candidates), num_diffn_samples=1)


@function_tool
async def score_candidate_interactions(
    target_name: str,
    target_sequence: str,
    candidates: list[dict[str, str]],
    scoring_base_url: str,
    scoring_api_key: str,
) -> dict[str, Any]:
    client = ScoringClient(base_url=scoring_base_url, api_key=scoring_api_key)
    items = []
    for candidate in candidates:
        structure = candidate.get("pdb")
        items.append(
            {
                "id": candidate["id"],
                "protein_a": {"name": target_name, "sequence": target_sequence},
                "protein_b": {"name": candidate["id"], "sequence": candidate["sequence"]},
                "structure": {
                    "format": "pdb",
                    "content_base64": encode_structure_base64(structure),
                    "chain_a": "A",
                    "chain_b": "B",
                }
                if structure
                else None,
            }
        )
    return await client.score_batch(items=items)
```

- [ ] **Step 5: Run biology tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_structure_utils.py modal/tests/test_biology_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/modal/autopep_agent/structure_utils.py autopep/modal/autopep_agent/research_tools.py autopep/modal/autopep_agent/biology_tools.py autopep/modal/tests/test_structure_utils.py autopep/modal/tests/test_biology_tools.py
git commit -m "feat: add biology tool wrappers"
```

## Task 10: Python Agent Runner And One-Loop MVP Workflow

**Files:**
- Create: `autopep/modal/autopep_agent/runner.py`
- Create: `autopep/modal/tests/test_runner.py`

- [ ] **Step 1: Write runner tests with fake dependencies**

```py
import pytest

from autopep_agent.runner import build_agent_instructions, choose_task_kind


def test_choose_task_kind_routes_demo_prompt_to_branch_design():
    assert choose_task_kind("Generate a protein that binds to 3CL-protease") == "branch_design"


def test_choose_task_kind_preserves_simple_chat():
    assert choose_task_kind("Explain this residue selection") == "chat"


def test_build_agent_instructions_mentions_required_tools():
    instructions = build_agent_instructions(enabled_recipes=["Use PDB and bioRxiv first."])
    assert "life-science-research" in instructions
    assert "generate_binder_candidates" in instructions
    assert "score_candidate_interactions" in instructions
    assert "Use PDB and bioRxiv first." in instructions
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_runner.py -q
```

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement runner scaffolding**

Use SDK-native streaming and Modal sandbox config. The current OpenAI Agents SDK streaming docs show `Runner.run_streamed(...)` returning a result with `stream_events()`. The Modal extension exposes `ModalSandboxClient` and `ModalSandboxClientOptions` from `agents.extensions.sandbox.modal`.

```py
from __future__ import annotations

from agents import Agent, Runner, RunConfig, SandboxAgent, function_tool
from agents.extensions.sandbox.modal import ModalSandboxClient, ModalSandboxClientOptions
from agents.sandbox import SandboxRunConfig

from .biology_tools import (
    fold_sequences_with_chai,
    generate_binder_candidates,
    score_candidate_interactions,
)
from .config import WorkerConfig
from .events import EventWriter
from .streaming import normalize_stream_event


def choose_task_kind(prompt: str) -> str:
    normalized = prompt.lower()
    if "generate" in normalized and ("3cl" in normalized or "protease" in normalized or "bind" in normalized):
        return "branch_design"
    if "mutate" in normalized:
        return "mutate_structure"
    if "pdb" in normalized or "structure" in normalized:
        return "structure_search"
    return "chat"


def build_agent_instructions(enabled_recipes: list[str]) -> str:
    recipe_block = "\n\n".join(enabled_recipes)
    return f"""You are Autopep, a life-sciences research and protein design agent.
The life-science-research plugin is always available and should be treated as platform context.
For the MVP binder demo, run one complete loop: literature research, PDB search, target preparation,
generate_binder_candidates, fold_sequences_with_chai, score_candidate_interactions, and ranked summary.
Use computational screening language only; do not claim experimental binding.

Enabled recipes:
{recipe_block}
"""


def build_autopep_agent(enabled_recipes: list[str]) -> Agent:
    return Agent(
        name="Autopep",
        instructions=build_agent_instructions(enabled_recipes),
        tools=[
            generate_binder_candidates,
            fold_sequences_with_chai,
            score_candidate_interactions,
        ],
    )


def build_sandbox_config() -> SandboxRunConfig:
    return SandboxRunConfig(
        client=ModalSandboxClient(),
        options=ModalSandboxClientOptions(
            app_name="autopep-agent",
            workspace_persistence="snapshot_filesystem",
            timeout=60 * 60,
        ),
    )


async def execute_run(*, run_id: str, thread_id: str, workspace_id: str) -> None:
    config = WorkerConfig.from_env()
    writer = EventWriter(config.database_url)
    await writer.append_event(run_id=run_id, event_type="run_started", title="Run started")

    agent = build_autopep_agent(enabled_recipes=[])
    run_result = Runner.run_streamed(
        agent,
        input=f"Workspace {workspace_id}, thread {thread_id}, run {run_id}. Execute the user task.",
        run_config=RunConfig(
            model=config.default_model,
            sandbox=build_sandbox_config(),
            trace_include_sensitive_data=False,
        ),
    )

    async for sdk_event in run_result.stream_events():
        normalized = normalize_stream_event(sdk_event)
        if normalized:
            await writer.append_event(
                run_id=run_id,
                event_type=normalized["type"],
                title=normalized["title"],
                summary=normalized.get("summary"),
                display=normalized.get("display") or {},
                raw=normalized.get("raw") or {},
            )

    await writer.append_event(run_id=run_id, event_type="run_completed", title="Run completed")
```

- [ ] **Step 4: Persist final run state**

Extend `execute_run` after streaming to update `autopep_agent_run.status`, `finished_at`, `sdk_state_json`, and `last_response_id`. On exceptions, append `run_failed` and set `status='failed'`.

```py
try:
    await writer.append_event(run_id=run_id, event_type="run_started", title="Run started")
    agent = build_autopep_agent(enabled_recipes=[])
    run_result = Runner.run_streamed(
        agent,
        input=f"Workspace {workspace_id}, thread {thread_id}, run {run_id}. Execute the user task.",
        run_config=RunConfig(
            model=config.default_model,
            sandbox=build_sandbox_config(),
            trace_include_sensitive_data=False,
        ),
    )
    async for sdk_event in run_result.stream_events():
        normalized = normalize_stream_event(sdk_event)
        if normalized:
            await writer.append_event(
                run_id=run_id,
                event_type=normalized["type"],
                title=normalized["title"],
                summary=normalized.get("summary"),
                display=normalized.get("display") or {},
                raw=normalized.get("raw") or {},
            )
    await writer.append_event(run_id=run_id, event_type="run_completed", title="Run completed")
    await mark_run_completed(database_url=config.database_url, run_id=run_id)
except Exception as exc:
    await writer.append_event(
        run_id=run_id,
        event_type="run_failed",
        title="Run failed",
        summary=str(exc),
        raw={"error": repr(exc)},
    )
    await mark_run_failed(database_url=config.database_url, run_id=run_id, error_summary=str(exc))
    raise
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_runner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_runner.py
git commit -m "feat: add agents sdk runner"
```

## Task 11: Persist MVP Candidates, Folds, And Scores

**Files:**
- Modify: `autopep/modal/autopep_agent/db.py`
- Modify: `autopep/modal/autopep_agent/runner.py`
- Create: `autopep/modal/tests/test_mvp_persistence.py`

- [ ] **Step 1: Write score mapping tests**

```py
from autopep_agent.db import map_scoring_result_to_rows


def test_map_scoring_result_to_candidate_score_rows():
    rows = map_scoring_result_to_rows(
        candidate_id="candidate-1",
        model_inference_id="inference-1",
        result={
            "status": "ok",
            "scores": {
                "dscript": {"available": True, "interaction_probability": 0.74, "raw_score": 1.2},
                "prodigy": {"available": True, "delta_g_kcal_per_mol": -7.4, "kd_molar": 3.8e-6},
            },
            "aggregate": {"available": True, "label": "likely_binder", "notes": []},
            "warnings": [],
            "errors": [],
        },
    )

    assert rows[0]["scorer"] == "dscript"
    assert rows[0]["value"] == 0.74
    assert rows[1]["scorer"] == "prodigy"
    assert rows[1]["unit"] == "kcal/mol"
    assert rows[2]["scorer"] == "protein_interaction_aggregate"
    assert rows[2]["label"] == "likely_binder"
```

- [ ] **Step 2: Run failing persistence tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_mvp_persistence.py -q
```

Expected: FAIL because score mapping does not exist.

- [ ] **Step 3: Implement candidate score mapping**

```py
def map_scoring_result_to_rows(candidate_id: str, model_inference_id: str, result: dict) -> list[dict]:
    scores = result.get("scores", {})
    warnings = result.get("warnings", [])
    errors = result.get("errors", [])
    rows = []

    dscript = scores.get("dscript", {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "dscript",
            "status": result.get("status", "partial") if dscript.get("available") else "unavailable",
            "label": None,
            "value": dscript.get("interaction_probability"),
            "unit": "probability",
            "values_json": dscript,
            "warnings_json": dscript.get("warnings", warnings),
            "errors_json": errors,
        }
    )

    prodigy = scores.get("prodigy", {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "prodigy",
            "status": result.get("status", "partial") if prodigy.get("available") else "unavailable",
            "label": None,
            "value": prodigy.get("delta_g_kcal_per_mol"),
            "unit": "kcal/mol",
            "values_json": prodigy,
            "warnings_json": prodigy.get("warnings", warnings),
            "errors_json": errors,
        }
    )

    aggregate = result.get("aggregate", {})
    rows.append(
        {
            "candidate_id": candidate_id,
            "model_inference_id": model_inference_id,
            "scorer": "protein_interaction_aggregate",
            "status": result.get("status", "partial") if aggregate.get("available") else "unavailable",
            "label": aggregate.get("label"),
            "value": None,
            "unit": None,
            "values_json": aggregate,
            "warnings_json": warnings,
            "errors_json": errors,
        }
    )
    return rows
```

- [ ] **Step 4: Persist model inference rows and artifacts**

Add DB helpers with parameterized inserts:

```py
async def create_model_inference(conn, *, workspace_id, run_id, model_name, request_json, endpoint_url):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into autopep_model_inference
                (workspace_id, run_id, provider, model_name, status, endpoint_url_snapshot, request_json, started_at)
            values (%s, %s, 'modal', %s, 'running', %s, %s::jsonb, now())
            returning id
            """,
            (workspace_id, run_id, model_name, endpoint_url, json.dumps(request_json)),
        )
        row = await cur.fetchone()
        return row[0]
```

Call these helpers from the one-loop workflow around Proteina, Chai, and scoring. Insert `artifact_created` and `candidate_ranked` events immediately after each durable artifact/candidate insert.

- [ ] **Step 5: Run persistence tests**

Run:

```bash
cd autopep
PYTHONPATH=modal python3 -m pytest modal/tests/test_mvp_persistence.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/modal/autopep_agent/db.py autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_mvp_persistence.py
git commit -m "feat: persist generated candidates and scores"
```

## Task 11.5: Integration Smoke Roundtrip

This task is integration verification, not unit testing. It proves that TS launcher → Modal worker → OpenAI Agents SDK → Neon → polling endpoint actually round-trip with no biology, no frontend, and no inference endpoints involved. Three layered smokes isolate which integration surface is broken when one fails.

Run this before starting Task 12. Re-run before Task 15 to catch any regressions introduced by frontend work. Each smoke runs against `gpt-5.5-mini` (or any current `gpt-5.x-mini`) and should cost a fraction of a cent.

**Files:**
- Create: `autopep/modal/autopep_agent/smoke_agent.py`
- Modify: `autopep/modal/autopep_agent/runner.py`
- Create: `autopep/modal/tests/test_smoke_runner.py`
- Create: `autopep/scripts/smoke-roundtrip.ts`
- Modify: `autopep/.env.example`
- Modify: `autopep/README.md`

- [ ] **Step 1: Provision an isolated smoke environment**

Use a Neon branch and a separate Modal app so smoke runs cannot touch production state.

```bash
# Neon branch off main, ~3s, free under branching plan
neon branches create --name autopep-smoke --parent main
export AUTOPEP_SMOKE_DATABASE_URL="$(neon connection-string autopep-smoke)"
cd autopep
DATABASE_URL=$AUTOPEP_SMOKE_DATABASE_URL bun run db:migrate

# Separate Modal app — distinct start-run URL and webhook secret
modal config set-environment smoke
APP_NAME=autopep-agent-smoke modal deploy modal/autopep_worker.py
```

Capture the deployed `start-run` URL into `AUTOPEP_SMOKE_MODAL_START_URL` and the webhook secret into `AUTOPEP_SMOKE_MODAL_WEBHOOK_SECRET`. Do not reuse production secrets.

- [ ] **Step 2: Implement the smoke agent**

The smoke agent has three modes selected by `task_kind`. None of them touch biology tools, RCSB, PubMed, or any Modal inference endpoint.

```py
# autopep/modal/autopep_agent/smoke_agent.py
from __future__ import annotations

from agents import Agent, function_tool


@function_tool
def smoke_now() -> str:
    """Return the literal string 'now-ok' so smoke_tool can verify tool plumbing."""
    return "now-ok"


SMOKE_MODEL = "gpt-5.5-mini"  # cheap variant; see Task 6 model selection policy. Never haiku.


def build_ping_agent(model: str = SMOKE_MODEL) -> Agent:
    return Agent(
        name="autopep-smoke-ping",
        model=model,
        instructions="Reply with the literal text 'pong' and nothing else.",
    )


def build_tool_agent(model: str = SMOKE_MODEL) -> Agent:
    return Agent(
        name="autopep-smoke-tool",
        model=model,
        instructions=(
            "Call the smoke_now tool exactly once, then reply with its return value verbatim."
        ),
        tools=[smoke_now],
    )


# build_sandbox_agent should return a SandboxAgent configured with
# ModalSandboxClient that runs `echo sandbox-ok` and exits. It exercises
# the sandbox_command_started, sandbox_stdout_delta, and
# sandbox_command_completed event paths added in Task 8.
```

- [ ] **Step 3: Route smoke task kinds in the runner**

Extend `execute_run` to dispatch `task_kind` values prefixed with `smoke_` to the smoke agent. These task kinds are accepted only when `AUTOPEP_ALLOW_SMOKE_RUNS=1`. Never expose them through the tRPC router.

```py
# autopep/modal/autopep_agent/runner.py
SMOKE_TASK_KINDS = {"smoke_chat", "smoke_tool", "smoke_sandbox"}


async def execute_run(*, workspace_id: str, thread_id: str, run_id: str) -> None:
    run = await db.load_run(run_id)
    if run.task_kind in SMOKE_TASK_KINDS:
        if os.environ.get("AUTOPEP_ALLOW_SMOKE_RUNS") != "1":
            raise RuntimeError("Smoke task kinds are disabled in this environment.")
        await _execute_smoke_run(run)
        return
    await _execute_mvp_run(run)
```

`_execute_smoke_run` builds the right agent based on `run.task_kind`, calls `Runner.run_streamed(...)`, and feeds events through the same normalizer + DB writer used for real runs. No code path is duplicated — this is the same plumbing, with a smaller agent attached.

- [ ] **Step 4: Implement the TS smoke harness**

The harness creates a workspace, thread, and message+run with the chosen `task_kind`, fires the smoke Modal `start-run`, and polls for terminal status.

```ts
// autopep/scripts/smoke-roundtrip.ts
// Run: bun run autopep/scripts/smoke-roundtrip.ts smoke_chat
import { eq } from "drizzle-orm";

import { db } from "@/server/db";
import { agentEvents, agentRuns } from "@/server/db/schema";
import { createMessageRunWithLaunch } from "@/server/agent/project-run-creator";

const TASK_KIND = process.argv[2] as "smoke_chat" | "smoke_tool" | "smoke_sandbox";
const DEADLINE_MS = 90_000;
const POLL_MS = 1500;

if (!TASK_KIND || !TASK_KIND.startsWith("smoke_")) {
  throw new Error("Usage: smoke-roundtrip.ts <smoke_chat|smoke_tool|smoke_sandbox>");
}

const { runId } = await createMessageRunWithLaunch({
  contextRefs: [],
  db,
  ownerId: process.env.AUTOPEP_SMOKE_OWNER_ID!,
  prompt: "ping",
  recipeRefs: [],
  taskKind: TASK_KIND,
  threadId: process.env.AUTOPEP_SMOKE_THREAD_ID!,
  workspaceId: process.env.AUTOPEP_SMOKE_WORKSPACE_ID!,
});

const start = Date.now();
let run;
while (Date.now() - start < DEADLINE_MS) {
  [run] = await db.select().from(agentRuns).where(eq(agentRuns.id, runId));
  if (run.status === "completed" || run.status === "failed") break;
  await new Promise((resolve) => setTimeout(resolve, POLL_MS));
}

const events = await db
  .select()
  .from(agentEvents)
  .where(eq(agentEvents.runId, runId))
  .orderBy(agentEvents.sequence);

const types = new Set(events.map((event) => event.type));
const required = ["run_started", "assistant_message_completed", "run_completed"];
if (TASK_KIND === "smoke_tool") required.push("tool_call_completed");
if (TASK_KIND === "smoke_sandbox") required.push("sandbox_command_completed");

const missing = required.filter((type) => !types.has(type));
const sequenceContiguous = events.every(
  (event, index) => event.sequence === index + 1,
);

if (run?.status !== "completed" || missing.length > 0 || !sequenceContiguous) {
  console.error({
    durationMs: Date.now() - start,
    eventCount: events.length,
    missing,
    runStatus: run?.status,
    sequenceContiguous,
  });
  process.exit(1);
}

console.log(
  `✓ ${TASK_KIND} roundtrip in ${Date.now() - start}ms with ${events.length} events`,
);
```

- [ ] **Step 5: Run smoke A — chat ping/pong**

```bash
cd autopep
bun run scripts/smoke-roundtrip.ts smoke_chat
```

Expected: completes in under 15 seconds with at least 5 events, including `run_started`, `assistant_message_started`, at least one `assistant_token_delta`, `assistant_message_completed`, and `run_completed`. Sequence integers are contiguous starting at 1. `agent_runs.last_response_id` and `agent_runs.finished_at` are non-null.

This step alone catches: wrong default model name, Modal secret resolution failures, OpenAI key plumbing, SDK stream event shape drift, webhook bearer auth handshake, and event sequence collisions.

- [ ] **Step 6: Run smoke B — tool call**

```bash
cd autopep
bun run scripts/smoke-roundtrip.ts smoke_tool
```

Expected: completes in under 25 seconds with at least 7 events, adding `tool_call_started` and `tool_call_completed` to the chat baseline. The smoke tool returned `now-ok` exactly once.

This step catches `run_item_stream_event` mapping bugs in the normalizer added in Task 8.

- [ ] **Step 7: Run smoke C — sandbox echo**

```bash
cd autopep
bun run scripts/smoke-roundtrip.ts smoke_sandbox
```

Expected: completes in under 40 seconds with at least 9 events, adding `sandbox_command_started`, `sandbox_stdout_delta` (at least one with `sandbox-ok`), and `sandbox_command_completed`.

This step is the first time `ModalSandboxClient` runs against a real Modal sandbox. It catches sandbox image bring-up failures, stdout streaming deadlocks, and snapshot/resume regressions.

- [ ] **Step 8: Document the runbook and env vars**

Add to `autopep/.env.example`:

```
# Integration smoke (Task 11.5). Disabled in production.
AUTOPEP_ALLOW_SMOKE_RUNS=""
AUTOPEP_SMOKE_DATABASE_URL=""
AUTOPEP_SMOKE_MODAL_START_URL=""
AUTOPEP_SMOKE_MODAL_WEBHOOK_SECRET=""
AUTOPEP_SMOKE_OWNER_ID=""
AUTOPEP_SMOKE_WORKSPACE_ID=""
AUTOPEP_SMOKE_THREAD_ID=""
```

Add a short `## Smoke runbook` section to `autopep/README.md` covering: when to run (after Task 11, before Task 15, on every Modal worker change in CI behind `RUN_SMOKE=1`), the three layered smokes, and the cost envelope.

- [ ] **Step 9: Commit**

```bash
git add autopep/modal/autopep_agent/smoke_agent.py autopep/modal/autopep_agent/runner.py autopep/modal/tests/test_smoke_runner.py autopep/scripts/smoke-roundtrip.ts autopep/.env.example autopep/README.md
git commit -m "test: add integration smoke roundtrip"
```

## Task 12: Unified Chat Panel And Trace Cards

**Files:**
- Create: `autopep/src/app/_components/chat-panel.tsx`
- Create: `autopep/src/app/_components/trace-event-card.tsx`
- Create: `autopep/src/app/_components/chat-panel.test.tsx`
- Create: `autopep/src/app/_components/trace-event-card.test.tsx`
- Modify: `autopep/src/app/_components/autopep-workspace.tsx`

- [ ] **Step 1: Write component tests**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./chat-panel";

describe("ChatPanel", () => {
	it("shows example goals when there are no messages", () => {
		render(
			<ChatPanel
				contextReferences={[]}
				events={[]}
				isSending={false}
				messages={[]}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(screen.getByText("Generate a protein that binds to 3CL-protease")).toBeInTheDocument();
	});

	it("sends the prompt with selected context references", async () => {
		const onSend = vi.fn();
		render(
			<ChatPanel
				contextReferences={[{ id: "ctx-1", label: "6M0J chain A residues 333-527" }]}
				events={[]}
				isSending={false}
				messages={[]}
				onSend={onSend}
				recipes={[]}
			/>,
		);

		await userEvent.type(screen.getByLabelText("Message Autopep"), "Explain this region");
		await userEvent.click(screen.getByLabelText("Send message"));

		expect(onSend).toHaveBeenCalledWith(
			expect.objectContaining({
				contextRefs: ["ctx-1"],
				prompt: "Explain this region",
			}),
		);
	});
});
```

- [ ] **Step 2: Run failing component tests**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/chat-panel.test.tsx src/app/_components/trace-event-card.test.tsx
```

Expected: FAIL because the new components do not exist.

- [ ] **Step 3: Implement `TraceEventCard`**

```tsx
"use client";

import { CaretRight } from "@phosphor-icons/react";
import { useState } from "react";

type TraceEventCardProps = {
	event: {
		displayJson: Record<string, unknown>;
		id: string;
		rawJson: Record<string, unknown>;
		sequence: number;
		summary: string | null;
		title: string;
		type: string;
	};
};

export function TraceEventCard({ event }: TraceEventCardProps) {
	const [open, setOpen] = useState(false);
	return (
		<div className="border-[#e5e2d9] border-b py-2">
			<button
				className="flex w-full items-center gap-2 text-left"
				onClick={() => setOpen((value) => !value)}
				type="button"
			>
				<CaretRight className={open ? "rotate-90" : ""} size={14} />
				<span className="font-medium text-[#26332e] text-sm">{event.title}</span>
				<span className="ml-auto font-mono text-[#7a817a] text-xs">#{event.sequence}</span>
			</button>
			{event.summary ? <p className="mt-1 pl-6 text-[#66706a] text-xs">{event.summary}</p> : null}
			{open ? (
				<pre className="mt-2 max-h-64 overflow-auto rounded-md bg-[#f2f1ea] p-3 text-[#27322f] text-xs">
					{JSON.stringify({ display: event.displayJson, raw: event.rawJson }, null, 2)}
				</pre>
			) : null}
		</div>
	);
}
```

- [ ] **Step 4: Implement `ChatPanel`**

```tsx
"use client";

import { PaperPlaneTilt, Paperclip, SlidersHorizontal } from "@phosphor-icons/react";
import { type FormEvent, useState } from "react";

import { TraceEventCard } from "./trace-event-card";

type ChatPanelProps = {
	contextReferences: { id: string; label: string }[];
	events: React.ComponentProps<typeof TraceEventCard>["event"][];
	isSending: boolean;
	messages: { id: string; role: "user" | "assistant" | "system"; content: string }[];
	onSend: (input: { contextRefs: string[]; prompt: string; recipeRefs: string[] }) => void;
	recipes: { id: string; name: string; enabledByDefault: boolean }[];
};

const examples = [
	"Generate a protein that binds to 3CL-protease",
	"Find and prepare a high-quality SARS-CoV-2 spike RBD structure",
	"Explain this part of the protein",
];

export function ChatPanel({ contextReferences, events, isSending, messages, onSend, recipes }: ChatPanelProps) {
	const [draft, setDraft] = useState("");
	const selectedRecipeIds = recipes.filter((recipe) => recipe.enabledByDefault).map((recipe) => recipe.id);
	const submit = (event: FormEvent) => {
		event.preventDefault();
		const prompt = draft.trim();
		if (!prompt || isSending) return;
		setDraft("");
		onSend({
			contextRefs: contextReferences.map((reference) => reference.id),
			prompt,
			recipeRefs: selectedRecipeIds,
		});
	};

	return (
		<aside className="flex min-h-0 flex-col border-[#e5e2d9] border-r bg-[#fbfaf6]">
			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
				{messages.length === 0 ? (
					<div className="space-y-2">
						{examples.map((example) => (
							<button
								className="w-full rounded-md border border-[#ddd9cf] bg-[#fffef9] px-3 py-2 text-left text-[#26332e] text-sm hover:border-[#ccd747]"
								key={example}
								onClick={() => setDraft(example)}
								type="button"
							>
								{example}
							</button>
						))}
					</div>
				) : (
					<div className="space-y-3">
						{messages.map((message) => (
							<div className={message.role === "user" ? "ml-8 rounded-md bg-[#edf4ed] p-3" : "mr-8 rounded-md bg-[#fffef9] p-3"} key={message.id}>
								{message.content}
							</div>
						))}
					</div>
				)}
				<div className="mt-4">
					{events.map((event) => (
						<TraceEventCard event={event} key={event.id} />
					))}
				</div>
			</div>
			<form className="border-[#e5e2d9] border-t bg-[#fffef9] p-3" onSubmit={submit}>
				<div className="mb-2 flex flex-wrap gap-1">
					{contextReferences.map((reference) => (
						<span className="rounded-md bg-[#eaf4cf] px-2 py-1 text-[#315419] text-xs" key={reference.id}>
							{reference.label}
						</span>
					))}
				</div>
				<label className="sr-only" htmlFor="autopep-chat-input">Message Autopep</label>
				<textarea
					className="min-h-24 w-full resize-none rounded-md border border-[#ddd9cf] bg-[#fbfaf6] px-3 py-2 text-sm outline-none focus:border-[#cbd736]"
					id="autopep-chat-input"
					onChange={(event) => setDraft(event.target.value)}
					value={draft}
				/>
				<div className="mt-2 flex items-center justify-between">
					<div className="flex gap-2 text-[#52605a]">
						<button aria-label="Attach files" className="rounded-md p-2 hover:bg-[#f0efe8]" type="button"><Paperclip size={18} /></button>
						<button aria-label="Run settings" className="rounded-md p-2 hover:bg-[#f0efe8]" type="button"><SlidersHorizontal size={18} /></button>
					</div>
					<button aria-label="Send message" className="rounded-md bg-[#dfe94c] p-2 text-[#1d342e] disabled:opacity-50" disabled={!draft.trim() || isSending} type="submit">
						<PaperPlaneTilt size={20} weight="fill" />
					</button>
				</div>
			</form>
		</aside>
	);
}
```

- [ ] **Step 5: Run component tests**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/chat-panel.test.tsx src/app/_components/trace-event-card.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/src/app/_components/chat-panel.tsx autopep/src/app/_components/trace-event-card.tsx autopep/src/app/_components/*.test.tsx
git commit -m "feat: add unified chat progress panel"
```

## Task 13: Mol* Stage And Context References

**Files:**
- Modify: `autopep/src/app/_components/molstar-viewer.tsx`
- Create: `autopep/src/app/_components/molstar-stage.tsx`
- Create: `autopep/src/app/_components/molstar-stage.test.tsx`
- Modify: `autopep/src/server/api/routers/workspace.ts`

- [ ] **Step 1: Write context reference API test**

```ts
import { describe, expect, it } from "vitest";

import { contextReferenceSchema } from "@/server/agent/contracts";

describe("protein selection context references", () => {
	it("accepts residue-range selections produced by Mol*", () => {
		expect(
			contextReferenceSchema.parse({
				artifactId: "11111111-1111-4111-8111-111111111111",
				candidateId: "22222222-2222-4222-8222-222222222222",
				kind: "protein_selection",
				label: "6M0J chain A residues 41-145",
				selector: {
					authAsymId: "A",
					residueRanges: [{ start: 41, end: 145 }],
				},
			}),
		).toMatchObject({ kind: "protein_selection" });
	});
});
```

- [ ] **Step 2: Run failing UI/API test**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/molstar-stage.test.tsx src/server/agent/contracts.test.ts
```

Expected: FAIL until stage and router support context references.

- [ ] **Step 3: Add Mol* selection callback**

Extend `MolstarViewerProps`:

```ts
type MolstarViewerProps = {
	artifactId: string | null;
	candidateId: string | null;
	label: string;
	onProteinSelection?: (selection: {
		artifactId: string;
		candidateId: string | null;
		label: string;
		selector: Record<string, unknown>;
	}) => void;
	url: string | null;
};
```

Inside plugin creation, subscribe to click/selection changes and convert loci into a compact selector:

```ts
plugin.behaviors.interaction.click.subscribe((event) => {
	if (!artifactId || !event.current?.loci) return;
	const loci = event.current.loci;
	const selector = {
		kind: loci.kind,
		raw: JSON.parse(JSON.stringify(loci, (_key, value) => (typeof value === "bigint" ? value.toString() : value))),
	};
	onProteinSelection?.({
		artifactId,
		candidateId,
		label,
		selector,
	});
});
```

- [ ] **Step 4: Add `createContextReference` router procedure**

```ts
createContextReference: protectedProcedure
	.input(z.object({
		artifactId: z.string().uuid().nullable(),
		candidateId: z.string().uuid().nullable(),
		kind: z.enum(["protein_selection", "artifact", "candidate", "literature", "note"]),
		label: z.string().min(1).max(160),
		selector: z.record(z.unknown()).default({}),
		workspaceId: z.string().uuid(),
	}))
	.mutation(async ({ ctx, input }) => {
		const workspace = await ctx.db.query.workspaces.findFirst({
			where: and(eq(workspaces.id, input.workspaceId), eq(workspaces.ownerId, ctx.session.user.id)),
		});
		if (!workspace) throw new TRPCError({ code: "NOT_FOUND", message: "Workspace not found." });
		const [reference] = await ctx.db.insert(contextReferences).values({
			artifactId: input.artifactId,
			candidateId: input.candidateId,
			createdById: ctx.session.user.id,
			kind: input.kind,
			label: input.label,
			selectorJson: input.selector,
			workspaceId: input.workspaceId,
		}).returning();
		return reference;
	});
```

- [ ] **Step 5: Implement `MolstarStage`**

`MolstarStage` owns viewer action buttons: fullscreen, download/export, reset camera, and settings. It passes selections from `MolstarViewer` to `createContextReference`.

- [ ] **Step 6: Run tests**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/molstar-stage.test.tsx src/server/agent/contracts.test.ts
bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/app/_components/molstar-viewer.tsx autopep/src/app/_components/molstar-stage.tsx autopep/src/app/_components/molstar-stage.test.tsx autopep/src/server/api/routers/workspace.ts autopep/src/server/agent/contracts.test.ts
git commit -m "feat: add molstar context references"
```

## Task 14: Journey Panel, Candidate Tree, Recipes, And Shell Composition

**Files:**
- Create: `autopep/src/app/_components/journey-panel.tsx`
- Create: `autopep/src/app/_components/recipe-manager.tsx`
- Create: `autopep/src/app/_components/workspace-rail.tsx`
- Replace: `autopep/src/app/_components/workspace-shell.tsx`
- Modify: `autopep/src/app/_components/autopep-workspace.tsx`
- Create component tests next to new components

- [ ] **Step 1: Write candidate tree test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JourneyPanel } from "./journey-panel";

describe("JourneyPanel", () => {
	it("shows one-loop candidate score leaves without a branch-again action", () => {
		render(
			<JourneyPanel
				activeRunStatus="completed"
				artifacts={[{ id: "artifact-1", kind: "pdb", name: "candidate-1.pdb" }]}
				candidateScores={[
					{ candidateId: "candidate-1", label: "likely_binder", scorer: "protein_interaction_aggregate", value: null, unit: null },
					{ candidateId: "candidate-1", label: null, scorer: "dscript", value: 0.74, unit: "probability" },
					{ candidateId: "candidate-1", label: null, scorer: "prodigy", value: -7.4, unit: "kcal/mol" },
				]}
				candidates={[{ id: "candidate-1", rank: 1, title: "Candidate 1" }]}
				objective="Generate a protein that binds to 3CL-protease"
			/>,
		);

		expect(screen.getByText("likely_binder")).toBeInTheDocument();
		expect(screen.getByText("D-SCRIPT 0.74")).toBeInTheDocument();
		expect(screen.getByText("PRODIGY -7.4 kcal/mol")).toBeInTheDocument();
		expect(screen.getByText("MVP loop complete")).toBeInTheDocument();
	});
});
```

- [ ] **Step 2: Run failing component tests**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/journey-panel.test.tsx src/app/_components/recipe-manager.test.tsx
```

Expected: FAIL until components exist.

- [ ] **Step 3: Implement `JourneyPanel`**

```tsx
"use client";

type Score = {
	candidateId: string;
	label: string | null;
	scorer: "dscript" | "prodigy" | "protein_interaction_aggregate" | string;
	unit: string | null;
	value: number | null;
};

export function JourneyPanel({
	activeRunStatus,
	candidateScores,
	candidates,
	objective,
}: {
	activeRunStatus: string | null;
	artifacts: { id: string; kind: string; name: string }[];
	candidateScores: Score[];
	candidates: { id: string; rank: number; title: string }[];
	objective: string;
}) {
	const scoreByCandidate = new Map<string, Score[]>();
	for (const score of candidateScores) {
		scoreByCandidate.set(score.candidateId, [...(scoreByCandidate.get(score.candidateId) ?? []), score]);
	}

	return (
		<aside className="min-h-0 overflow-y-auto border-[#e5e2d9] border-l bg-[#fbfaf6] p-4">
			<p className="font-semibold text-[#17211e] text-sm">Design journey</p>
			<p className="mt-1 text-[#68726c] text-xs">{objective}</p>
			<div className="mt-4 space-y-3">
				<Milestone done label="Understand target" />
				<Milestone done label="Find structures" />
				<Milestone done label="Prepare target" />
				<Milestone done={activeRunStatus === "completed"} label="Generate, fold, score" />
			</div>
			<div className="mt-5 space-y-3">
				{candidates.map((candidate) => {
					const scores = scoreByCandidate.get(candidate.id) ?? [];
					const aggregate = scores.find((score) => score.scorer === "protein_interaction_aggregate");
					const dscript = scores.find((score) => score.scorer === "dscript");
					const prodigy = scores.find((score) => score.scorer === "prodigy");
					return (
						<div className="rounded-md border border-[#ddd9cf] bg-[#fffef9] p-3" key={candidate.id}>
							<div className="flex items-center justify-between gap-2">
								<p className="font-medium text-sm">#{candidate.rank} {candidate.title}</p>
								{aggregate?.label ? <span className="rounded bg-[#eaf4cf] px-2 py-1 text-[#315419] text-xs">{aggregate.label}</span> : null}
							</div>
							{dscript?.value !== null && dscript?.value !== undefined ? <p className="mt-2 text-xs">D-SCRIPT {dscript.value}</p> : null}
							{prodigy?.value !== null && prodigy?.value !== undefined ? <p className="text-xs">PRODIGY {prodigy.value} {prodigy.unit}</p> : null}
						</div>
					);
				})}
			</div>
			<p className="mt-4 rounded-md bg-[#f0efe8] px-3 py-2 text-[#626c66] text-xs">MVP loop complete</p>
		</aside>
	);
}

function Milestone({ done, label }: { done: boolean; label: string }) {
	return <div className="flex items-center gap-2 text-sm"><span className={done ? "size-2 rounded-full bg-[#4b9a63]" : "size-2 rounded-full bg-[#c8c5ba]"} />{label}</div>;
}
```

- [ ] **Step 4: Implement recipes API and manager**

Use these recipe procedures:

```ts
const recipeInput = z.object({
	bodyMarkdown: z.string().min(1).max(20000),
	description: z.string().max(1000).nullable().optional(),
	enabledByDefault: z.boolean().default(false),
	name: z.string().min(1).max(120),
	workspaceId: z.string().uuid(),
});

listRecipes: protectedProcedure
	.input(z.object({ workspaceId: z.string().uuid() }))
	.query(async ({ ctx, input }) =>
		ctx.db.query.recipes.findMany({
			where: and(
				eq(recipes.workspaceId, input.workspaceId),
				eq(recipes.ownerId, ctx.session.user.id),
				isNull(recipes.archivedAt),
			),
			orderBy: [asc(recipes.name)],
		}),
	),

createRecipe: protectedProcedure.input(recipeInput).mutation(async ({ ctx, input }) => {
	const [recipe] = await ctx.db
		.insert(recipes)
		.values({
			bodyMarkdown: input.bodyMarkdown,
			description: input.description ?? null,
			enabledByDefault: input.enabledByDefault,
			name: input.name,
			ownerId: ctx.session.user.id,
			workspaceId: input.workspaceId,
		})
		.returning();
	if (!recipe) throw new TRPCError({ code: "INTERNAL_SERVER_ERROR", message: "Failed to create recipe." });
	const [version] = await ctx.db
		.insert(recipeVersions)
		.values({
			bodyMarkdown: input.bodyMarkdown,
			createdById: ctx.session.user.id,
			recipeId: recipe.id,
			version: 1,
		})
		.returning();
	return { recipe, version };
}),

updateRecipe: protectedProcedure
	.input(recipeInput.extend({ recipeId: z.string().uuid() }))
	.mutation(async ({ ctx, input }) => {
		const [recipe] = await ctx.db
			.update(recipes)
			.set({
				bodyMarkdown: input.bodyMarkdown,
				description: input.description ?? null,
				enabledByDefault: input.enabledByDefault,
				name: input.name,
			})
			.where(and(eq(recipes.id, input.recipeId), eq(recipes.ownerId, ctx.session.user.id)))
			.returning();
		if (!recipe) throw new TRPCError({ code: "NOT_FOUND", message: "Recipe not found." });
		const latest = await ctx.db.query.recipeVersions.findFirst({
			where: eq(recipeVersions.recipeId, recipe.id),
			orderBy: [desc(recipeVersions.version)],
		});
		const [version] = await ctx.db
			.insert(recipeVersions)
			.values({
				bodyMarkdown: input.bodyMarkdown,
				createdById: ctx.session.user.id,
				recipeId: recipe.id,
				version: (latest?.version ?? 0) + 1,
			})
			.returning();
		return { recipe, version };
	}),

archiveRecipe: protectedProcedure
	.input(z.object({ recipeId: z.string().uuid() }))
	.mutation(async ({ ctx, input }) => {
		const [recipe] = await ctx.db
			.update(recipes)
			.set({ archivedAt: new Date() })
			.where(and(eq(recipes.id, input.recipeId), eq(recipes.ownerId, ctx.session.user.id)))
			.returning();
		if (!recipe) throw new TRPCError({ code: "NOT_FOUND", message: "Recipe not found." });
		return recipe;
	}),
```

When `createMessageRunWithLaunch` receives selected `recipeRefs`, query the latest `recipeVersions` for those recipe IDs and insert `runRecipes` rows with `nameSnapshot` and `bodySnapshot`.

- [ ] **Step 5: Compose `WorkspaceShell`**

Replace the current crowded shell with a four-column desktop layout:

```tsx
<main className="grid h-[100dvh] grid-cols-[64px_minmax(320px,390px)_minmax(0,1fr)_minmax(280px,340px)] bg-[#f8f7f2] text-[#17211e]">
	<WorkspaceRail
		activeWorkspaceId={activeWorkspaceId}
		onCreateWorkspace={onCreateWorkspace}
		onSelectWorkspace={onSelectWorkspace}
		workspaces={workspaces}
	/>
	<ChatPanel
		contextReferences={contextReferences}
		events={events}
		isSending={isSending}
		messages={messages}
		onSend={onSendMessage}
		recipes={recipes}
	/>
	<MolstarStage
		artifact={selectedArtifact}
		candidate={selectedCandidate}
		onProteinSelection={onProteinSelection}
	/>
	<JourneyPanel
		activeRunStatus={activeRunStatus}
		artifacts={artifacts}
		candidateScores={candidateScores}
		candidates={candidates}
		objective={objective}
	/>
</main>
```

For mobile, use `grid-cols-1` and render the same component order: chat, viewer, journey.

- [ ] **Step 6: Run component tests**

Run:

```bash
cd autopep
bunx vitest run src/app/_components/journey-panel.test.tsx src/app/_components/recipe-manager.test.tsx src/app/_components/chat-panel.test.tsx
bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/app/_components/journey-panel.tsx autopep/src/app/_components/recipe-manager.tsx autopep/src/app/_components/workspace-rail.tsx autopep/src/app/_components/workspace-shell.tsx autopep/src/app/_components/autopep-workspace.tsx autopep/src/app/_components/*.test.tsx autopep/src/server/api/routers/workspace.ts
git commit -m "feat: compose autopep mvp workspace shell"
```

## Task 15: Deployed Production End-To-End Verification

**Production stance.** Autopep currently has zero users. It is explicitly fine to break production while developing this MVP — apply destructive migrations directly to production Neon, redeploy Modal whenever needed, force-deploy to Vercel, and roll forward. Do not invent staging environments, blue/green deploys, or backwards-compatibility shims to protect "users" who do not exist. Fix-forward is the correct posture for every step in this task.

**Account scoping.** Three Modal-hosted inference APIs (Proteina-Complexa, Chai-1, protein interaction scoring) live in a separate Modal account that this task cannot deploy or modify. They are reached purely via HTTPS using their `MODAL_*_URL` and `MODAL_*_API_KEY` pairs. The `autopep-agent-worker` Modal app is in the autopep-controllable account and is the only Modal deployment this task touches.

**Available tooling.** This task assumes the agent has the Neon MCP plugin, the Cloudflare MCP plugin, the Modal CLI logged into the autopep account, and either the Vercel CLI or Vercel MCP. Use the plugins to verify deployed state — do not rely on hopeful curl-and-grep alone.

This task is a **headless backend end-to-end** validation. The browser-use UI smoke is optional and only added at the end, because the demo's reliability depends on the backend pipeline (TS → Modal → SDK → endpoints → Neon/R2), not on Mol* or the Tailwind tree.

**Files:**
- Modify: `autopep/README.md`
- Modify: `autopep/.env.example`
- Create: `autopep/scripts/deployed-e2e-3clpro.ts`

- [ ] **Step 1: Pre-flight local checks**

Stop early if these fail. There is no point deploying broken code even when production is breakable.

```bash
cd autopep
bun run typecheck
bun run check
bun run test
PYTHONPATH=modal python3 -m pytest modal/tests -q
```

Re-run the three Task 11.5 smokes against the smoke environment and confirm they still pass:

```bash
bun run scripts/smoke-roundtrip.ts smoke_chat
bun run scripts/smoke-roundtrip.ts smoke_tool
bun run scripts/smoke-roundtrip.ts smoke_sandbox
```

Expected: all four checks plus all three smokes pass.

- [ ] **Step 2: Apply the destructive migration to production Neon**

Use the Neon MCP plugin to inspect and confirm production state at every step. Do not skip the verification reads — the migration is destructive and silently incorrect schemas have caused incidents before.

```bash
# 1. Identify the production project + branch via the Neon MCP plugin.
#    list_projects, then describe_branch on the production branch.

# 2. Capture the pre-migration table list for the diff record.
#    get_database_tables(project_id, branch_id) — paste the result into the commit message body.

# 3. Apply migrations against production DATABASE_URL.
DATABASE_URL=$AUTOPEP_PROD_DATABASE_URL bun run db:migrate

# 4. Verify the post-migration schema with the Neon MCP plugin:
#    describe_table_schema for autopep_workspace, autopep_thread, autopep_message,
#    autopep_agent_run, autopep_agent_event, autopep_artifact,
#    autopep_protein_candidate, autopep_model_inference, autopep_candidate_score,
#    autopep_context_reference, autopep_recipe, autopep_recipe_version,
#    autopep_run_recipe.
#    Also describe_table_schema for "user", "session", "account", "verification"
#    to confirm Better Auth tables survived.
```

Expected: 13 autopep tables exist with the columns specified in Task 2; 4 Better Auth tables remain unchanged. If anything is wrong, inspect with the Neon MCP plugin and correct directly — do not write a recovery migration unless schema drift is the only path forward.

- [ ] **Step 3: Verify Cloudflare R2 bucket and credentials**

Use the Cloudflare MCP plugin to confirm the production R2 bucket exists, is in the expected account, and that the `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` pair has read+write+delete on that bucket. Then exercise the path with a real upload:

```bash
# Through the Cloudflare MCP plugin: verify the bucket, list objects (should be empty
# or contain prior dev artifacts), and confirm the worker's IAM token scopes.

# Round-trip a tiny artifact through the production storage adapter to prove the
# Task 5 R2 client works against the real bucket:
cd autopep
bun run --silent -e '
  import { r2ArtifactStore } from "@/server/artifacts/r2";
  const key = `health-checks/${Date.now()}.txt`;
  await r2ArtifactStore.put({ key, body: Buffer.from("ok"), contentType: "text/plain" });
  console.log(await r2ArtifactStore.signedReadUrl({ key, ttlSeconds: 60 }));
'
```

Expected: the `put` succeeds and the signed URL fetches `ok`. Delete the test key afterwards via the Cloudflare MCP plugin.

- [ ] **Step 4: Deploy the autopep worker to Modal and verify inference endpoint health**

```bash
cd autopep

# Confirm we are on the autopep Modal account, not the inference account:
modal token current

# Deploy the worker.
modal deploy modal/autopep_worker.py

# Capture the new start-run URL printed by Modal. Update AUTOPEP_MODAL_START_URL
# everywhere it is set: local .env, Vercel project env, and any Modal Secret that
# embeds it.

# Confirm the deployed worker boots: hit the /health route exposed by the FastAPI
# app, or trigger a no-op Modal function call via `modal run` if the deployment
# does not expose /health.

# Confirm the three inference endpoints (in the OTHER, inaccessible Modal account)
# are reachable from this network:
curl -fsS -H "X-API-Key: $MODAL_PROTEINA_API_KEY" "$MODAL_PROTEINA_URL/health"
curl -fsS -H "X-API-Key: $MODAL_CHAI_API_KEY" "$MODAL_CHAI_URL/health"
curl -fsS -H "X-API-Key: $MODAL_PROTEIN_INTERACTION_SCORING_API_KEY" "$MODAL_PROTEIN_INTERACTION_SCORING_URL/health"
```

Expected: deployment succeeds, the worker `/health` (or no-op call) returns ok, and all three inference endpoints respond healthy. If an inference endpoint is down, this task is blocked — the inference account is not in scope to fix here, raise it out-of-band.

- [ ] **Step 5: Push env vars to Vercel and deploy the frontend**

```bash
# Required Vercel env vars for production. Set each via `vercel env add` or the
# Vercel MCP plugin. Do not let mismatched values silently leak into production.
#
#   DATABASE_URL                                  -> production Neon URL
#   BETTER_AUTH_SECRET                            -> existing prod secret
#   BETTER_AUTH_URL                               -> production app URL
#   OPENAI_API_KEY                                -> autopep-account OpenAI key
#   OPENAI_DEFAULT_MODEL                          -> gpt-5.5
#   AUTOPEP_RUNNER_BACKEND                        -> modal
#   AUTOPEP_MODAL_START_URL                       -> from Step 4
#   AUTOPEP_MODAL_WEBHOOK_SECRET                  -> from Modal Secret
#   R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET
#   MODAL_PROTEINA_URL / MODAL_PROTEINA_API_KEY
#   MODAL_CHAI_URL / MODAL_CHAI_API_KEY
#   MODAL_PROTEIN_INTERACTION_SCORING_URL / MODAL_PROTEIN_INTERACTION_SCORING_API_KEY

vercel deploy --prod

# After deploy: pull the live env back to confirm the deployed function actually
# sees what was set. The Vercel UI lies sometimes; the runtime is the truth.
vercel env pull .env.production.snapshot
diff <(grep -E '^[A-Z_]+=' .env.production.expected | sort) \
     <(grep -E '^[A-Z_]+=' .env.production.snapshot | sort) || true
rm -f .env.production.snapshot
```

Expected: a successful production deploy whose preview URL serves the workspace shell. No env variable is missing or mismatched. If the deploy errors during build, fix forward and redeploy. There is no rollback strategy — there is nobody to roll back for.

- [ ] **Step 6: Run the headless backend E2E against the deployed stack**

This is the real validation. Drive the demo prompt end-to-end against production Vercel + production Modal + production Neon + production R2 with `gpt-5.5`. No browser involved.

Create `autopep/scripts/deployed-e2e-3clpro.ts`:

```ts
// Run: AUTOPEP_PROD_API_BASE=https://<vercel-prod-url> \
//      AUTOPEP_PROD_SESSION_COOKIE='<value>' \
//      bun run autopep/scripts/deployed-e2e-3clpro.ts
//
// Drives the production Autopep API the same way the Next frontend would, but
// without any browser. Creates a workspace, sends the 3CL-protease prompt, polls
// agent_events through the public read API, and asserts the MVP loop completed
// with at least one ranked candidate and one candidate_score row.

const BASE = requireEnv("AUTOPEP_PROD_API_BASE");
const COOKIE = requireEnv("AUTOPEP_PROD_SESSION_COOKIE");
const PROMPT = "Generate a protein that binds to 3CL-protease.";
const DEADLINE_MS = 30 * 60 * 1000; // 30 minutes — Proteina + Chai + scoring is real work.
const POLL_MS = 5_000;

const workspace = await trpc("workspace.createWorkspace", {
  name: "Deployed E2E — 3CLpro",
});
const { run } = await trpc("workspace.sendMessage", {
  workspaceId: workspace.id,
  threadId: workspace.activeThreadId,
  prompt: PROMPT,
  taskKind: "research", // route to the real MVP agent, not a smoke kind
  recipeRefs: [],
  contextRefs: [],
});

// Poll cursor-based events until the run reaches a terminal status.
let cursor = 0;
const seenTypes = new Set<string>();
const start = Date.now();
let runRow: { status: string; errorSummary: string | null } = { status: "queued", errorSummary: null };
while (Date.now() - start < DEADLINE_MS) {
  const page = await trpc("workspace.getRunEvents", { runId: run.id, afterSequence: cursor });
  for (const event of page.events) {
    cursor = event.sequence;
    seenTypes.add(event.type);
    console.log(`[seq=${event.sequence}] ${event.type}: ${event.title}`);
  }
  runRow = await trpc("workspace.getRun", { runId: run.id });
  if (runRow.status === "completed" || runRow.status === "failed" || runRow.status === "cancelled") break;
  await sleep(POLL_MS);
}

const required = [
  "run_started",
  "tool_call_completed",       // at least one biology tool fired
  "artifact_created",          // at least one artifact landed in R2
  "candidate_ranked",          // candidates persisted
  "run_completed",
];
const missing = required.filter((type) => !seenTypes.has(type));

if (runRow.status !== "completed" || missing.length > 0) {
  console.error({ runStatus: runRow.status, errorSummary: runRow.errorSummary, missing });
  process.exit(1);
}

// Spot-check Neon directly via the Neon MCP plugin to confirm row counts:
//   - autopep_artifact has at least one row for this run_id (target CIF)
//   - autopep_protein_candidate has at least one row for this run_id
//   - autopep_model_inference has rows for proteina_complexa, chai_1,
//     protein_interaction_scoring
//   - autopep_candidate_score has at least one aggregate row with a non-null label
console.log("✓ Deployed E2E completed");
```

Then run it:

```bash
cd autopep
AUTOPEP_PROD_API_BASE=https://<vercel-prod-url> \
AUTOPEP_PROD_SESSION_COOKIE='<value>' \
bun run scripts/deployed-e2e-3clpro.ts
```

Expected: the run reaches `completed`, all five required event types appear at least once, and the Neon MCP spot-checks confirm artifacts, candidates, model_inferences, and candidate_scores rows. If the run fails, read the preserved events + `error_summary`, fix the underlying issue (in TS, in the worker, in env, wherever), redeploy whatever is needed, and re-run. Do not ship Task 15 without one fully successful run.

- [ ] **Step 7: Optional browser smoke + README + final commit**

Once Step 6 passes, do a single browser-use pass against the deployed Vercel URL to confirm the UI renders the same flow:

1. Open the Vercel production URL.
2. Sign in.
3. Open the workspace created in Step 6 (or a new one).
4. Send `Generate a protein that binds to 3CL-protease`.
5. Confirm chat events render through polling, Mol* loads a structure, the journey panel shows score leaves.

This is corroboration, not the source of truth. If Step 6 passes and the browser smoke shows a UI rendering glitch, treat it as a UI bug, not an E2E failure.

Update `autopep/README.md` with a `## Autopep MVP Runtime` section listing required runtime secrets and a `## Production runbook` section pointing at this task's steps, the Task 11.5 smokes, and the Neon/Cloudflare MCP plugins as the canonical inspection tools.

Required runtime secrets:

- `OPENAI_API_KEY`
- `OPENAI_DEFAULT_MODEL` (default `gpt-5.5`)
- `DATABASE_URL`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `AUTOPEP_MODAL_START_URL`
- `AUTOPEP_MODAL_WEBHOOK_SECRET`
- `MODAL_PROTEINA_URL`
- `MODAL_PROTEINA_API_KEY`
- `MODAL_CHAI_URL`
- `MODAL_CHAI_API_KEY`
- `MODAL_PROTEIN_INTERACTION_SCORING_URL`
- `MODAL_PROTEIN_INTERACTION_SCORING_API_KEY`

Final commit:

```bash
git add autopep/README.md autopep/.env.example autopep/scripts/deployed-e2e-3clpro.ts
git commit -m "docs: document autopep mvp runtime and deployed e2e"
```

## Self-Review Checklist

- Spec coverage: Tasks 1-4 cover contracts, schema, workspaces, messages, runs, events, and polling. Tasks 5-11 cover artifacts, Python Agents SDK runtime, Modal sandbox setup, Life Science Research context, Proteina, Chai, scoring, and one-loop persistence. Task 11.5 covers integration smoke roundtrips against a Neon branch and a smoke Modal app to surface integration drift before any frontend work. Tasks 12-14 cover unified chat, larger Mol* stage, context chips, compact journey, candidate tree, workspace navigation, and recipes. Task 15 covers a deployed production end-to-end pass: destructive migration to production Neon (with Neon MCP verification), Cloudflare R2 verification (with the Cloudflare MCP plugin), Modal worker deploy, Vercel env + production deploy, and a headless backend E2E driving the 3CL-protease prompt against the deployed stack with `gpt-5.5`. Production breakage is acceptable while there are no users.
- Model selection: Real demo runs use `gpt-5.5`. Smoke and CI runs use a `gpt-5.x-mini` (e.g. `gpt-5.5-mini`). Anthropic Haiku and other non-OpenAI models are not compatible with the worker.
- MVP boundary: The plan stops after one scored generation/folding batch and only preserves lineage for Phase 2 branching.
- Test stance: Default local tests mock OpenAI, Modal inference endpoints, RCSB, PubMed, bioRxiv, R2, and browser flows. Real endpoint calls are verification steps only.
- Security stance: Modal/OpenAI/R2 credentials remain server/worker-only. Browser code receives signed/public artifact URLs and database-backed display payloads only.
