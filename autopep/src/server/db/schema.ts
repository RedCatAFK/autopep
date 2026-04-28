import { relations } from "drizzle-orm";
import {
	boolean,
	index,
	pgEnum,
	pgTable,
	pgTableCreator,
	text,
	timestamp,
	uniqueIndex,
} from "drizzle-orm/pg-core";

export const createTable = pgTableCreator((name) => `pg-drizzle_${name}`);
export const createAutopepTable = pgTableCreator((name) => `autopep_${name}`);

export const autopepProjectStatus = pgEnum("autopep_project_status", [
	"active",
	"archived",
]);

export const autopepWorkspaceStatus = pgEnum("autopep_workspace_status", [
	"cold",
	"ready",
	"running",
	"failed",
]);

export const autopepRunStatus = pgEnum("autopep_run_status", [
	"queued",
	"running",
	"succeeded",
	"failed",
	"canceled",
]);

export const autopepRunPhase = pgEnum("autopep_run_phase", [
	"intake",
	"entity_normalization",
	"pdb_search",
	"literature_search",
	"ranking",
	"pdb_download",
	"artifact_sync",
	"ready_for_complexa",
	"failed",
]);

export const autopepEventLevel = pgEnum("autopep_event_level", [
	"debug",
	"info",
	"warn",
	"error",
]);

export const autopepArtifactType = pgEnum("autopep_artifact_type", [
	"pdb",
	"mmcif",
	"literature_summary",
	"search_report",
	"proteina_input",
	"log",
	"other",
]);

export const autopepArtifactStorageKind = pgEnum(
	"autopep_artifact_storage_kind",
	["neon", "modal_volume", "external_url"],
);

export const autopepLiteratureSource = pgEnum("autopep_literature_source", [
	"pubmed",
	"pmc",
	"biorxiv",
	"medrxiv",
	"other",
]);

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

export const autopepProjects = createAutopepTable(
	"project",
	(d) => ({
		id: d.uuid().defaultRandom().primaryKey(),
		name: d.varchar({ length: 256 }).notNull(),
		objective: text("objective").notNull(),
		targetDescription: text("target_description"),
		status: autopepProjectStatus("status").default("active").notNull(),
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
		index("autopep_project_created_by_idx").on(t.createdById),
		index("autopep_project_status_idx").on(t.status),
	],
);

export const autopepProjectWorkspaces = createAutopepTable(
	"project_workspace",
	(d) => ({
		projectId: d
			.uuid("project_id")
			.primaryKey()
			.references(() => autopepProjects.id, { onDelete: "cascade" }),
		modalAppName: text("modal_app_name")
			.default("autopep-discovery-agent")
			.notNull(),
		modalVolumeName: text("modal_volume_name").notNull(),
		volumeRoot: text("volume_root").notNull(),
		activeSandboxId: text("active_sandbox_id"),
		activeSandboxName: text("active_sandbox_name"),
		filesystemSnapshotImageId: text("filesystem_snapshot_image_id"),
		status: autopepWorkspaceStatus("status").default("cold").notNull(),
		lastSyncedAt: d.timestamp("last_synced_at", { withTimezone: true }),
		metadata: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: d.timestamp({ withTimezone: true }).$onUpdate(() => new Date()),
	}),
	(t) => [
		index("autopep_project_workspace_status_idx").on(t.status),
		index("autopep_project_workspace_volume_name_idx").on(t.modalVolumeName),
	],
);

export const autopepAgentRuns = createAutopepTable(
	"agent_run",
	(d) => ({
		id: d.uuid().defaultRandom().primaryKey(),
		projectId: d
			.uuid("project_id")
			.notNull()
			.references(() => autopepProjects.id, { onDelete: "cascade" }),
		objective: text("objective").notNull(),
		status: autopepRunStatus("status").default("queued").notNull(),
		phase: autopepRunPhase("phase").default("intake").notNull(),
		model: text("model").default("gpt-5.5").notNull(),
		harnessName: text("harness_name").default("codex").notNull(),
		lifeSciencePluginRef: text("life_science_plugin_ref").notNull(),
		topK: d.integer("top_k").default(5).notNull(),
		modalSandboxId: text("modal_sandbox_id"),
		modalSandboxName: text("modal_sandbox_name"),
		modalFilesystemSnapshotImageId: text(
			"modal_filesystem_snapshot_image_id",
		),
		metadata: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		errorMessage: text("error_message"),
		startedAt: d.timestamp("started_at", { withTimezone: true }),
		completedAt: d.timestamp("completed_at", { withTimezone: true }),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: d.timestamp({ withTimezone: true }).$onUpdate(() => new Date()),
	}),
	(t) => [
		index("autopep_agent_run_project_idx").on(t.projectId),
		index("autopep_agent_run_status_idx").on(t.status),
		index("autopep_agent_run_phase_idx").on(t.phase),
	],
);

export const autopepAgentEvents = createAutopepTable(
	"agent_event",
	(d) => ({
		id: d.integer().primaryKey().generatedByDefaultAsIdentity(),
		runId: d
			.uuid("run_id")
			.notNull()
			.references(() => autopepAgentRuns.id, { onDelete: "cascade" }),
		sequence: d.integer().notNull(),
		phase: autopepRunPhase("phase"),
		level: autopepEventLevel("level").default("info").notNull(),
		type: text("type").notNull(),
		message: text("message").notNull(),
		payload: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
	}),
	(t) => [
		index("autopep_agent_event_run_idx").on(t.runId),
		uniqueIndex("autopep_agent_event_run_sequence_idx").on(
			t.runId,
			t.sequence,
		),
	],
);

export const autopepProteinCandidates = createAutopepTable(
	"protein_candidate",
	(d) => ({
		id: d.uuid().defaultRandom().primaryKey(),
		projectId: d
			.uuid("project_id")
			.notNull()
			.references(() => autopepProjects.id, { onDelete: "cascade" }),
		runId: d
			.uuid("run_id")
			.notNull()
			.references(() => autopepAgentRuns.id, { onDelete: "cascade" }),
		rank: d.integer().notNull(),
		pdbId: text("pdb_id"),
		chainIds: text("chain_ids").array().default([]).notNull(),
		title: text("title").notNull(),
		sourceDatabase: text("source_database").default("RCSB PDB").notNull(),
		sourceUrl: text("source_url"),
		organism: text("organism"),
		experimentalMethod: text("experimental_method"),
		resolutionAngstrom: d.doublePrecision("resolution_angstrom"),
		relevanceScore: d.doublePrecision("relevance_score"),
		selectionRationale: text("selection_rationale").notNull(),
		metadata: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: d.timestamp({ withTimezone: true }).$onUpdate(() => new Date()),
	}),
	(t) => [
		index("autopep_protein_candidate_project_idx").on(t.projectId),
		index("autopep_protein_candidate_run_idx").on(t.runId),
		uniqueIndex("autopep_protein_candidate_run_rank_idx").on(t.runId, t.rank),
	],
);

export const autopepArtifacts = createAutopepTable(
	"artifact",
	(d) => ({
		id: d.uuid().defaultRandom().primaryKey(),
		projectId: d
			.uuid("project_id")
			.notNull()
			.references(() => autopepProjects.id, { onDelete: "cascade" }),
		runId: d
			.uuid("run_id")
			.references(() => autopepAgentRuns.id, { onDelete: "set null" }),
		proteinCandidateId: d
			.uuid("protein_candidate_id")
			.references(() => autopepProteinCandidates.id, { onDelete: "set null" }),
		type: autopepArtifactType("type").notNull(),
		storageKind: autopepArtifactStorageKind("storage_kind").notNull(),
		displayName: text("display_name").notNull(),
		mimeType: text("mime_type"),
		contentText: text("content_text"),
		contentSha256: text("content_sha256"),
		sizeBytes: d.integer("size_bytes"),
		modalVolumeName: text("modal_volume_name"),
		modalPath: text("modal_path"),
		externalUrl: text("external_url"),
		metadata: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
		updatedAt: d.timestamp({ withTimezone: true }).$onUpdate(() => new Date()),
	}),
	(t) => [
		index("autopep_artifact_project_idx").on(t.projectId),
		index("autopep_artifact_run_idx").on(t.runId),
		index("autopep_artifact_candidate_idx").on(t.proteinCandidateId),
		index("autopep_artifact_type_idx").on(t.type),
		index("autopep_artifact_content_sha_idx").on(t.contentSha256),
	],
);

export const autopepLiteratureHits = createAutopepTable(
	"literature_hit",
	(d) => ({
		id: d.uuid().defaultRandom().primaryKey(),
		projectId: d
			.uuid("project_id")
			.notNull()
			.references(() => autopepProjects.id, { onDelete: "cascade" }),
		runId: d
			.uuid("run_id")
			.notNull()
			.references(() => autopepAgentRuns.id, { onDelete: "cascade" }),
		source: autopepLiteratureSource("source").notNull(),
		title: text("title").notNull(),
		abstract: text("abstract"),
		doi: text("doi"),
		pmid: text("pmid"),
		pmcid: text("pmcid"),
		url: text("url"),
		publishedAt: d.timestamp("published_at", { withTimezone: true }),
		relevanceScore: d.doublePrecision("relevance_score"),
		summary: text("summary"),
		metadata: d.jsonb().$type<Record<string, unknown>>().default({}).notNull(),
		createdAt: d
			.timestamp({ withTimezone: true })
			.$defaultFn(() => new Date())
			.notNull(),
	}),
	(t) => [
		index("autopep_literature_hit_project_idx").on(t.projectId),
		index("autopep_literature_hit_run_idx").on(t.runId),
		index("autopep_literature_hit_source_idx").on(t.source),
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

export const userRelations = relations(user, ({ many }) => ({
	account: many(account),
	session: many(session),
}));

export const accountRelations = relations(account, ({ one }) => ({
	user: one(user, { fields: [account.userId], references: [user.id] }),
}));

export const sessionRelations = relations(session, ({ one }) => ({
	user: one(user, { fields: [session.userId], references: [user.id] }),
}));

export const autopepProjectRelations = relations(
	autopepProjects,
	({ many, one }) => ({
		artifacts: many(autopepArtifacts),
		createdBy: one(user, {
			fields: [autopepProjects.createdById],
			references: [user.id],
		}),
		literatureHits: many(autopepLiteratureHits),
		proteinCandidates: many(autopepProteinCandidates),
		runs: many(autopepAgentRuns),
		workspace: one(autopepProjectWorkspaces),
	}),
);

export const autopepProjectWorkspaceRelations = relations(
	autopepProjectWorkspaces,
	({ one }) => ({
		project: one(autopepProjects, {
			fields: [autopepProjectWorkspaces.projectId],
			references: [autopepProjects.id],
		}),
	}),
);

export const autopepAgentRunRelations = relations(
	autopepAgentRuns,
	({ many, one }) => ({
		artifacts: many(autopepArtifacts),
		events: many(autopepAgentEvents),
		literatureHits: many(autopepLiteratureHits),
		project: one(autopepProjects, {
			fields: [autopepAgentRuns.projectId],
			references: [autopepProjects.id],
		}),
		proteinCandidates: many(autopepProteinCandidates),
	}),
);

export const autopepAgentEventRelations = relations(
	autopepAgentEvents,
	({ one }) => ({
		run: one(autopepAgentRuns, {
			fields: [autopepAgentEvents.runId],
			references: [autopepAgentRuns.id],
		}),
	}),
);

export const autopepProteinCandidateRelations = relations(
	autopepProteinCandidates,
	({ many, one }) => ({
		artifacts: many(autopepArtifacts),
		project: one(autopepProjects, {
			fields: [autopepProteinCandidates.projectId],
			references: [autopepProjects.id],
		}),
		run: one(autopepAgentRuns, {
			fields: [autopepProteinCandidates.runId],
			references: [autopepAgentRuns.id],
		}),
	}),
);

export const autopepArtifactRelations = relations(
	autopepArtifacts,
	({ one }) => ({
		project: one(autopepProjects, {
			fields: [autopepArtifacts.projectId],
			references: [autopepProjects.id],
		}),
		proteinCandidate: one(autopepProteinCandidates, {
			fields: [autopepArtifacts.proteinCandidateId],
			references: [autopepProteinCandidates.id],
		}),
		run: one(autopepAgentRuns, {
			fields: [autopepArtifacts.runId],
			references: [autopepAgentRuns.id],
		}),
	}),
);

export const autopepLiteratureHitRelations = relations(
	autopepLiteratureHits,
	({ one }) => ({
		project: one(autopepProjects, {
			fields: [autopepLiteratureHits.projectId],
			references: [autopepProjects.id],
		}),
		run: one(autopepAgentRuns, {
			fields: [autopepLiteratureHits.runId],
			references: [autopepAgentRuns.id],
		}),
	}),
);
