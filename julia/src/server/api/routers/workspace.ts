import { TRPCError } from "@trpc/server";
import { and, asc, desc, eq } from "drizzle-orm";
import { z } from "zod";

import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import type { db as dbClient } from "@/server/db";
import {
	artifacts,
	contextReferences,
	messages,
	projects,
	runEvents,
	runs,
	threads,
} from "@/server/db/schema";

const DEFAULT_PROJECT_NAME = "Julia workspace";
const DEFAULT_THREAD_TITLE = "New thread";
type Db = typeof dbClient;

export const workspaceRouter = createTRPCRouter({
	getOrCreateDefaultProject: protectedProcedure.query(async ({ ctx }) => {
		const project = await getOrCreateDefaultProject(
			ctx.db,
			ctx.session.user.id,
		);
		await ensureDefaultThread(ctx.db, project.id);
		return project;
	}),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const project = await getOrCreateDefaultProject(
			ctx.db,
			ctx.session.user.id,
		);
		await ensureDefaultThread(ctx.db, project.id);
		return getProjectState(ctx.db, project.id);
	}),

	getProjectState: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			await assertProjectOwner(ctx.db, input.projectId, ctx.session.user.id);
			return getProjectState(ctx.db, input.projectId);
		}),

	createThread: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.mutation(async ({ ctx, input }) => {
			await assertProjectOwner(ctx.db, input.projectId, ctx.session.user.id);

			const [thread] = await ctx.db
				.insert(threads)
				.values({
					projectId: input.projectId,
					title: DEFAULT_THREAD_TITLE,
				})
				.returning();

			return thread;
		}),

	listArtifacts: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			await assertProjectOwner(ctx.db, input.projectId, ctx.session.user.id);

			const rows = await ctx.db
				.select()
				.from(artifacts)
				.where(eq(artifacts.projectId, input.projectId))
				.orderBy(desc(artifacts.createdAt));

			return rows.map(toArtifactShape);
		}),

	addContextReference: protectedProcedure
		.input(
			z.object({
				projectId: z.string().uuid(),
				threadId: z.string().uuid().optional(),
				artifactId: z.string().uuid(),
				label: z.string().trim().min(1),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			await assertProjectOwner(ctx.db, input.projectId, ctx.session.user.id);
			if (input.threadId) {
				await assertThreadInProject(ctx.db, input.threadId, input.projectId);
			}
			await assertArtifactInProject(ctx.db, input.artifactId, input.projectId);

			const [reference] = await ctx.db
				.insert(contextReferences)
				.values({
					projectId: input.projectId,
					threadId: input.threadId,
					artifactId: input.artifactId,
					label: input.label,
				})
				.returning();

			return reference;
		}),

	removeContextReference: protectedProcedure
		.input(
			z.object({
				id: z.string().uuid().optional(),
				referenceId: z.string().uuid().optional(),
				projectId: z.string().uuid().optional(),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			const id = input.id ?? input.referenceId;
			if (!id) {
				throw new TRPCError({
					code: "BAD_REQUEST",
					message: "Context reference id is required",
				});
			}
			const [reference] = await ctx.db
				.select({
					id: contextReferences.id,
					projectId: contextReferences.projectId,
				})
				.from(contextReferences)
				.innerJoin(projects, eq(projects.id, contextReferences.projectId))
				.where(
					and(
						eq(contextReferences.id, id),
						eq(projects.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!reference) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Context reference not found",
				});
			}

			await ctx.db
				.delete(contextReferences)
				.where(eq(contextReferences.id, id));

			return { id };
		}),

	deleteContextReference: protectedProcedure
		.input(
			z.object({
				referenceId: z.string().uuid(),
				projectId: z.string().uuid().optional(),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			const [reference] = await ctx.db
				.select({ id: contextReferences.id })
				.from(contextReferences)
				.innerJoin(projects, eq(projects.id, contextReferences.projectId))
				.where(
					and(
						eq(contextReferences.id, input.referenceId),
						eq(projects.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!reference) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Context reference not found",
				});
			}

			await ctx.db
				.delete(contextReferences)
				.where(eq(contextReferences.id, input.referenceId));

			return { id: input.referenceId };
		}),
});

async function getProjectState(db: Db, projectId: string) {
	const [
		projectRows,
		threadRows,
		messageRows,
		runRows,
		eventRows,
		artifactRows,
		contextReferenceRows,
	] = await Promise.all([
		db.select().from(projects).where(eq(projects.id, projectId)).limit(1),
		db
			.select()
			.from(threads)
			.where(eq(threads.projectId, projectId))
			.orderBy(desc(threads.createdAt)),
		db
			.select()
			.from(messages)
			.innerJoin(threads, eq(threads.id, messages.threadId))
			.where(eq(threads.projectId, projectId))
			.orderBy(asc(messages.createdAt)),
		db
			.select()
			.from(runs)
			.where(eq(runs.projectId, projectId))
			.orderBy(desc(runs.createdAt)),
		db
			.select()
			.from(runEvents)
			.innerJoin(runs, eq(runs.id, runEvents.runId))
			.where(eq(runs.projectId, projectId))
			.orderBy(asc(runEvents.sequence)),
		db
			.select()
			.from(artifacts)
			.where(eq(artifacts.projectId, projectId))
			.orderBy(desc(artifacts.createdAt)),
		db
			.select()
			.from(contextReferences)
			.where(eq(contextReferences.projectId, projectId))
			.orderBy(desc(contextReferences.createdAt)),
	]);

	const currentThread = threadRows[0] ?? null;
	const activeRun = runRows.find((run) =>
		["queued", "running"].includes(run.status),
	);

	return {
		project: projectRows[0],
		thread: currentThread,
		threads: threadRows,
		currentThread,
		messages: messageRows.map(({ messages: message }) => message),
		runs: runRows,
		events: eventRows.map(({ run_events: event }) => event),
		artifacts: artifactRows.map(toArtifactShape),
		contextReferences: contextReferenceRows,
		activeRunId: activeRun?.id ?? null,
	};
}

async function getOrCreateDefaultProject(db: Db, ownerId: string) {
	const [existingProject] = await db
		.select()
		.from(projects)
		.where(eq(projects.ownerId, ownerId))
		.orderBy(asc(projects.createdAt))
		.limit(1);

	if (existingProject) return existingProject;

	const [project] = await db
		.insert(projects)
		.values({ ownerId, name: DEFAULT_PROJECT_NAME })
		.returning();

	if (!project) {
		throw new TRPCError({
			code: "INTERNAL_SERVER_ERROR",
			message: "Failed to create default project",
		});
	}

	return project;
}

async function ensureDefaultThread(db: Db, projectId: string) {
	const [existingThread] = await db
		.select({ id: threads.id })
		.from(threads)
		.where(eq(threads.projectId, projectId))
		.limit(1);

	if (existingThread) return;

	await db.insert(threads).values({
		projectId,
		title: DEFAULT_THREAD_TITLE,
	});
}

async function assertProjectOwner(db: Db, projectId: string, userId: string) {
	const [project] = await db
		.select({ id: projects.id })
		.from(projects)
		.where(and(eq(projects.id, projectId), eq(projects.ownerId, userId)))
		.limit(1);

	if (!project) {
		throw new TRPCError({ code: "NOT_FOUND", message: "Project not found" });
	}
}

async function assertThreadInProject(
	db: Db,
	threadId: string,
	projectId: string,
) {
	const [thread] = await db
		.select({ id: threads.id })
		.from(threads)
		.where(and(eq(threads.id, threadId), eq(threads.projectId, projectId)))
		.limit(1);

	if (!thread) {
		throw new TRPCError({ code: "NOT_FOUND", message: "Thread not found" });
	}
}

async function assertArtifactInProject(
	db: Db,
	artifactId: string,
	projectId: string,
) {
	const [artifact] = await db
		.select({ id: artifacts.id })
		.from(artifacts)
		.where(
			and(eq(artifacts.id, artifactId), eq(artifacts.projectId, projectId)),
		)
		.limit(1);

	if (!artifact) {
		throw new TRPCError({ code: "NOT_FOUND", message: "Artifact not found" });
	}
}

function toArtifactShape(artifact: typeof artifacts.$inferSelect) {
	return {
		...artifact,
		viewerUrl: `/api/artifacts/${artifact.id}`,
	};
}
