# CIF Retrieval Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Autopep vertical slice: natural-language target request in, ranked structure candidates and a CIF/mmCIF artifact out, with progress visible in the deployed T3 app.

**Architecture:** The Vercel-hosted T3 app owns authenticated project/run creation and polling UI. Neon stores durable project, run, event, candidate, and artifact metadata. A separate worker claims queued runs, performs CIF retrieval/prep through structured service boundaries, uploads accepted CIF artifacts to Cloudflare R2, and writes progress back to Neon.

**Tech Stack:** Next.js 15 App Router, React 19, tRPC 11, Drizzle/Postgres, Better Auth, Cloudflare R2 through AWS SDK v3 S3 APIs, Mol*, Vitest, Bun.

---

## Scope Check

This plan implements one hackathon vertical slice from the approved spec. It does not implement Proteina Complexa inference, ProteinMPNN, Chai-1/Boltz scoring, or iterative mutation. Those systems will consume `protein_candidates` and `artifacts` after this slice produces a `prepared_cif` or validated `source_cif` artifact.

## File Structure

- Modify `autopep/package.json`: add test/worker scripts and runtime/dev dependencies.
- Create `autopep/vitest.config.ts`: Vitest configuration with the `@` alias.
- Create `autopep/src/test/setup.ts`: shared test setup.
- Modify `autopep/src/env.js`: add server-side R2 and worker configuration.
- Modify `autopep/src/server/db/schema.ts`: add Autopep project/run/event/entity/candidate/artifact tables.
- Modify `autopep/src/server/api/root.ts`: register the workspace router.
- Create `autopep/src/server/api/routers/workspace.ts`: project/run/artifact tRPC API.
- Create `autopep/src/server/agent/contracts.ts`: Zod contracts shared by worker, API, and tests.
- Create `autopep/src/server/agent/completion.ts`: pure completion validator.
- Create `autopep/src/server/agent/events.ts`: event append helper and event type constants.
- Create `autopep/src/server/agent/rcsb-client.ts`: RCSB search, metadata, and CIF download client.
- Create `autopep/src/server/agent/pubmed-client.ts`: minimal PubMed search client for literature evidence.
- Create `autopep/src/server/agent/retrieval-pipeline.ts`: deterministic retrieval pipeline that emits events and records candidates/artifacts.
- Create `autopep/src/server/agent/harness-client.ts`: subprocess adapter for the Codex harness contract.
- Create `autopep/src/server/artifacts/keys.ts`: deterministic R2 object key builder.
- Create `autopep/src/server/artifacts/r2.ts`: R2 upload and signed-read URL service.
- Create `autopep/workers/cif-retrieval-worker.ts`: external worker CLI that claims and executes runs.
- Replace `autopep/src/app/page.tsx`: workspace-first home screen.
- Create `autopep/src/app/_components/autopep-workspace.tsx`: client polling workspace.
- Create `autopep/src/app/_components/molstar-viewer.tsx`: isolated Mol* client component.
- Create `autopep/src/app/_components/workspace-shell.tsx`: presentational workspace layout.
- Create tests next to the new server files under `autopep/src/server/**`.

## Task 1: Dependencies And Test Harness

**Files:**
- Modify: `autopep/package.json`
- Create: `autopep/vitest.config.ts`
- Create: `autopep/src/test/setup.ts`

- [ ] **Step 1: Install dependencies**

Run:

```bash
cd autopep
bun add @aws-sdk/client-s3 @aws-sdk/s3-request-presigner @phosphor-icons/react molstar
bun add -d @testing-library/jest-dom @testing-library/react jsdom sass tsx vitest
```

Expected: `package.json` and `bun.lock` change.

- [ ] **Step 2: Add scripts to `autopep/package.json`**

Modify `scripts` so it includes these entries while keeping the existing scripts:

```json
{
	"test": "vitest run",
	"test:watch": "vitest",
	"worker:cif": "tsx workers/cif-retrieval-worker.ts"
}
```

Expected: `bun run test` is now a valid command.

- [ ] **Step 3: Create `autopep/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
	resolve: {
		alias: {
			"@": new URL("./src", import.meta.url).pathname,
		},
	},
	test: {
		environment: "node",
		globals: true,
		setupFiles: ["./src/test/setup.ts"],
		env: {
			BETTER_AUTH_SECRET: "test-secret",
			DATABASE_URL: "postgres://user:password@localhost:5432/autopep_test",
			NODE_ENV: "test",
			R2_ACCESS_KEY_ID: "test-access-key",
			R2_ACCOUNT_ID: "test-account",
			R2_BUCKET: "autopep-test",
			R2_SECRET_ACCESS_KEY: "test-secret-key",
		},
	},
});
```

- [ ] **Step 4: Create `autopep/src/test/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Verify the empty test harness**

Run:

```bash
cd autopep
bun run test
```

Expected: PASS with no tests found only if Vitest exits cleanly. If Vitest returns code 1 because no test files exist, continue after confirming the config is parsed without TypeScript or module errors.

- [ ] **Step 6: Commit**

```bash
git add autopep/package.json autopep/bun.lock autopep/vitest.config.ts autopep/src/test/setup.ts
git commit -m "test: add vitest harness"
```

## Task 2: Database Schema For Projects, Runs, Candidates, And Artifacts

**Files:**
- Modify: `autopep/src/server/db/schema.ts`
- Generated: `autopep/drizzle/*.sql`
- Generated: `autopep/drizzle/meta/*.json`

- [ ] **Step 1: Extend imports in `autopep/src/server/db/schema.ts`**

Replace the current first import with:

```ts
import { relations, sql } from "drizzle-orm";
```

Extend the `drizzle-orm/pg-core` import to include these names:

```ts
import {
	boolean,
	index,
	integer,
	jsonb,
	pgEnum,
	pgTable,
	pgTableCreator,
	real,
	text,
	timestamp,
	uuid,
} from "drizzle-orm/pg-core";
```

- [ ] **Step 2: Add Autopep table creator and enums after `createTable`**

```ts
export const createAutopepTable = pgTableCreator((name) => `autopep_${name}`);

export const agentRunStatus = pgEnum("agent_run_status", [
	"queued",
	"running",
	"succeeded",
	"failed",
	"canceled",
]);

export const artifactType = pgEnum("artifact_type", [
	"source_cif",
	"prepared_cif",
	"fasta",
	"raw_search_json",
	"report",
	"other",
]);
```

- [ ] **Step 3: Add domain tables after auth tables**

Append this block after `verification`:

```ts
export const projects = createAutopepTable(
	"project",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		ownerId: text("owner_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		goal: text("goal").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).$onUpdate(
			() => new Date(),
		),
	},
	(t) => [index("autopep_project_owner_idx").on(t.ownerId)],
);

export const agentRuns = createAutopepTable(
	"agent_run",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		prompt: text("prompt").notNull(),
		status: agentRunStatus("status").notNull().default("queued"),
		topK: integer("top_k").notNull().default(5),
		claimedBy: text("claimed_by"),
		claimedAt: timestamp("claimed_at", { withTimezone: true }),
		startedAt: timestamp("started_at", { withTimezone: true }),
		finishedAt: timestamp("finished_at", { withTimezone: true }),
		errorSummary: text("error_summary"),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).$onUpdate(
			() => new Date(),
		),
	},
	(t) => [
		index("autopep_agent_run_project_idx").on(t.projectId),
		index("autopep_agent_run_status_idx").on(t.status),
	],
);

export const agentEvents = createAutopepTable(
	"agent_event",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		sequence: integer("sequence").notNull(),
		type: text("type").notNull(),
		title: text("title").notNull(),
		detail: text("detail"),
		payloadJson: jsonb("payload_json")
			.$type<Record<string, unknown>>()
			.notNull()
			.default(sql`'{}'::jsonb`),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
	},
	(t) => [
		index("autopep_agent_event_run_idx").on(t.runId),
		index("autopep_agent_event_sequence_idx").on(t.runId, t.sequence),
	],
);

export const targetEntities = createAutopepTable(
	"target_entity",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		label: text("label").notNull(),
		aliasesJson: jsonb("aliases_json")
			.$type<string[]>()
			.notNull()
			.default(sql`'[]'::jsonb`),
		organism: text("organism"),
		sourceIdsJson: jsonb("source_ids_json")
			.$type<Record<string, string>>()
			.notNull()
			.default(sql`'{}'::jsonb`),
		confidence: real("confidence").notNull().default(0),
		notes: text("notes"),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
	},
	(t) => [index("autopep_target_entity_run_idx").on(t.runId)],
);

export const proteinCandidates = createAutopepTable(
	"protein_candidate",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		targetEntityId: uuid("target_entity_id").references(() => targetEntities.id, {
			onDelete: "set null",
		}),
		rank: integer("rank").notNull(),
		score: real("score").notNull(),
		rcsbEntryId: text("rcsb_entry_id").notNull(),
		title: text("title").notNull(),
		organism: text("organism"),
		experimentalMethod: text("experimental_method"),
		resolution: real("resolution"),
		chainsJson: jsonb("chains_json")
			.$type<Array<{ id: string; label?: string; residues?: string }>>()
			.notNull()
			.default(sql`'[]'::jsonb`),
		literatureRefsJson: jsonb("literature_refs_json")
			.$type<Array<{ id: string; title: string; url?: string }>>()
			.notNull()
			.default(sql`'[]'::jsonb`),
		whySelected: text("why_selected").notNull(),
		proteinaReady: boolean("proteina_ready").notNull().default(false),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true }).$onUpdate(
			() => new Date(),
		),
	},
	(t) => [
		index("autopep_candidate_run_idx").on(t.runId),
		index("autopep_candidate_rank_idx").on(t.runId, t.rank),
	],
);

export const artifacts = createAutopepTable(
	"artifact",
	{
		id: uuid("id").primaryKey().defaultRandom(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		candidateId: uuid("candidate_id").references(() => proteinCandidates.id, {
			onDelete: "set null",
		}),
		type: artifactType("type").notNull(),
		fileName: text("file_name").notNull(),
		mimeType: text("mime_type").notNull(),
		sizeBytes: integer("size_bytes").notNull(),
		checksum: text("checksum"),
		r2Bucket: text("r2_bucket").notNull(),
		r2Key: text("r2_key").notNull(),
		viewer: text("viewer").notNull().default("molstar"),
		viewerHintsJson: jsonb("viewer_hints_json")
			.$type<Record<string, unknown>>()
			.notNull()
			.default(sql`'{}'::jsonb`),
		createdAt: timestamp("created_at", { withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
	},
	(t) => [
		index("autopep_artifact_project_idx").on(t.projectId),
		index("autopep_artifact_run_idx").on(t.runId),
		index("autopep_artifact_candidate_idx").on(t.candidateId),
	],
);
```

- [ ] **Step 4: Add relations after existing relations**

```ts
export const projectRelations = relations(projects, ({ many, one }) => ({
	owner: one(user, { fields: [projects.ownerId], references: [user.id] }),
	runs: many(agentRuns),
	artifacts: many(artifacts),
}));

export const agentRunRelations = relations(agentRuns, ({ many, one }) => ({
	project: one(projects, {
		fields: [agentRuns.projectId],
		references: [projects.id],
	}),
	createdBy: one(user, {
		fields: [agentRuns.createdById],
		references: [user.id],
	}),
	events: many(agentEvents),
	targetEntities: many(targetEntities),
	candidates: many(proteinCandidates),
	artifacts: many(artifacts),
}));

export const agentEventRelations = relations(agentEvents, ({ one }) => ({
	run: one(agentRuns, {
		fields: [agentEvents.runId],
		references: [agentRuns.id],
	}),
}));

export const targetEntityRelations = relations(targetEntities, ({ many, one }) => ({
	run: one(agentRuns, {
		fields: [targetEntities.runId],
		references: [agentRuns.id],
	}),
	candidates: many(proteinCandidates),
}));

export const proteinCandidateRelations = relations(
	proteinCandidates,
	({ many, one }) => ({
		run: one(agentRuns, {
			fields: [proteinCandidates.runId],
			references: [agentRuns.id],
		}),
		targetEntity: one(targetEntities, {
			fields: [proteinCandidates.targetEntityId],
			references: [targetEntities.id],
		}),
		artifacts: many(artifacts),
	}),
);

export const artifactRelations = relations(artifacts, ({ one }) => ({
	project: one(projects, {
		fields: [artifacts.projectId],
		references: [projects.id],
	}),
	run: one(agentRuns, {
		fields: [artifacts.runId],
		references: [agentRuns.id],
	}),
	candidate: one(proteinCandidates, {
		fields: [artifacts.candidateId],
		references: [proteinCandidates.id],
	}),
}));
```

- [ ] **Step 5: Generate migration**

Run:

```bash
cd autopep
bun run db:generate
```

Expected: a new SQL migration appears under `autopep/drizzle/` and includes `autopep_project`, `autopep_agent_run`, `autopep_agent_event`, `autopep_target_entity`, `autopep_protein_candidate`, and `autopep_artifact`.

- [ ] **Step 6: Verify schema compiles**

Run:

```bash
cd autopep
bun run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autopep/src/server/db/schema.ts autopep/drizzle
git commit -m "feat: add retrieval workspace schema"
```

## Task 3: Pure Contracts, Artifact Keys, And Completion Validation

**Files:**
- Create: `autopep/src/server/agent/contracts.ts`
- Create: `autopep/src/server/agent/completion.ts`
- Create: `autopep/src/server/artifacts/keys.ts`
- Test: `autopep/src/server/agent/completion.test.ts`
- Test: `autopep/src/server/artifacts/keys.test.ts`

- [ ] **Step 1: Write failing tests for artifact keys**

Create `autopep/src/server/artifacts/keys.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildArtifactKey } from "./keys";

describe("buildArtifactKey", () => {
	it("builds deterministic project/run/candidate keys", () => {
		expect(
			buildArtifactKey({
				projectId: "project-1",
				runId: "run-1",
				candidateId: "candidate-1",
				type: "prepared_cif",
				fileName: "6m0j-rbd.cif",
			}),
		).toBe("projects/project-1/runs/run-1/candidates/candidate-1/prepared_cif/6m0j-rbd.cif");
	});

	it("sanitizes file names and supports run-level artifacts", () => {
		expect(
			buildArtifactKey({
				projectId: "project-1",
				runId: "run-1",
				type: "raw_search_json",
				fileName: "RCSB search results.json",
			}),
		).toBe("projects/project-1/runs/run-1/run-artifacts/raw_search_json/rcsb-search-results.json");
	});
});
```

- [ ] **Step 2: Run the artifact key test to verify failure**

Run:

```bash
cd autopep
bun run test src/server/artifacts/keys.test.ts
```

Expected: FAIL because `./keys` does not exist.

- [ ] **Step 3: Create `autopep/src/server/artifacts/keys.ts`**

```ts
type ArtifactKeyInput = {
	projectId: string;
	runId: string;
	candidateId?: string | null;
	type: string;
	fileName: string;
};

const sanitizeSegment = (value: string) =>
	value
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "");

export const buildArtifactKey = (input: ArtifactKeyInput) => {
	const fileName = sanitizeSegment(input.fileName);
	const type = sanitizeSegment(input.type);

	if (input.candidateId) {
		return [
			"projects",
			input.projectId,
			"runs",
			input.runId,
			"candidates",
			input.candidateId,
			type,
			fileName,
		].join("/");
	}

	return [
		"projects",
		input.projectId,
		"runs",
		input.runId,
		"run-artifacts",
		type,
		fileName,
	].join("/");
};
```

- [ ] **Step 4: Write failing tests for completion validation**

Create `autopep/src/server/agent/completion.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { validateRunCompletion } from "./completion";

describe("validateRunCompletion", () => {
	it("accepts a proteina-ready candidate with a linked CIF artifact", () => {
		const result = validateRunCompletion({
			candidates: [
				{
					id: "candidate-1",
					rank: 1,
					proteinaReady: true,
				},
			],
			artifacts: [
				{
					id: "artifact-1",
					candidateId: "candidate-1",
					type: "prepared_cif",
				},
			],
		});

		expect(result.ok).toBe(true);
		expect(result.selectedCandidateId).toBe("candidate-1");
		expect(result.selectedArtifactId).toBe("artifact-1");
	});

	it("rejects runs without a proteina-ready CIF artifact", () => {
		const result = validateRunCompletion({
			candidates: [
				{
					id: "candidate-1",
					rank: 1,
					proteinaReady: true,
				},
			],
			artifacts: [
				{
					id: "artifact-1",
					candidateId: "candidate-1",
					type: "fasta",
				},
			],
		});

		expect(result.ok).toBe(false);
		expect(result.reason).toBe("No proteina-ready CIF artifact is linked to the selected candidate.");
	});
});
```

- [ ] **Step 5: Create `autopep/src/server/agent/contracts.ts`**

```ts
import { z } from "zod";

export const agentEventTypeSchema = z.enum([
	"normalizing_target",
	"searching_structures",
	"searching_literature",
	"ranking_candidates",
	"downloading_cif",
	"preparing_cif",
	"uploading_artifact",
	"ready_for_proteina",
	"source_failed",
	"run_failed",
]);

export type AgentEventType = z.infer<typeof agentEventTypeSchema>;

export const artifactTypeSchema = z.enum([
	"source_cif",
	"prepared_cif",
	"fasta",
	"raw_search_json",
	"report",
	"other",
]);

export type ArtifactType = z.infer<typeof artifactTypeSchema>;

export const targetEntitySchema = z.object({
	label: z.string().min(1),
	aliases: z.array(z.string()).default([]),
	organism: z.string().nullable().default(null),
	sourceIds: z.record(z.string()).default({}),
	confidence: z.number().min(0).max(1),
	notes: z.string().nullable().default(null),
});

export const rankedCandidateSchema = z.object({
	rcsbEntryId: z.string().min(4),
	title: z.string().min(1),
	organism: z.string().nullable().default(null),
	experimentalMethod: z.string().nullable().default(null),
	resolution: z.number().nullable().default(null),
	chains: z.array(
		z.object({
			id: z.string().min(1),
			label: z.string().optional(),
			residues: z.string().optional(),
		}),
	),
	literatureRefs: z.array(
		z.object({
			id: z.string().min(1),
			title: z.string().min(1),
			url: z.string().url().optional(),
		}),
	),
	score: z.number().min(0).max(1),
	whySelected: z.string().min(1),
});

export type RankedCandidate = z.infer<typeof rankedCandidateSchema>;
export type TargetEntity = z.infer<typeof targetEntitySchema>;
```

- [ ] **Step 6: Create `autopep/src/server/agent/completion.ts`**

```ts
type CompletionCandidate = {
	id: string;
	rank: number;
	proteinaReady: boolean;
};

type CompletionArtifact = {
	id: string;
	candidateId: string | null;
	type: string;
};

type CompletionInput = {
	candidates: CompletionCandidate[];
	artifacts: CompletionArtifact[];
};

type CompletionResult =
	| {
			ok: true;
			selectedCandidateId: string;
			selectedArtifactId: string;
	  }
	| {
			ok: false;
			reason: string;
	  };

const cifArtifactTypes = new Set(["prepared_cif", "source_cif"]);

export const validateRunCompletion = (
	input: CompletionInput,
): CompletionResult => {
	const selected = [...input.candidates]
		.filter((candidate) => candidate.proteinaReady)
		.sort((a, b) => a.rank - b.rank)[0];

	if (!selected) {
		return {
			ok: false,
			reason: "No proteina-ready candidate exists.",
		};
	}

	const artifact = input.artifacts.find(
		(item) =>
			item.candidateId === selected.id && cifArtifactTypes.has(item.type),
	);

	if (!artifact) {
		return {
			ok: false,
			reason:
				"No proteina-ready CIF artifact is linked to the selected candidate.",
		};
	}

	return {
		ok: true,
		selectedArtifactId: artifact.id,
		selectedCandidateId: selected.id,
	};
};
```

- [ ] **Step 7: Run pure tests**

Run:

```bash
cd autopep
bun run test src/server/artifacts/keys.test.ts src/server/agent/completion.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add autopep/src/server/artifacts/keys.ts autopep/src/server/artifacts/keys.test.ts autopep/src/server/agent/contracts.ts autopep/src/server/agent/completion.ts autopep/src/server/agent/completion.test.ts
git commit -m "feat: add retrieval contracts"
```

## Task 4: R2 Artifact Storage Service

**Files:**
- Modify: `autopep/src/env.js`
- Create: `autopep/src/server/artifacts/r2.ts`
- Test: `autopep/src/server/artifacts/r2.test.ts`

- [ ] **Step 1: Add R2 env vars to `autopep/src/env.js`**

In the `server` block, add:

```ts
R2_ACCESS_KEY_ID:
	process.env.NODE_ENV === "production"
		? z.string()
		: z.string().default("local-access-key"),
R2_ACCOUNT_ID:
	process.env.NODE_ENV === "production"
		? z.string()
		: z.string().default("local-account"),
R2_BUCKET:
	process.env.NODE_ENV === "production"
		? z.string()
		: z.string().default("autopep-local"),
R2_PUBLIC_BASE_URL: z.string().url().optional(),
R2_SECRET_ACCESS_KEY:
	process.env.NODE_ENV === "production"
		? z.string()
		: z.string().default("local-secret-key"),
AUTOPEP_AGENT_MODE: z.enum(["direct", "codex"]).default("direct"),
AUTOPEP_CODEX_COMMAND: z.string().optional(),
```

In `runtimeEnv`, add:

```ts
R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID,
R2_ACCOUNT_ID: process.env.R2_ACCOUNT_ID,
R2_BUCKET: process.env.R2_BUCKET,
R2_PUBLIC_BASE_URL: process.env.R2_PUBLIC_BASE_URL,
R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY,
AUTOPEP_AGENT_MODE: process.env.AUTOPEP_AGENT_MODE,
AUTOPEP_CODEX_COMMAND: process.env.AUTOPEP_CODEX_COMMAND,
```

- [ ] **Step 2: Write failing R2 service tests**

Create `autopep/src/server/artifacts/r2.test.ts`:

```ts
import { PutObjectCommand } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";

import { createR2ArtifactStore } from "./r2";

describe("createR2ArtifactStore", () => {
	it("uploads bytes with the configured bucket and content type", async () => {
		const send = vi.fn().mockResolvedValue({});
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: { send },
			getSignedUrl: vi.fn(),
		});

		await store.upload({
			body: Buffer.from("data_6m0j"),
			contentType: "chemical/x-cif",
			key: "projects/project-1/runs/run-1/source_cif/6m0j.cif",
		});

		expect(send).toHaveBeenCalledTimes(1);
		const command = send.mock.calls[0]?.[0];
		expect(command).toBeInstanceOf(PutObjectCommand);
		expect(command.input).toMatchObject({
			Bucket: "autopep-test",
			ContentType: "chemical/x-cif",
			Key: "projects/project-1/runs/run-1/source_cif/6m0j.cif",
		});
	});

	it("creates signed read URLs", async () => {
		const getSignedUrl = vi.fn().mockResolvedValue("https://signed.example/6m0j");
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: { send: vi.fn() },
			getSignedUrl,
		});

		const url = await store.getReadUrl({
			key: "projects/project-1/runs/run-1/source_cif/6m0j.cif",
		});

		expect(url).toBe("https://signed.example/6m0j");
		expect(getSignedUrl).toHaveBeenCalledWith(
			expect.anything(),
			expect.objectContaining({ expiresIn: 900 }),
		);
	});
});
```

- [ ] **Step 3: Create `autopep/src/server/artifacts/r2.ts`**

```ts
import {
	GetObjectCommand,
	PutObjectCommand,
	S3Client,
	type S3ClientConfig,
} from "@aws-sdk/client-s3";
import { getSignedUrl as getAwsSignedUrl } from "@aws-sdk/s3-request-presigner";

import { env } from "@/env";

type MinimalS3Client = {
	send(command: PutObjectCommand | GetObjectCommand): Promise<unknown>;
};

type ArtifactStoreConfig = {
	bucket: string;
	client: MinimalS3Client;
	getSignedUrl: (
		command: GetObjectCommand,
		options: { expiresIn: number },
	) => Promise<string>;
};

type UploadInput = {
	key: string;
	body: Buffer | Uint8Array | string;
	contentType: string;
};

type ReadUrlInput = {
	key: string;
	expiresInSeconds?: number;
};

export const createR2Client = () => {
	const config: S3ClientConfig = {
		credentials: {
			accessKeyId: env.R2_ACCESS_KEY_ID,
			secretAccessKey: env.R2_SECRET_ACCESS_KEY,
		},
		endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
		region: "auto",
	};

	return new S3Client(config);
};

export const createR2ArtifactStore = (config: ArtifactStoreConfig) => ({
	async upload(input: UploadInput) {
		await config.client.send(
			new PutObjectCommand({
				Body: input.body,
				Bucket: config.bucket,
				ContentType: input.contentType,
				Key: input.key,
			}),
		);
	},

	async getReadUrl(input: ReadUrlInput) {
		return config.getSignedUrl(
			new GetObjectCommand({
				Bucket: config.bucket,
				Key: input.key,
			}),
			{ expiresIn: input.expiresInSeconds ?? 900 },
		);
	},
});

export const r2ArtifactStore = createR2ArtifactStore({
	bucket: env.R2_BUCKET,
	client: createR2Client(),
	getSignedUrl: (command, options) =>
		getAwsSignedUrl(createR2Client(), command, options),
});
```

- [ ] **Step 4: Run R2 tests**

Run:

```bash
cd autopep
bun run test src/server/artifacts/r2.test.ts
```

Expected: PASS.

- [ ] **Step 5: Run typecheck**

Run:

```bash
cd autopep
bun run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add autopep/src/env.js autopep/src/server/artifacts/r2.ts autopep/src/server/artifacts/r2.test.ts
git commit -m "feat: add r2 artifact store"
```

## Task 5: Workspace tRPC API

**Files:**
- Create: `autopep/src/server/api/routers/workspace.ts`
- Modify: `autopep/src/server/api/root.ts`

- [ ] **Step 1: Create `autopep/src/server/api/routers/workspace.ts`**

```ts
import { and, asc, desc, eq, gt } from "drizzle-orm";
import { z } from "zod";

import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import {
	agentEvents,
	agentRuns,
	artifacts,
	proteinCandidates,
	projects,
	targetEntities,
} from "@/server/db/schema";

export const workspaceRouter = createTRPCRouter({
	createProjectRun: protectedProcedure
		.input(
			z.object({
				goal: z.string().min(3),
				name: z.string().min(1).max(120).optional(),
				topK: z.number().int().min(1).max(10).default(5),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			const [project] = await ctx.db
				.insert(projects)
				.values({
					goal: input.goal,
					name: input.name ?? input.goal.slice(0, 80),
					ownerId: ctx.session.user.id,
				})
				.returning();

			if (!project) {
				throw new Error("Failed to create project.");
			}

			const [run] = await ctx.db
				.insert(agentRuns)
				.values({
					createdById: ctx.session.user.id,
					projectId: project.id,
					prompt: input.goal,
					topK: input.topK,
				})
				.returning();

			if (!run) {
				throw new Error("Failed to create agent run.");
			}

			return { project, run };
		}),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const [project] = await ctx.db
			.select()
			.from(projects)
			.where(eq(projects.ownerId, ctx.session.user.id))
			.orderBy(desc(projects.createdAt))
			.limit(1);

		if (!project) return null;

		return getWorkspacePayload(ctx.db, project.id, ctx.session.user.id);
	}),

	getWorkspace: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			return getWorkspacePayload(ctx.db, input.projectId, ctx.session.user.id);
		}),

	getRunEvents: protectedProcedure
		.input(
			z.object({
				runId: z.string().uuid(),
				afterSequence: z.number().int().min(0).default(0),
			}),
		)
		.query(async ({ ctx, input }) => {
			const [run] = await ctx.db
				.select({ projectId: agentRuns.projectId })
				.from(agentRuns)
				.innerJoin(projects, eq(projects.id, agentRuns.projectId))
				.where(
					and(
						eq(agentRuns.id, input.runId),
						eq(projects.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!run) return [];

			return ctx.db
				.select()
				.from(agentEvents)
				.where(
					and(
						eq(agentEvents.runId, input.runId),
						gt(agentEvents.sequence, input.afterSequence),
					),
				)
				.orderBy(asc(agentEvents.sequence));
	}),
});

type DbClient = typeof import("@/server/db").db;

async function getWorkspacePayload(
	db: DbClient,
	projectId: string,
	ownerId: string,
) {
	const [project] = await db
		.select()
		.from(projects)
		.where(and(eq(projects.id, projectId), eq(projects.ownerId, ownerId)))
		.limit(1);

	if (!project) return null;

	const runs = await db
		.select()
		.from(agentRuns)
		.where(eq(agentRuns.projectId, project.id))
		.orderBy(desc(agentRuns.createdAt))
		.limit(10);

	const activeRun = runs[0] ?? null;

	if (!activeRun) {
		return {
			activeRun: null,
			artifacts: [],
			candidates: [],
			events: [],
			project,
			runs,
			targetEntities: [],
		};
	}

	const [events, targetEntityRows, candidateRows, artifactRows] =
		await Promise.all([
			db
				.select()
				.from(agentEvents)
				.where(eq(agentEvents.runId, activeRun.id))
				.orderBy(asc(agentEvents.sequence)),
			db
				.select()
				.from(targetEntities)
				.where(eq(targetEntities.runId, activeRun.id)),
			db
				.select()
				.from(proteinCandidates)
				.where(eq(proteinCandidates.runId, activeRun.id))
				.orderBy(asc(proteinCandidates.rank)),
			db
				.select()
				.from(artifacts)
				.where(eq(artifacts.runId, activeRun.id))
				.orderBy(desc(artifacts.createdAt)),
		]);

	const artifactRowsWithUrls = await Promise.all(
		artifactRows.map(async (artifact) => ({
			...artifact,
			signedUrl: await r2ArtifactStore.getReadUrl({ key: artifact.r2Key }),
		})),
	);

	return {
		activeRun,
		artifacts: artifactRowsWithUrls,
		candidates: candidateRows,
		events,
		project,
		runs,
		targetEntities: targetEntityRows,
	};
}
```

- [ ] **Step 2: Register the router in `autopep/src/server/api/root.ts`**

```ts
import { workspaceRouter } from "@/server/api/routers/workspace";
```

Change `appRouter` to:

```ts
export const appRouter = createTRPCRouter({
	post: postRouter,
	workspace: workspaceRouter,
});
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd autopep
bun run typecheck
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/src/server/api/root.ts autopep/src/server/api/routers/workspace.ts
git commit -m "feat: add workspace api"
```

## Task 6: RCSB, PubMed, And Retrieval Pipeline Services

**Files:**
- Create: `autopep/src/server/agent/events.ts`
- Create: `autopep/src/server/agent/rcsb-client.ts`
- Create: `autopep/src/server/agent/pubmed-client.ts`
- Create: `autopep/src/server/agent/retrieval-pipeline.ts`
- Test: `autopep/src/server/agent/rcsb-client.test.ts`
- Test: `autopep/src/server/agent/pubmed-client.test.ts`

- [ ] **Step 1: Create `autopep/src/server/agent/events.ts`**

```ts
import { desc, eq } from "drizzle-orm";

import type { AgentEventType } from "@/server/agent/contracts";
import { agentEvents } from "@/server/db/schema";

export type AppendRunEventInput = {
	db: typeof import("@/server/db").db;
	runId: string;
	type: AgentEventType;
	title: string;
	detail?: string;
	payload?: Record<string, unknown>;
};

export async function appendRunEvent(input: AppendRunEventInput) {
	const [latest] = await input.db
		.select({ sequence: agentEvents.sequence })
		.from(agentEvents)
		.where(eq(agentEvents.runId, input.runId))
		.orderBy(desc(agentEvents.sequence))
		.limit(1);

	const sequence = (latest?.sequence ?? 0) + 1;

	const [event] = await input.db
		.insert(agentEvents)
		.values({
			detail: input.detail,
			payloadJson: input.payload ?? {},
			runId: input.runId,
			sequence,
			title: input.title,
			type: input.type,
		})
		.returning();

	if (!event) {
		throw new Error("Failed to append run event.");
	}

	return event;
}
```

- [ ] **Step 2: Write failing RCSB client tests**

Create `autopep/src/server/agent/rcsb-client.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { downloadRcsbCif, searchRcsbEntries } from "./rcsb-client";

describe("rcsb-client", () => {
	it("searches RCSB entries", async () => {
		const fetchImpl = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({
				result_set: [{ identifier: "6M0J" }, { identifier: "2DUC" }],
			}),
		});

		const result = await searchRcsbEntries({
			fetchImpl,
			query: "SARS-CoV-2 spike RBD",
			rows: 2,
		});

		expect(result).toEqual(["6M0J", "2DUC"]);
		expect(fetchImpl).toHaveBeenCalledWith(
			"https://search.rcsb.org/rcsbsearch/v2/query",
			expect.objectContaining({ method: "POST" }),
		);
	});

	it("downloads CIF text", async () => {
		const fetchImpl = vi.fn().mockResolvedValue({
			ok: true,
			text: async () => "data_6M0J\n#",
		});

		const cif = await downloadRcsbCif({ entryId: "6M0J", fetchImpl });

		expect(cif).toBe("data_6M0J\n#");
		expect(fetchImpl).toHaveBeenCalledWith(
			"https://files.rcsb.org/download/6M0J.cif",
		);
	});
});
```

- [ ] **Step 3: Create `autopep/src/server/agent/rcsb-client.ts`**

```ts
type Fetch = typeof fetch;

export async function searchRcsbEntries(input: {
	query: string;
	rows: number;
	fetchImpl?: Fetch;
}) {
	const fetcher = input.fetchImpl ?? fetch;
	const response = await fetcher("https://search.rcsb.org/rcsbsearch/v2/query", {
		body: JSON.stringify({
			query: {
				parameters: { value: input.query },
				service: "full_text",
				type: "terminal",
			},
			request_options: {
				pager: { rows: input.rows, start: 0 },
			},
			return_type: "entry",
		}),
		headers: { "content-type": "application/json" },
		method: "POST",
	});

	if (!response.ok) {
		throw new Error(`RCSB search failed with status ${response.status}`);
	}

	const body = (await response.json()) as {
		result_set?: Array<{ identifier?: string }>;
	};

	return (body.result_set ?? [])
		.map((item) => item.identifier)
		.filter((identifier): identifier is string => Boolean(identifier));
}

export async function downloadRcsbCif(input: {
	entryId: string;
	fetchImpl?: Fetch;
}) {
	const fetcher = input.fetchImpl ?? fetch;
	const entryId = input.entryId.toUpperCase();
	const response = await fetcher(
		`https://files.rcsb.org/download/${entryId}.cif`,
	);

	if (!response.ok) {
		throw new Error(`RCSB CIF download failed with status ${response.status}`);
	}

	const cif = await response.text();
	if (!cif.includes(`data_${entryId}`) && !cif.startsWith("data_")) {
		throw new Error(`Downloaded CIF for ${entryId} did not include a data block.`);
	}

	return cif;
}
```

- [ ] **Step 4: Write failing PubMed client test**

Create `autopep/src/server/agent/pubmed-client.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { searchPubMed } from "./pubmed-client";

describe("searchPubMed", () => {
	it("returns PubMed references from ESearch", async () => {
		const fetchImpl = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({
				esearchresult: {
					idlist: ["32225176", "32225175"],
				},
			}),
		});

		const refs = await searchPubMed({
			fetchImpl,
			query: "SARS-CoV-2 spike RBD structure",
			retmax: 2,
		});

		expect(refs).toEqual([
			{
				id: "32225176",
				title: "PubMed result 32225176",
				url: "https://pubmed.ncbi.nlm.nih.gov/32225176/",
			},
			{
				id: "32225175",
				title: "PubMed result 32225175",
				url: "https://pubmed.ncbi.nlm.nih.gov/32225175/",
			},
		]);
	});
});
```

- [ ] **Step 5: Create `autopep/src/server/agent/pubmed-client.ts`**

```ts
type Fetch = typeof fetch;

export async function searchPubMed(input: {
	query: string;
	retmax: number;
	fetchImpl?: Fetch;
}) {
	const fetcher = input.fetchImpl ?? fetch;
	const params = new URLSearchParams({
		db: "pubmed",
		retmax: String(input.retmax),
		retmode: "json",
		term: input.query,
	});

	const response = await fetcher(
		`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?${params}`,
	);

	if (!response.ok) {
		throw new Error(`PubMed search failed with status ${response.status}`);
	}

	const body = (await response.json()) as {
		esearchresult?: { idlist?: string[] };
	};

	return (body.esearchresult?.idlist ?? []).map((id) => ({
		id,
		title: `PubMed result ${id}`,
		url: `https://pubmed.ncbi.nlm.nih.gov/${id}/`,
	}));
}
```

- [ ] **Step 6: Create `autopep/src/server/agent/retrieval-pipeline.ts`**

```ts
import { eq } from "drizzle-orm";

import { appendRunEvent } from "@/server/agent/events";
import { downloadRcsbCif, searchRcsbEntries } from "@/server/agent/rcsb-client";
import { searchPubMed } from "@/server/agent/pubmed-client";
import { buildArtifactKey } from "@/server/artifacts/keys";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import {
	agentRuns,
	artifacts,
	proteinCandidates,
	targetEntities,
} from "@/server/db/schema";
import { env } from "@/env";

export async function runCifRetrievalPipeline(input: {
	db: typeof import("@/server/db").db;
	runId: string;
	fetchImpl?: typeof fetch;
}) {
	const [run] = await input.db
		.select()
		.from(agentRuns)
		.where(eq(agentRuns.id, input.runId))
		.limit(1);

	if (!run) {
		throw new Error(`Run ${input.runId} was not found.`);
	}

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Normalizing target",
		type: "normalizing_target",
		payload: { prompt: run.prompt },
	});

	const [targetEntity] = await input.db
		.insert(targetEntities)
		.values({
			aliasesJson: inferAliases(run.prompt),
			confidence: 0.78,
			label: inferTargetLabel(run.prompt),
			notes: "Initial target normalization from user prompt.",
			organism: inferOrganism(run.prompt),
			runId: run.id,
			sourceIdsJson: {},
		})
		.returning();

	if (!targetEntity) {
		throw new Error("Failed to create target entity.");
	}

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Searching Protein Data Bank",
		type: "searching_structures",
		payload: { query: targetEntity.label },
	});

	const entryIds = await searchRcsbEntries({
		fetchImpl: input.fetchImpl,
		query: targetEntity.label,
		rows: run.topK,
	});

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Searching literature",
		type: "searching_literature",
		payload: { query: `${targetEntity.label} structure` },
	});

	const literatureRefs = await searchPubMed({
		fetchImpl: input.fetchImpl,
		query: `${targetEntity.label} structure`,
		retmax: 3,
	});

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Ranking candidate structures",
		type: "ranking_candidates",
		payload: { entryIds },
	});

	const candidates = await input.db
		.insert(proteinCandidates)
		.values(
			entryIds.map((entryId, index) => ({
				chainsJson: [],
				experimentalMethod: null,
				literatureRefsJson: literatureRefs,
				organism: targetEntity.organism,
				proteinaReady: index === 0,
				rank: index + 1,
				rcsbEntryId: entryId,
				resolution: null,
				runId: run.id,
				score: Math.max(0.1, 0.95 - index * 0.08),
				targetEntityId: targetEntity.id,
				title: `${entryId} candidate structure for ${targetEntity.label}`,
				whySelected:
					index === 0
						? `Selected ${entryId} as the top structure candidate for ${targetEntity.label} because it ranked first in RCSB full-text search and has supporting literature context.`
						: `Kept ${entryId} as a backup structure candidate for comparison.`,
			})),
		)
		.returning();

	const topCandidate = candidates[0];
	if (!topCandidate) {
		throw new Error("RCSB search returned no candidate structures.");
	}

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: `Downloading ${topCandidate.rcsbEntryId} CIF`,
		type: "downloading_cif",
		payload: { rcsbEntryId: topCandidate.rcsbEntryId },
	});

	const cif = await downloadRcsbCif({
		entryId: topCandidate.rcsbEntryId,
		fetchImpl: input.fetchImpl,
	});

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Uploading CIF artifact",
		type: "uploading_artifact",
		payload: { candidateId: topCandidate.id },
	});

	const fileName = `${topCandidate.rcsbEntryId.toLowerCase()}-source.cif`;
	const r2Key = buildArtifactKey({
		candidateId: topCandidate.id,
		fileName,
		projectId: run.projectId,
		runId: run.id,
		type: "source_cif",
	});

	await r2ArtifactStore.upload({
		body: Buffer.from(cif),
		contentType: "chemical/x-cif",
		key: r2Key,
	});

	const [artifact] = await input.db
		.insert(artifacts)
		.values({
			candidateId: topCandidate.id,
			fileName,
			mimeType: "chemical/x-cif",
			projectId: run.projectId,
			r2Bucket: env.R2_BUCKET,
			r2Key,
			runId: run.id,
			sizeBytes: Buffer.byteLength(cif),
			type: "source_cif",
			viewer: "molstar",
			viewerHintsJson: { format: "mmcif", rcsbEntryId: topCandidate.rcsbEntryId },
		})
		.returning();

	if (!artifact) {
		throw new Error("Failed to create artifact row.");
	}

	await appendRunEvent({
		db: input.db,
		runId: run.id,
		title: "Ready for Proteina",
		type: "ready_for_proteina",
		payload: {
			artifactId: artifact.id,
			candidateId: topCandidate.id,
			rcsbEntryId: topCandidate.rcsbEntryId,
		},
	});

	await input.db
		.update(agentRuns)
		.set({ finishedAt: new Date(), status: "succeeded" })
		.where(eq(agentRuns.id, run.id));
}

function inferTargetLabel(prompt: string) {
	const lower = prompt.toLowerCase();
	if (lower.includes("3cl") || lower.includes("protease")) {
		return "SARS-CoV-2 3CL protease";
	}
	if (lower.includes("spike") || lower.includes("rbd")) {
		return "SARS-CoV-2 spike receptor binding domain";
	}
	return prompt.replace(/^generate (a )?(protein|binder) to bind to /i, "").trim();
}

function inferAliases(prompt: string) {
	const lower = prompt.toLowerCase();
	if (lower.includes("3cl")) return ["3CLpro", "main protease", "Mpro"];
	if (lower.includes("rbd")) return ["RBD", "spike receptor binding domain"];
	return [];
}

function inferOrganism(prompt: string) {
	return prompt.toLowerCase().includes("sars") ? "SARS-CoV-2" : null;
}
```

- [ ] **Step 7: Run service tests**

Run:

```bash
cd autopep
bun run test src/server/agent/rcsb-client.test.ts src/server/agent/pubmed-client.test.ts
```

Expected: PASS.

- [ ] **Step 8: Run typecheck**

Run:

```bash
cd autopep
bun run typecheck
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add autopep/src/server/agent/events.ts autopep/src/server/agent/rcsb-client.ts autopep/src/server/agent/pubmed-client.ts autopep/src/server/agent/retrieval-pipeline.ts autopep/src/server/agent/rcsb-client.test.ts autopep/src/server/agent/pubmed-client.test.ts
git commit -m "feat: add cif retrieval pipeline"
```

## Task 7: External Worker CLI

**Files:**
- Create: `autopep/src/server/agent/harness-client.ts`
- Create: `autopep/workers/cif-retrieval-worker.ts`

- [ ] **Step 1: Create `autopep/src/server/agent/harness-client.ts`**

```ts
import { spawn } from "node:child_process";

import { env } from "@/env";

type CodexHarnessInput = {
	runId: string;
	projectId: string;
	prompt: string;
	topK: number;
};

export async function runCodexHarness(input: CodexHarnessInput) {
	if (!env.AUTOPEP_CODEX_COMMAND) {
		throw new Error(
			"AUTOPEP_CODEX_COMMAND must be set when AUTOPEP_AGENT_MODE=codex.",
		);
	}

	const payload = JSON.stringify(input);
	const child = spawn(env.AUTOPEP_CODEX_COMMAND, {
		env: {
			...process.env,
			AUTOPEP_HARNESS_INPUT: payload,
			AUTOPEP_PROJECT_ID: input.projectId,
			AUTOPEP_PROMPT: input.prompt,
			AUTOPEP_RUN_ID: input.runId,
			AUTOPEP_TOP_K: String(input.topK),
		},
		shell: true,
		stdio: ["ignore", "pipe", "pipe"],
	});

	let stdout = "";
	let stderr = "";

	child.stdout.on("data", (chunk) => {
		stdout += String(chunk);
	});

	child.stderr.on("data", (chunk) => {
		stderr += String(chunk);
	});

	const exitCode = await new Promise<number | null>((resolve, reject) => {
		child.on("error", reject);
		child.on("close", resolve);
	});

	if (exitCode !== 0) {
		throw new Error(
			`Codex harness failed with exit code ${exitCode}. ${stderr || stdout}`,
		);
	}

	return { stdout, stderr };
}
```

- [ ] **Step 2: Create `autopep/workers/cif-retrieval-worker.ts`**

```ts
import { asc, eq } from "drizzle-orm";

import { env } from "@/env";
import { runCodexHarness } from "@/server/agent/harness-client";
import { runCifRetrievalPipeline } from "@/server/agent/retrieval-pipeline";
import { db } from "@/server/db";
import { agentRuns } from "@/server/db/schema";

const workerId = process.env.AUTOPEP_WORKER_ID ?? `worker-${process.pid}`;
const once = process.argv.includes("--once");

async function claimNextRun() {
	const [run] = await db
		.select()
		.from(agentRuns)
		.where(eq(agentRuns.status, "queued"))
		.orderBy(asc(agentRuns.createdAt))
		.limit(1);

	if (!run) return null;

	const [claimed] = await db
		.update(agentRuns)
		.set({
			claimedAt: new Date(),
			claimedBy: workerId,
			startedAt: new Date(),
			status: "running",
		})
		.where(eq(agentRuns.id, run.id))
		.returning();

	return claimed ?? null;
}

async function runOnce() {
	const run = await claimNextRun();
	if (!run) {
		console.log("No queued runs.");
		return false;
	}

	console.log(`Claimed run ${run.id}`);

	try {
		if (env.AUTOPEP_AGENT_MODE === "codex") {
			await runCodexHarness({
				projectId: run.projectId,
				prompt: run.prompt,
				runId: run.id,
				topK: run.topK,
			});
		} else {
			await runCifRetrievalPipeline({ db, runId: run.id });
		}
		console.log(`Completed run ${run.id}`);
		return true;
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		await db
			.update(agentRuns)
			.set({
				errorSummary: message,
				finishedAt: new Date(),
				status: "failed",
			})
			.where(eq(agentRuns.id, run.id));
		console.error(`Failed run ${run.id}: ${message}`);
		return false;
	}
}

async function main() {
	if (once) {
		await runOnce();
		return;
	}

	for (;;) {
		const claimed = await runOnce();
		await new Promise((resolve) => setTimeout(resolve, claimed ? 500 : 3000));
	}
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd autopep
bun run typecheck
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add autopep/src/server/agent/harness-client.ts autopep/workers/cif-retrieval-worker.ts autopep/package.json
git commit -m "feat: add cif retrieval worker"
```

## Task 8: Workspace UI And Mol* Viewer

**Files:**
- Replace: `autopep/src/app/page.tsx`
- Create: `autopep/src/app/_components/autopep-workspace.tsx`
- Create: `autopep/src/app/_components/molstar-viewer.tsx`
- Create: `autopep/src/app/_components/workspace-shell.tsx`
- Modify: `autopep/src/app/layout.tsx`
- Modify: `autopep/src/styles/globals.css`

- [ ] **Step 1: Update app metadata in `autopep/src/app/layout.tsx`**

Add this import after the existing globals import:

```ts
import "molstar/lib/mol-plugin-ui/skin/light.scss";
```

Replace `metadata` with:

```ts
export const metadata: Metadata = {
	title: "Autopep",
	description: "A molecular studio for agentic protein design.",
	icons: [{ rel: "icon", url: "/favicon.ico" }],
};
```

- [ ] **Step 2: Create `autopep/src/app/_components/molstar-viewer.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { createPluginUI } from "molstar/lib/mol-plugin-ui";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { renderReact18 } from "molstar/lib/mol-plugin-ui/react18";

type MolstarViewerProps = {
	url: string | null;
	label: string;
};

export function MolstarViewer({ label, url }: MolstarViewerProps) {
	const containerRef = useRef<HTMLDivElement>(null);
	const pluginRef = useRef<PluginUIContext | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let disposed = false;

		async function init() {
			if (!containerRef.current || pluginRef.current) return;

			const plugin = await createPluginUI({
				render: renderReact18,
				spec: {
					layout: {
						initial: {
							isExpanded: false,
							showControls: true,
						},
					},
				},
				target: containerRef.current,
			});

			if (disposed) {
				plugin.dispose();
				return;
			}

			pluginRef.current = plugin;
		}

		init().catch((cause: unknown) => {
			setError(cause instanceof Error ? cause.message : String(cause));
		});

		return () => {
			disposed = true;
			pluginRef.current?.dispose();
			pluginRef.current = null;
		};
	}, []);

	useEffect(() => {
		async function loadStructure() {
			if (!url || !pluginRef.current) return;
			setError(null);
			await pluginRef.current.clear();
			const data = await pluginRef.current.builders.data.download({ url });
			const trajectory =
				await pluginRef.current.builders.structure.parseTrajectory(
					data,
					"mmcif",
				);
			await pluginRef.current.builders.structure.hierarchy.applyPreset(
				trajectory,
				"default",
			);
		}

		loadStructure().catch((cause: unknown) => {
			setError(cause instanceof Error ? cause.message : String(cause));
		});
	}, [url]);

	if (!url) {
		return (
			<div className="flex h-full min-h-[520px] items-center justify-center border border-zinc-200 bg-[#f4f2ed] text-zinc-500">
				<div className="max-w-sm text-center">
					<p className="font-medium text-zinc-800">No CIF loaded</p>
					<p className="mt-2 text-sm">
						Start a retrieval run and the selected structure will appear here.
					</p>
				</div>
			</div>
		);
	}

	return (
		<div className="relative h-full min-h-[520px] overflow-hidden border border-zinc-200 bg-white">
			<div className="absolute top-3 left-3 z-[1] rounded-full border border-zinc-200 bg-white/90 px-3 py-1 text-xs text-zinc-700">
				{label}
			</div>
			<div className="absolute inset-0" ref={containerRef} />
			{error && (
				<div className="absolute right-4 bottom-4 left-4 border border-red-200 bg-red-50 p-3 text-sm text-red-800">
					Mol* could not load this CIF: {error}
				</div>
			)}
		</div>
	);
}
```

- [ ] **Step 3: Create `autopep/src/app/_components/workspace-shell.tsx`**

```tsx
import { ArrowClockwise, Flask, Folder, Play } from "@phosphor-icons/react";

type WorkspaceShellProps = {
	artifactLabel: string;
	candidates: Array<{
		id: string;
		rank: number;
		rcsbEntryId: string;
		score: number;
		whySelected: string;
		proteinaReady: boolean;
	}>;
	children: React.ReactNode;
	events: Array<{
		id: string;
		sequence: number;
		title: string;
		detail: string | null;
		type: string;
	}>;
	onRefresh: () => void;
	onStartExample: (goal: string) => void;
	runStatus: string | null;
};

export function WorkspaceShell(props: WorkspaceShellProps) {
	return (
		<main className="min-h-[100dvh] bg-[#f7f5ef] text-zinc-950">
			<div className="mx-auto grid min-h-[100dvh] max-w-[1500px] grid-cols-1 gap-0 px-4 py-4 lg:grid-cols-[340px_minmax(0,1fr)_360px]">
				<aside className="border-zinc-200 border-r bg-[#fbfaf6] p-5">
					<div className="flex items-center gap-3">
						<div className="flex size-9 items-center justify-center border border-zinc-300 bg-white">
							<Flask size={18} weight="duotone" />
						</div>
						<div>
							<p className="font-semibold">Autopep</p>
							<p className="text-xs text-zinc-500">Molecular studio</p>
						</div>
					</div>

					<div className="mt-8 space-y-3">
						<button
							className="w-full border border-zinc-900 bg-zinc-950 px-4 py-3 text-left text-sm text-white transition active:translate-y-[1px]"
							onClick={() =>
								props.onStartExample(
									"Generate a protein to bind to SARS-CoV-2 spike RBD",
								)
							}
							type="button"
						>
							<Play className="mr-2 inline" size={15} />
							Start spike RBD retrieval
						</button>
						<button
							className="w-full border border-zinc-300 bg-white px-4 py-3 text-left text-sm transition hover:border-zinc-500 active:translate-y-[1px]"
							onClick={() =>
								props.onStartExample(
									"Generate a protein to bind to 3CL-protease",
								)
							}
							type="button"
						>
							<Play className="mr-2 inline" size={15} />
							Start 3CL-protease retrieval
						</button>
					</div>

					<div className="mt-8 border-zinc-200 border-t pt-5">
						<div className="flex items-center justify-between">
							<p className="text-sm font-medium">Run status</p>
							<button
								aria-label="Refresh workspace"
								className="border border-zinc-200 bg-white p-2 transition hover:border-zinc-500 active:translate-y-[1px]"
								onClick={props.onRefresh}
								type="button"
							>
								<ArrowClockwise size={14} />
							</button>
						</div>
						<p className="mt-3 font-mono text-sm text-zinc-600">
							{props.runStatus ?? "no-run"}
						</p>
					</div>

					<div className="mt-8 border-zinc-200 border-t pt-5">
						<p className="flex items-center gap-2 text-sm font-medium">
							<Folder size={15} />
							Selected artifact
						</p>
						<p className="mt-3 break-all text-sm text-zinc-600">
							{props.artifactLabel}
						</p>
					</div>
				</aside>

				<section className="min-w-0 bg-white p-4 lg:p-6">{props.children}</section>

				<aside className="border-zinc-200 border-l bg-[#fbfaf6] p-5">
					<section>
						<p className="text-sm font-medium">Ranked structures</p>
						<div className="mt-4 space-y-3">
							{props.candidates.length === 0 ? (
								<p className="text-sm text-zinc-500">
									Candidates will appear after the worker ranks RCSB results.
								</p>
							) : (
								props.candidates.map((candidate) => (
									<div
										className="border border-zinc-200 bg-white p-3"
										key={candidate.id}
									>
										<div className="flex items-center justify-between">
											<p className="font-mono text-sm">
												#{candidate.rank} {candidate.rcsbEntryId}
											</p>
											<p className="font-mono text-xs text-zinc-500">
												{Math.round(candidate.score * 100)}%
											</p>
										</div>
										<p className="mt-2 text-xs leading-relaxed text-zinc-600">
											{candidate.whySelected}
										</p>
										{candidate.proteinaReady && (
											<p className="mt-2 text-xs font-medium text-emerald-700">
												Proteina-ready CIF
											</p>
										)}
									</div>
								))
							)}
						</div>
					</section>

					<section className="mt-8 border-zinc-200 border-t pt-5">
						<p className="text-sm font-medium">Research trace</p>
						<div className="mt-4 space-y-3">
							{props.events.length === 0 ? (
								<p className="text-sm text-zinc-500">
									The agent trace will appear here as the worker writes events.
								</p>
							) : (
								props.events.map((event) => (
									<div className="border-zinc-200 border-l pl-3" key={event.id}>
										<p className="font-medium text-sm">{event.title}</p>
										<p className="mt-1 font-mono text-[11px] text-zinc-500">
											{event.sequence.toString().padStart(2, "0")} / {event.type}
										</p>
										{event.detail && (
											<p className="mt-1 text-xs text-zinc-600">{event.detail}</p>
										)}
									</div>
								))
							)}
						</div>
					</section>
				</aside>
			</div>
		</main>
	);
}
```

- [ ] **Step 4: Create `autopep/src/app/_components/autopep-workspace.tsx`**

```tsx
"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { api } from "@/trpc/react";
import { WorkspaceShell } from "./workspace-shell";

const MolstarViewer = dynamic(
	() => import("./molstar-viewer").then((mod) => mod.MolstarViewer),
	{ ssr: false },
);

export function AutopepWorkspace() {
	const utils = api.useUtils();
	const workspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: (query) => {
			const status = query.state.data?.activeRun?.status;
			return status === "queued" || status === "running" ? 2000 : false;
		},
	});

	const createRun = api.workspace.createProjectRun.useMutation({
		onSuccess: async () => {
			await utils.workspace.getLatestWorkspace.invalidate();
		},
	});

	const selectedArtifact = useMemo(() => {
		const artifacts = workspace.data?.artifacts ?? [];
		return (
			artifacts.find((artifact) => artifact.type === "prepared_cif") ??
			artifacts.find((artifact) => artifact.type === "source_cif") ??
			null
		);
	}, [workspace.data?.artifacts]);

	return (
		<WorkspaceShell
			artifactLabel={selectedArtifact?.fileName ?? "No CIF artifact yet"}
			candidates={(workspace.data?.candidates ?? []).map((candidate) => ({
				id: candidate.id,
				proteinaReady: candidate.proteinaReady,
				rank: candidate.rank,
				rcsbEntryId: candidate.rcsbEntryId,
				score: candidate.score,
				whySelected: candidate.whySelected,
			}))}
			events={(workspace.data?.events ?? []).map((event) => ({
				detail: event.detail,
				id: event.id,
				sequence: event.sequence,
				title: event.title,
				type: event.type,
			}))}
			onRefresh={() => {
				void workspace.refetch();
			}}
			onStartExample={(goal) => {
				createRun.mutate({ goal, topK: 5 });
			}}
			runStatus={workspace.data?.activeRun?.status ?? null}
		>
			<MolstarViewer
				label={selectedArtifact?.fileName ?? "Awaiting CIF"}
				url={selectedArtifact?.signedUrl ?? null}
			/>
		</WorkspaceShell>
	);
}
```

- [ ] **Step 5: Replace `autopep/src/app/page.tsx`**

```tsx
import { AuthCard } from "@/app/_components/auth-card";
import { AutopepWorkspace } from "@/app/_components/autopep-workspace";
import { getSession } from "@/server/better-auth/server";
import { HydrateClient } from "@/trpc/server";

export default async function Home() {
	const session = await getSession();

	if (!session) {
		return (
			<main className="flex min-h-[100dvh] items-center justify-center bg-[#f7f5ef] px-4 text-zinc-950">
				<div className="w-full max-w-md border border-zinc-800 bg-zinc-950 p-6 text-white">
					<p className="mb-6 text-sm text-zinc-300">
						Sign in to open your Autopep molecular studio.
					</p>
					<AuthCard />
				</div>
			</main>
		);
	}

	return (
		<HydrateClient>
			<AutopepWorkspace />
		</HydrateClient>
	);
}
```

- [ ] **Step 6: Update `autopep/src/styles/globals.css`**

Replace the current `@theme` block with:

```css
@theme {
	--font-sans:
		var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
}

body {
	background: #f7f5ef;
}
```

- [ ] **Step 7: Run checks**

Run:

```bash
cd autopep
bun run typecheck
bun run check
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add autopep/src/app/page.tsx autopep/src/app/layout.tsx autopep/src/app/_components/autopep-workspace.tsx autopep/src/app/_components/molstar-viewer.tsx autopep/src/app/_components/workspace-shell.tsx autopep/src/styles/globals.css
git commit -m "feat: add molecular workspace ui"
```

## Task 9: End-To-End Smoke Verification

**Files:**
- Modify only files required by failed verification.

- [ ] **Step 1: Apply database migration locally**

Run:

```bash
cd autopep
bun run db:migrate
```

Expected: migration succeeds against the configured Neon/Postgres database.

- [ ] **Step 2: Start the web app**

Run:

```bash
cd autopep
bun run dev
```

Expected: Next.js starts on `http://localhost:3000` or prints the next available port.

- [ ] **Step 3: Create a run from the UI**

In the browser:

1. Sign in if required.
2. Click `Start spike RBD retrieval`.
3. Confirm the run status changes to `queued`.

Expected: the workspace shows a run status and an empty trace before the worker starts.

- [ ] **Step 4: Run the worker once**

In a second terminal:

```bash
cd autopep
bun run worker:cif -- --once
```

Expected: terminal prints `Claimed run <id>` and then `Completed run <id>`.

- [ ] **Step 5: Verify the UI updates**

In the browser:

1. Confirm the trace includes normalization, structure search, literature search, ranking, CIF download, upload, and ready events.
2. Confirm at least one ranked structure candidate appears.
3. Confirm a CIF artifact label appears in the left rail.
4. Confirm Mol* attempts to load the signed CIF URL.

Expected: run status is `succeeded`, the top candidate is marked Proteina-ready, and the molecular stage is no longer empty.

- [ ] **Step 6: Run final automated checks**

Run:

```bash
cd autopep
bun run test
bun run typecheck
bun run check
bun run build
```

Expected: all commands PASS.

- [ ] **Step 7: Commit fixes from smoke verification**

If verification required fixes, commit them:

```bash
git add autopep
git commit -m "fix: complete cif retrieval smoke path"
```

If no fixes were required, record the clean result in the final implementation handoff instead of creating an empty commit.

## Implementation Notes

- R2 credentials must exist in Vercel and the worker runtime: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET`.
- For local testing, set the same variables in `autopep/.env`.
- CIF/mmCIF is the universal structure artifact format. New code should use `source_cif` and `prepared_cif`, not legacy structure-file artifact names.
- The first worker is intentionally simple. It claims one queued run at a time and writes durable state to Neon so the UI can poll.
- The Codex harness can replace the deterministic `runCifRetrievalPipeline` internals behind the same event/candidate/artifact contracts without changing the T3 UI.
