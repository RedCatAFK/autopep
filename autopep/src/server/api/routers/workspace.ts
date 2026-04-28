import { and, asc, desc, eq, gt } from "drizzle-orm";
import { z } from "zod";

import { createProjectRunWithLaunch } from "@/server/agent/project-run-creator";
import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	projects,
	proteinCandidates,
	targetEntities,
} from "@/server/db/schema";

type Db = typeof appDb;

const projectIdInput = z.object({
	projectId: z.string().uuid(),
});

const runEventsInput = z.object({
	runId: z.string().uuid(),
	afterSequence: z.number().int().min(0).default(0),
});

const createProjectRunInput = z.object({
	goal: z.string().min(3),
	name: z.string().min(1).max(120).optional(),
	topK: z.number().int().min(1).max(10).default(5),
});

export const getWorkspacePayload = async (
	db: Db,
	projectId: string,
	ownerId: string,
) => {
	const project = await db.query.projects.findFirst({
		where: and(eq(projects.id, projectId), eq(projects.ownerId, ownerId)),
	});

	if (!project) {
		return null;
	}

	const runs = await db.query.agentRuns.findMany({
		where: eq(agentRuns.projectId, project.id),
		orderBy: [desc(agentRuns.createdAt)],
		limit: 10,
	});

	const activeRun = runs[0] ?? null;

	if (!activeRun) {
		return {
			project,
			runs,
			activeRun,
			events: [],
			targetEntities: [],
			candidates: [],
			artifacts: [],
		};
	}

	const [events, targetEntitiesForRun, candidates, artifactsForRun] =
		await Promise.all([
			db.query.agentEvents.findMany({
				where: eq(agentEvents.runId, activeRun.id),
				orderBy: [asc(agentEvents.sequence)],
			}),
			db.query.targetEntities.findMany({
				where: eq(targetEntities.runId, activeRun.id),
				orderBy: [asc(targetEntities.createdAt)],
			}),
			db.query.proteinCandidates.findMany({
				where: eq(proteinCandidates.runId, activeRun.id),
				orderBy: [asc(proteinCandidates.rank)],
			}),
			db.query.artifacts.findMany({
				where: eq(artifacts.runId, activeRun.id),
				orderBy: [desc(artifacts.createdAt)],
			}),
		]);

	const artifactsWithSignedUrls = await Promise.all(
		artifactsForRun.map(async (artifact) => ({
			...artifact,
			signedUrl: await r2ArtifactStore.getReadUrl({
				key: artifact.objectKey,
			}),
		})),
	);

	return {
		project,
		runs,
		activeRun,
		events,
		targetEntities: targetEntitiesForRun,
		candidates,
		artifacts: artifactsWithSignedUrls,
	};
};

export const workspaceRouter = createTRPCRouter({
	createProjectRun: protectedProcedure
		.input(createProjectRunInput)
		.mutation(async ({ ctx, input }) => {
			const ownerId = ctx.session.user.id;
			return createProjectRunWithLaunch({
				db: ctx.db,
				input,
				ownerId,
			});
		}),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const project = await ctx.db.query.projects.findFirst({
			where: eq(projects.ownerId, ctx.session.user.id),
			orderBy: [desc(projects.createdAt)],
		});

		if (!project) {
			return null;
		}

		return getWorkspacePayload(ctx.db, project.id, ctx.session.user.id);
	}),

	getWorkspace: protectedProcedure
		.input(projectIdInput)
		.query(async ({ ctx, input }) =>
			getWorkspacePayload(ctx.db, input.projectId, ctx.session.user.id),
		),

	getRunEvents: protectedProcedure
		.input(runEventsInput)
		.query(async ({ ctx, input }) => {
			const run = await ctx.db
				.select({ id: agentRuns.id })
				.from(agentRuns)
				.innerJoin(projects, eq(agentRuns.projectId, projects.id))
				.where(
					and(
						eq(agentRuns.id, input.runId),
						eq(projects.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!run[0]) {
				return [];
			}

			return ctx.db.query.agentEvents.findMany({
				where: and(
					eq(agentEvents.runId, input.runId),
					gt(agentEvents.sequence, input.afterSequence),
				),
				orderBy: [asc(agentEvents.sequence)],
			});
		}),
});
