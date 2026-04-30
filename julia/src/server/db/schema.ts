import { relations } from "drizzle-orm";
import {
	boolean,
	index,
	integer,
	jsonb,
	pgEnum,
	pgTable,
	pgTableCreator,
	text,
	timestamp,
	uuid,
} from "drizzle-orm/pg-core";

export const createTable = pgTableCreator((name) => `julia_${name}`);

export const runModeEnum = pgEnum("julia_run_mode", ["chat", "research"]);
export const runStatusEnum = pgEnum("julia_run_status", [
	"queued",
	"running",
	"completed",
	"failed",
	"canceled",
]);
export const runEventTypeEnum = pgEnum("julia_run_event_type", [
	"queued",
	"running",
	"run_status",
	"text_delta",
	"tool_started",
	"tool_completed",
	"tool_call_started",
	"tool_call_completed",
	"message",
	"artifact_created",
	"completed",
	"run_error",
]);
export const artifactKindEnum = pgEnum("julia_artifact_kind", [
	"structure",
	"json",
	"fasta",
	"log",
	"text",
	"other",
]);

const metadata = () =>
	jsonb("metadata").$type<Record<string, unknown>>().notNull().default({});

const createdAt = () =>
	timestamp("created_at", { withTimezone: true })
		.$defaultFn(() => new Date())
		.notNull();

const updatedAt = () =>
	timestamp("updated_at", { withTimezone: true }).$onUpdate(() => new Date());

export const posts = createTable(
	"post",
	{
		id: integer("id").primaryKey().generatedByDefaultAsIdentity(),
		name: text("name"),
		createdById: text("created_by_id")
			.notNull()
			.references(() => user.id),
		createdAt: createdAt(),
		updatedAt: updatedAt(),
	},
	(t) => [
		index("julia_post_created_by_idx").on(t.createdById),
		index("julia_post_name_idx").on(t.name),
	],
);

export const projects = createTable(
	"projects",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		ownerId: text("owner_id")
			.notNull()
			.references(() => user.id, { onDelete: "cascade" }),
		name: text("name").notNull(),
		description: text("description"),
		metadata: metadata(),
		createdAt: createdAt(),
		updatedAt: updatedAt(),
	},
	(t) => [index("julia_projects_owner_id_idx").on(t.ownerId)],
);

export const threads = createTable(
	"threads",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		title: text("title").notNull(),
		metadata: metadata(),
		createdAt: createdAt(),
		updatedAt: updatedAt(),
	},
	(t) => [index("julia_threads_project_id_idx").on(t.projectId)],
);

export const messages = createTable(
	"messages",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		threadId: uuid("thread_id")
			.notNull()
			.references(() => threads.id, { onDelete: "cascade" }),
		role: text("role").notNull(),
		content: text("content").notNull(),
		metadata: metadata(),
		createdAt: createdAt(),
	},
	(t) => [index("julia_messages_thread_id_idx").on(t.threadId)],
);

export const runs = createTable(
	"runs",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		threadId: uuid("thread_id").references(() => threads.id, {
			onDelete: "set null",
		}),
		mode: runModeEnum("mode").notNull().default("chat"),
		status: runStatusEnum("status").notNull().default("queued"),
		input: text("input"),
		summary: text("summary"),
		metadata: metadata(),
		startedAt: timestamp("started_at", { withTimezone: true }),
		completedAt: timestamp("completed_at", { withTimezone: true }),
		createdAt: createdAt(),
		updatedAt: updatedAt(),
	},
	(t) => [
		index("julia_runs_project_id_idx").on(t.projectId),
		index("julia_runs_thread_id_idx").on(t.threadId),
		index("julia_runs_status_idx").on(t.status),
	],
);

export const runEvents = createTable(
	"run_events",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		runId: uuid("run_id")
			.notNull()
			.references(() => runs.id, { onDelete: "cascade" }),
		type: runEventTypeEnum("type").notNull(),
		message: text("message"),
		sequence: integer("sequence").notNull().default(0),
		metadata: metadata(),
		createdAt: createdAt(),
	},
	(t) => [
		index("julia_run_events_run_id_idx").on(t.runId),
		index("julia_run_events_type_idx").on(t.type),
	],
);

export const artifacts = createTable(
	"artifacts",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		runId: uuid("run_id").references(() => runs.id, { onDelete: "set null" }),
		kind: artifactKindEnum("kind").notNull().default("other"),
		filename: text("filename").notNull(),
		contentType: text("content_type"),
		r2Key: text("r2_key").notNull(),
		sizeBytes: integer("size_bytes"),
		metadata: metadata(),
		createdAt: createdAt(),
	},
	(t) => [
		index("julia_artifacts_project_id_idx").on(t.projectId),
		index("julia_artifacts_run_id_idx").on(t.runId),
		index("julia_artifacts_kind_idx").on(t.kind),
	],
);

export const contextReferences = createTable(
	"context_references",
	{
		id: uuid("id").defaultRandom().primaryKey(),
		projectId: uuid("project_id")
			.notNull()
			.references(() => projects.id, { onDelete: "cascade" }),
		threadId: uuid("thread_id").references(() => threads.id, {
			onDelete: "cascade",
		}),
		messageId: uuid("message_id").references(() => messages.id, {
			onDelete: "cascade",
		}),
		artifactId: uuid("artifact_id").references(() => artifacts.id, {
			onDelete: "cascade",
		}),
		label: text("label").notNull(),
		metadata: metadata(),
		createdAt: createdAt(),
	},
	(t) => [
		index("julia_context_references_project_id_idx").on(t.projectId),
		index("julia_context_references_thread_id_idx").on(t.threadId),
		index("julia_context_references_artifact_id_idx").on(t.artifactId),
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

export const projectRelations = relations(projects, ({ many, one }) => ({
	owner: one(user, { fields: [projects.ownerId], references: [user.id] }),
	threads: many(threads),
	runs: many(runs),
	artifacts: many(artifacts),
	contextReferences: many(contextReferences),
}));

export const threadRelations = relations(threads, ({ many, one }) => ({
	project: one(projects, {
		fields: [threads.projectId],
		references: [projects.id],
	}),
	messages: many(messages),
	runs: many(runs),
	contextReferences: many(contextReferences),
}));

export const messageRelations = relations(messages, ({ many, one }) => ({
	thread: one(threads, {
		fields: [messages.threadId],
		references: [threads.id],
	}),
	contextReferences: many(contextReferences),
}));

export const runRelations = relations(runs, ({ many, one }) => ({
	project: one(projects, {
		fields: [runs.projectId],
		references: [projects.id],
	}),
	thread: one(threads, { fields: [runs.threadId], references: [threads.id] }),
	events: many(runEvents),
	artifacts: many(artifacts),
}));

export const runEventRelations = relations(runEvents, ({ one }) => ({
	run: one(runs, { fields: [runEvents.runId], references: [runs.id] }),
}));

export const artifactRelations = relations(artifacts, ({ many, one }) => ({
	project: one(projects, {
		fields: [artifacts.projectId],
		references: [projects.id],
	}),
	run: one(runs, { fields: [artifacts.runId], references: [runs.id] }),
	contextReferences: many(contextReferences),
}));

export const contextReferenceRelations = relations(
	contextReferences,
	({ one }) => ({
		project: one(projects, {
			fields: [contextReferences.projectId],
			references: [projects.id],
		}),
		thread: one(threads, {
			fields: [contextReferences.threadId],
			references: [threads.id],
		}),
		message: one(messages, {
			fields: [contextReferences.messageId],
			references: [messages.id],
		}),
		artifact: one(artifacts, {
			fields: [contextReferences.artifactId],
			references: [artifacts.id],
		}),
	}),
);
