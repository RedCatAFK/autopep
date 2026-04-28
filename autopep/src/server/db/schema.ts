import { relations, sql } from "drizzle-orm";
import {
	boolean,
	foreignKey,
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

export const projects = createAutopepTable(
	"project",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		ownerId: text("owner_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		goal: text("goal").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
		updatedAt: timestamp("updated_at", { withTimezone: true })
			.defaultNow()
			.$onUpdate(() => new Date())
			.notNull(),
	},
	(t) => [index("autopep_project_owner_idx").on(t.ownerId)],
);

export const agentRuns = createAutopepTable(
	"agent_run",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		prompt: text("prompt").notNull(),
		status: agentRunStatus("status").default("queued").notNull(),
		topK: integer("top_k").default(5).notNull(),
		claimedBy: text("claimed_by"),
		claimedAt: timestamp("claimed_at", { withTimezone: true }),
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
		index("autopep_agent_run_project_id_idx").on(t.projectId),
		index("autopep_agent_run_status_idx").on(t.status),
		unique("autopep_agent_run_id_project_id_unique").on(t.id, t.projectId),
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
		detail: text("detail"),
		payloadJson: jsonb("payload_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [
		index("autopep_agent_event_run_id_idx").on(t.runId),
		unique("autopep_agent_event_run_id_sequence_unique").on(
			t.runId,
			t.sequence,
		),
	],
);

export const targetEntities = createAutopepTable(
	"target_entity",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		organism: text("organism"),
		uniprotId: text("uniprot_id"),
		role: text("role"),
		aliasesJson: jsonb("aliases_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		rationale: text("rationale"),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [
		index("autopep_target_entity_run_id_idx").on(t.runId),
		unique("autopep_target_entity_id_run_id_unique").on(t.id, t.runId),
	],
);

export const proteinCandidates = createAutopepTable(
	"protein_candidate",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id")
			.notNull()
			.references(() => agentRuns.id, { onDelete: "cascade" }),
		targetEntityId: uuid("target_entity_id").references(
			() => targetEntities.id,
			{
				onDelete: "cascade",
			},
		),
		rank: integer("rank").notNull(),
		rcsbId: text("rcsb_id").notNull(),
		assemblyId: text("assembly_id"),
		title: text("title").notNull(),
		method: text("method"),
		resolutionAngstrom: real("resolution_angstrom"),
		organism: text("organism"),
		chainIdsJson: jsonb("chain_ids_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		ligandIdsJson: jsonb("ligand_ids_json")
			.$type<string[]>()
			.default(sql`'[]'::jsonb`)
			.notNull(),
		citationJson: jsonb("citation_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		relevanceScore: real("relevance_score").notNull(),
		confidence: real("confidence").default(0).notNull(),
		selectionRationale: text("selection_rationale").notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [
		index("autopep_protein_candidate_run_id_idx").on(t.runId),
		unique("autopep_protein_candidate_run_id_rank_unique").on(t.runId, t.rank),
		unique("autopep_protein_candidate_id_run_id_unique").on(t.id, t.runId),
		foreignKey({
			name: "autopep_protein_candidate_target_entity_run_fk",
			columns: [t.targetEntityId, t.runId],
			foreignColumns: [targetEntities.id, targetEntities.runId],
		}).onDelete("cascade"),
	],
);

export const artifacts = createAutopepTable(
	"artifact",
	{
		id: uuid("id").defaultRandom().primaryKey(),
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
		contentType: text("content_type").notNull(),
		byteSize: integer("byte_size").notNull(),
		checksum: text("checksum"),
		bucket: text("bucket").notNull(),
		objectKey: text("object_key").notNull(),
		sourceUrl: text("source_url"),
		viewerHint: text("viewer_hint").default("molstar").notNull(),
		metadataJson: jsonb("metadata_json")
			.$type<Record<string, unknown>>()
			.default(sql`'{}'::jsonb`)
			.notNull(),
		createdAt: timestamp("created_at", { withTimezone: true })
			.defaultNow()
			.notNull(),
	},
	(t) => [
		index("autopep_artifact_project_id_idx").on(t.projectId),
		index("autopep_artifact_run_id_idx").on(t.runId),
		index("autopep_artifact_candidate_id_idx").on(t.candidateId),
		foreignKey({
			name: "autopep_artifact_run_project_fk",
			columns: [t.runId, t.projectId],
			foreignColumns: [agentRuns.id, agentRuns.projectId],
		}),
		foreignKey({
			name: "autopep_artifact_candidate_run_fk",
			columns: [t.candidateId, t.runId],
			foreignColumns: [proteinCandidates.id, proteinCandidates.runId],
		}),
	],
);

export const userRelations = relations(user, ({ many }) => ({
	account: many(account),
	session: many(session),
	projects: many(projects),
	runs: many(agentRuns),
}));

export const accountRelations = relations(account, ({ one }) => ({
	user: one(user, { fields: [account.userId], references: [user.id] }),
}));

export const sessionRelations = relations(session, ({ one }) => ({
	user: one(user, { fields: [session.userId], references: [user.id] }),
}));

export const projectRelations = relations(projects, ({ one, many }) => ({
	owner: one(user, { fields: [projects.ownerId], references: [user.id] }),
	runs: many(agentRuns),
	artifacts: many(artifacts),
}));

export const agentRunRelations = relations(agentRuns, ({ one, many }) => ({
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

export const targetEntityRelations = relations(
	targetEntities,
	({ one, many }) => ({
		run: one(agentRuns, {
			fields: [targetEntities.runId],
			references: [agentRuns.id],
		}),
		candidates: many(proteinCandidates),
	}),
);

export const proteinCandidateRelations = relations(
	proteinCandidates,
	({ one, many }) => ({
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
