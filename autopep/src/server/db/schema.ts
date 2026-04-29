import { relations, sql } from "drizzle-orm";
import {
	type AnyPgColumn,
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
	unique,
	uuid,
} from "drizzle-orm/pg-core";

export const createTable = pgTableCreator((name) => `pg-drizzle_${name}`);

export const createAutopepTable = pgTableCreator((name) => `autopep_${name}`);

export const posts = createTable(
	"post",
	(d) => ({
		id: d.integer().primaryKey().generatedByDefaultAsIdentity(),
		name: d.varchar({ length: 256 }),
		createdById: d
			.varchar({ length: 255 })
			.notNull()
			.references(() => user.id),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: d.timestamp({ withTimezone: true }).$onUpdate(() => new Date()),
	}),
	(t) => [
		index("created_by_idx").on(t.createdById),
		index("name_idx").on(t.name),
	],
);

export const user = pgTable("user", {
	id: text("id").primaryKey(),
	name: text("name").notNull(),
	email: text("email").notNull().unique(),
	emailVerified: boolean("email_verified")
		.$defaultFn(() => false)
		.notNull(),
	image: text("image"),
	createdAt: timestamp("created_at")
		.$defaultFn(() => /* @__PURE__ */ new Date())
		.notNull(),
	updatedAt: timestamp("updated_at")
		.$defaultFn(() => /* @__PURE__ */ new Date())
		.notNull(),
});

export const session = pgTable("session", {
	id: text("id").primaryKey(),
	expiresAt: timestamp("expires_at").notNull(),
	token: text("token").notNull().unique(),
	createdAt: timestamp("created_at").notNull(),
	updatedAt: timestamp("updated_at").notNull(),
	ipAddress: text("ip_address"),
	userAgent: text("user_agent"),
	userId: text("user_id")
		.notNull()
		.references(() => user.id, { onDelete: "cascade" }),
});

export const account = pgTable("account", {
	id: text("id").primaryKey(),
	accountId: text("account_id").notNull(),
	providerId: text("provider_id").notNull(),
	userId: text("user_id")
		.notNull()
		.references(() => user.id, { onDelete: "cascade" }),
	accessToken: text("access_token"),
	refreshToken: text("refresh_token"),
	idToken: text("id_token"),
	accessTokenExpiresAt: timestamp("access_token_expires_at"),
	refreshTokenExpiresAt: timestamp("refresh_token_expires_at"),
	scope: text("scope"),
	password: text("password"),
	createdAt: timestamp("created_at").notNull(),
	updatedAt: timestamp("updated_at").notNull(),
});

export const verification = pgTable("verification", {
	id: text("id").primaryKey(),
	identifier: text("identifier").notNull(),
	value: text("value").notNull(),
	expiresAt: timestamp("expires_at").notNull(),
	createdAt: timestamp("created_at").$defaultFn(
		() => /* @__PURE__ */ new Date(),
	),
	updatedAt: timestamp("updated_at").$defaultFn(
		() => /* @__PURE__ */ new Date(),
	),
});

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
		ownerId: text("owner_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		description: text("description"),
		activeThreadId: uuid("active_thread_id").references(
			(): AnyPgColumn => threads.id,
			{ onDelete: "set null" },
		),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true })
			.defaultNow()
			.$onUpdate(() => new Date())
			.notNull(),
		archivedAt: timestamp("archived_at", { withTimezone: true }),
	},
	(t) => [index("autopep_workspace_owner_idx").on(t.ownerId)],
);

export const threads = createAutopepTable(
	"thread",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		title: text("title").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true })
			.defaultNow()
			.$onUpdate(() => new Date())
			.notNull(),
	},
	(t) => [index("autopep_thread_workspace_idx").on(t.workspaceId)],
);

export const messages = createAutopepTable(
	"message",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		threadId: uuid("thread_id")
			.notNull()
			.references(() => threads.id, { onDelete: "cascade" }),
		runId: uuid("run_id").references(() => agentRuns.id, {
			onDelete: "set null",
		}),
		role: text("role", { enum: ["user", "assistant", "system"] }).notNull(),
		content: text("content").notNull(),
		contextRefsJson: jsonb("context_refs_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		recipeRefsJson: jsonb("recipe_refs_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		attachmentRefsJson: jsonb("attachment_refs_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [index("autopep_message_thread_idx").on(t.threadId)],
);

export const agentRuns = createAutopepTable(
	"agent_run",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		threadId: uuid("thread_id")
			.notNull()
			.references(() => threads.id, { onDelete: "cascade" }),
		parentRunId: uuid("parent_run_id").references(
			(): AnyPgColumn => agentRuns.id,
			{ onDelete: "set null" },
		),
		rootRunId: uuid("root_run_id").references((): AnyPgColumn => agentRuns.id, {
			onDelete: "set null",
		}),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		status: agentRunStatus("status").default("queued").notNull(),
		taskKind: agentTaskKind("task_kind").default("chat").notNull(),
		prompt: text("prompt").notNull(),
		model: text("model").notNull().default("gpt-5.4"),
		agentName: text("agent_name").notNull().default("Autopep"),
		modalCallId: text("modal_call_id"),
		sandboxSessionStateJson: jsonb("sandbox_session_state_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		sdkStateJson: jsonb("sdk_state_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		lastResponseId: text("last_response_id"),
		startedAt: timestamp("started_at", { withTimezone: true }),
		finishedAt: timestamp("finished_at", { withTimezone: true }),
		errorSummary: text("error_summary"),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true })
			.defaultNow()
			.$onUpdate(() => new Date())
			.notNull(),
	},
	(t) => [
		index("autopep_agent_run_workspace_idx").on(t.workspaceId),
		index("autopep_agent_run_thread_idx").on(t.threadId),
		index("autopep_agent_run_status_idx").on(t.status),
	],
);

export const agentEvents = createAutopepTable(
	"agent_event",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		sequence: integer("sequence").notNull(),
		type: text("type").notNull(),
		title: text("title").notNull(),
		summary: text("summary"),
		displayJson: jsonb("display_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		rawJson: jsonb("raw_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
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
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id").references(() => agentRuns.id, {
			onDelete: "set null",
		}),
		sourceArtifactId: uuid("source_artifact_id").references(
			(): AnyPgColumn => artifacts.id,
			{ onDelete: "set null" },
		),
		kind: artifactKind("kind").notNull(),
		name: text("name").notNull(),
		storageProvider: text("storage_provider").notNull().default("r2"),
		storageKey: text("storage_key").notNull(),
		contentType: text("content_type").notNull(),
		sizeBytes: integer("size_bytes").notNull(),
		sha256: text("sha256"),
		metadataJson: jsonb("metadata_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
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
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		parentCandidateId: uuid("parent_candidate_id").references(
			(): AnyPgColumn => proteinCandidates.id,
			{ onDelete: "set null" },
		),
		rank: integer("rank").notNull(),
		source: text("source", {
			enum: [
				"rcsb_pdb",
				"alphafold",
				"proteina_complexa",
				"chai_1",
				"generated",
				"uploaded",
				"mutated",
			],
		}).notNull(),
		structureId: text("structure_id"),
		chainIdsJson: jsonb("chain_ids_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		sequence: text("sequence"),
		title: text("title").notNull(),
		scoreJson: jsonb("score_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		whySelected: text("why_selected"),
		artifactId: uuid("artifact_id").references(() => artifacts.id, {
			onDelete: "set null",
		}),
		foldArtifactId: uuid("fold_artifact_id").references(() => artifacts.id, {
			onDelete: "set null",
		}),
		parentInferenceId: uuid("parent_inference_id").references(
			(): AnyPgColumn => modelInferences.id,
			{ onDelete: "set null" },
		),
		metadataJson: jsonb("metadata_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
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
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		parentInferenceId: uuid("parent_inference_id").references(
			(): AnyPgColumn => modelInferences.id,
			{ onDelete: "set null" },
		),
		provider: text("provider").notNull().default("modal"),
		modelName: text("model_name", {
			enum: [
				"proteina_complexa",
				"chai_1",
				"protein_interaction_scoring",
				"future_scorer",
			],
		}).notNull(),
		status: agentRunStatus("status").default("queued").notNull(),
		endpointUrlSnapshot: text("endpoint_url_snapshot"),
		requestJson: jsonb("request_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		responseJson: jsonb("response_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		externalRequestId: text("external_request_id"),
		startedAt: timestamp("started_at", { withTimezone: true }),
		finishedAt: timestamp("finished_at", { withTimezone: true }),
		errorSummary: text("error_summary"),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
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
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		candidateId: uuid("candidate_id")
			.notNull()
			.references(() => proteinCandidates.id, { onDelete: "cascade" }),
		modelInferenceId: uuid("model_inference_id").references(
			() => modelInferences.id,
			{ onDelete: "set null" },
		),
		scorer: text("scorer", {
			enum: [
				"dscript",
				"prodigy",
				"protein_interaction_aggregate",
				"future_scorer",
			],
		}).notNull(),
		status: text("status", {
			enum: ["ok", "partial", "failed", "unavailable"],
		}).notNull(),
		label: text("label"),
		value: real("value"),
		unit: text("unit"),
		valuesJson: jsonb("values_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		warningsJson: jsonb("warnings_json")
			.$type<unknown[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		errorsJson: jsonb("errors_json")
			.$type<unknown[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
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
		workspaceId: uuid("workspace_id")
			.notNull()
			.references(() => workspaces.id, { onDelete: "cascade" }),
		artifactId: uuid("artifact_id").references(() => artifacts.id, {
			onDelete: "set null",
		}),
		candidateId: uuid("candidate_id").references(() => proteinCandidates.id, {
			onDelete: "set null",
		}),
		kind: text("kind", {
			enum: [
				"protein_selection",
				"artifact",
				"candidate",
				"literature",
				"note",
			],
		}).notNull(),
		label: text("label").notNull(),
		selectorJson: jsonb("selector_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [index("autopep_context_reference_workspace_idx").on(t.workspaceId)],
);

export const recipes = createAutopepTable(
	"recipe",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		ownerId: text("owner_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		workspaceId: uuid("workspace_id").references(() => workspaces.id, {
			onDelete: "cascade",
		}),
		name: text("name").notNull(),
		description: text("description"),
		bodyMarkdown: text("body_markdown").notNull(),
		isGlobal: boolean("is_global").default(false).notNull(),
		enabledByDefault: boolean("enabled_by_default").default(false).notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true })
			.defaultNow()
			.$onUpdate(() => new Date())
			.notNull(),
		archivedAt: timestamp("archived_at", { withTimezone: true }),
	},
	(t) => [index("autopep_recipe_workspace_idx").on(t.workspaceId)],
);

export const recipeVersions = createAutopepTable(
	"recipe_version",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		recipeId: uuid("recipe_id")
			.notNull()
			.references(() => recipes.id, { onDelete: "cascade" }),
		version: integer("version").notNull(),
		bodyMarkdown: text("body_markdown").notNull(),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [unique("autopep_recipe_version_unique").on(t.recipeId, t.version)],
);

export const runRecipes = createAutopepTable(
	"run_recipe",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		recipeId: uuid("recipe_id")
			.notNull()
			.references(() => recipes.id, { onDelete: "cascade" }),
		recipeVersionId: uuid("recipe_version_id")
			.notNull()
			.references(() => recipeVersions.id, { onDelete: "cascade" }),
		nameSnapshot: text("name_snapshot").notNull(),
		bodySnapshot: text("body_snapshot").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [index("autopep_run_recipe_run_idx").on(t.runId)],
);

export const userRelations = relations(user, ({ many }) => ({
	account: many(account),
	session: many(session),
	workspaces: many(workspaces),
	runs: many(agentRuns),
	recipes: many(recipes),
	contextReferences: many(contextReferences),
	recipeVersions: many(recipeVersions),
}));

export const accountRelations = relations(account, ({ one }) => ({
	user: one(user, { fields: [account.userId], references: [user.id] }),
}));

export const sessionRelations = relations(session, ({ one }) => ({
	user: one(user, { fields: [session.userId], references: [user.id] }),
}));

export const workspaceRelations = relations(workspaces, ({ one, many }) => ({
	owner: one(user, { fields: [workspaces.ownerId], references: [user.id] }),
	activeThread: one(threads, {
		fields: [workspaces.activeThreadId],
		references: [threads.id],
		relationName: "activeThread",
	}),
	threads: many(threads),
	runs: many(agentRuns),
	artifacts: many(artifacts),
	candidates: many(proteinCandidates),
	contextReferences: many(contextReferences),
	recipes: many(recipes),
}));

export const threadRelations = relations(threads, ({ one, many }) => ({
	workspace: one(workspaces, {
		fields: [threads.workspaceId],
		references: [workspaces.id],
	}),
	messages: many(messages),
	runs: many(agentRuns),
}));

export const messageRelations = relations(messages, ({ one }) => ({
	thread: one(threads, {
		fields: [messages.threadId],
		references: [threads.id],
	}),
	run: one(agentRuns, {
		fields: [messages.runId],
		references: [agentRuns.id],
	}),
}));

export const agentRunRelations = relations(agentRuns, ({ one, many }) => ({
	workspace: one(workspaces, {
		fields: [agentRuns.workspaceId],
		references: [workspaces.id],
	}),
	thread: one(threads, {
		fields: [agentRuns.threadId],
		references: [threads.id],
	}),
	parentRun: one(agentRuns, {
		fields: [agentRuns.parentRunId],
		references: [agentRuns.id],
		relationName: "runLineage",
	}),
	childRuns: many(agentRuns, { relationName: "runLineage" }),
	rootRun: one(agentRuns, {
		fields: [agentRuns.rootRunId],
		references: [agentRuns.id],
		relationName: "rootRun",
	}),
	rootChildRuns: many(agentRuns, { relationName: "rootRun" }),
	createdBy: one(user, {
		fields: [agentRuns.createdById],
		references: [user.id],
	}),
	events: many(agentEvents),
	artifacts: many(artifacts),
	candidates: many(proteinCandidates),
	modelInferences: many(modelInferences),
	candidateScores: many(candidateScores),
	runRecipes: many(runRecipes),
}));

export const agentEventRelations = relations(agentEvents, ({ one }) => ({
	run: one(agentRuns, {
		fields: [agentEvents.runId],
		references: [agentRuns.id],
	}),
}));

export const artifactRelations = relations(artifacts, ({ one, many }) => ({
	workspace: one(workspaces, {
		fields: [artifacts.workspaceId],
		references: [workspaces.id],
	}),
	run: one(agentRuns, {
		fields: [artifacts.runId],
		references: [agentRuns.id],
	}),
	sourceArtifact: one(artifacts, {
		fields: [artifacts.sourceArtifactId],
		references: [artifacts.id],
		relationName: "artifactLineage",
	}),
	derivedArtifacts: many(artifacts, { relationName: "artifactLineage" }),
	candidates: many(proteinCandidates, { relationName: "candidateArtifact" }),
	foldedCandidates: many(proteinCandidates, { relationName: "foldArtifact" }),
	contextReferences: many(contextReferences),
}));

export const proteinCandidateRelations = relations(
	proteinCandidates,
	({ one, many }) => ({
		workspace: one(workspaces, {
			fields: [proteinCandidates.workspaceId],
			references: [workspaces.id],
		}),
		run: one(agentRuns, {
			fields: [proteinCandidates.runId],
			references: [agentRuns.id],
		}),
		parentCandidate: one(proteinCandidates, {
			fields: [proteinCandidates.parentCandidateId],
			references: [proteinCandidates.id],
			relationName: "candidateLineage",
		}),
		childCandidates: many(proteinCandidates, {
			relationName: "candidateLineage",
		}),
		artifact: one(artifacts, {
			fields: [proteinCandidates.artifactId],
			references: [artifacts.id],
			relationName: "candidateArtifact",
		}),
		foldArtifact: one(artifacts, {
			fields: [proteinCandidates.foldArtifactId],
			references: [artifacts.id],
			relationName: "foldArtifact",
		}),
		parentInference: one(modelInferences, {
			fields: [proteinCandidates.parentInferenceId],
			references: [modelInferences.id],
		}),
		scores: many(candidateScores),
		contextReferences: many(contextReferences),
	}),
);

export const modelInferenceRelations = relations(
	modelInferences,
	({ one, many }) => ({
		workspace: one(workspaces, {
			fields: [modelInferences.workspaceId],
			references: [workspaces.id],
		}),
		run: one(agentRuns, {
			fields: [modelInferences.runId],
			references: [agentRuns.id],
		}),
		parentInference: one(modelInferences, {
			fields: [modelInferences.parentInferenceId],
			references: [modelInferences.id],
			relationName: "inferenceLineage",
		}),
		childInferences: many(modelInferences, {
			relationName: "inferenceLineage",
		}),
		candidates: many(proteinCandidates),
		scores: many(candidateScores),
	}),
);

export const candidateScoreRelations = relations(
	candidateScores,
	({ one }) => ({
		workspace: one(workspaces, {
			fields: [candidateScores.workspaceId],
			references: [workspaces.id],
		}),
		run: one(agentRuns, {
			fields: [candidateScores.runId],
			references: [agentRuns.id],
		}),
		candidate: one(proteinCandidates, {
			fields: [candidateScores.candidateId],
			references: [proteinCandidates.id],
		}),
		modelInference: one(modelInferences, {
			fields: [candidateScores.modelInferenceId],
			references: [modelInferences.id],
		}),
	}),
);

export const contextReferenceRelations = relations(
	contextReferences,
	({ one }) => ({
		workspace: one(workspaces, {
			fields: [contextReferences.workspaceId],
			references: [workspaces.id],
		}),
		artifact: one(artifacts, {
			fields: [contextReferences.artifactId],
			references: [artifacts.id],
		}),
		candidate: one(proteinCandidates, {
			fields: [contextReferences.candidateId],
			references: [proteinCandidates.id],
		}),
		createdBy: one(user, {
			fields: [contextReferences.createdById],
			references: [user.id],
		}),
	}),
);

export const recipeRelations = relations(recipes, ({ one, many }) => ({
	owner: one(user, { fields: [recipes.ownerId], references: [user.id] }),
	workspace: one(workspaces, {
		fields: [recipes.workspaceId],
		references: [workspaces.id],
	}),
	versions: many(recipeVersions),
	runRecipes: many(runRecipes),
}));

export const recipeVersionRelations = relations(
	recipeVersions,
	({ one, many }) => ({
		recipe: one(recipes, {
			fields: [recipeVersions.recipeId],
			references: [recipes.id],
		}),
		createdBy: one(user, {
			fields: [recipeVersions.createdById],
			references: [user.id],
		}),
		runRecipes: many(runRecipes),
	}),
);

export const runRecipeRelations = relations(runRecipes, ({ one }) => ({
	run: one(agentRuns, {
		fields: [runRecipes.runId],
		references: [agentRuns.id],
	}),
	recipe: one(recipes, {
		fields: [runRecipes.recipeId],
		references: [recipes.id],
	}),
	recipeVersion: one(recipeVersions, {
		fields: [runRecipes.recipeVersionId],
		references: [recipeVersions.id],
	}),
}));
