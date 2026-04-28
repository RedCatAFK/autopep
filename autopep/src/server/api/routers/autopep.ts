import { and, asc, desc, eq, gt } from "drizzle-orm";
import { z } from "zod";

import {
	assertProjectOwner,
	createAutopepProject,
	createDiscoveryRun,
} from "@/server/agent/orchestration";
import {
	autopepAgentEvents,
	autopepAgentRuns,
	autopepArtifacts,
	autopepLiteratureHits,
	autopepProjects,
	autopepProteinCandidates,
} from "@/server/db/schema";
import { createTRPCRouter, protectedProcedure } from "../trpc";

export const autopepRouter = createTRPCRouter({
	createProject: protectedProcedure
		.input(
			z.object({
				name: z.string().min(1).max(256),
				objective: z.string().min(1),
				targetDescription: z.string().optional(),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			return createAutopepProject({
				createdById: ctx.session.user.id,
				name: input.name,
				objective: input.objective,
				targetDescription: input.targetDescription,
			});
		}),

	listProjects: protectedProcedure.query(async ({ ctx }) => {
		return ctx.db.query.autopepProjects.findMany({
			where: eq(autopepProjects.createdById, ctx.session.user.id),
			with: {
				workspace: true,
			},
			orderBy: (projects, { desc }) => [desc(projects.createdAt)],
		});
	}),

	getProject: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			return ctx.db.query.autopepProjects.findFirst({
				where: and(
					eq(autopepProjects.id, input.projectId),
					eq(autopepProjects.createdById, ctx.session.user.id),
				),
				with: {
					artifacts: {
						orderBy: (artifacts, { desc }) => [desc(artifacts.createdAt)],
					},
					proteinCandidates: {
						orderBy: (candidates, { asc }) => [asc(candidates.rank)],
					},
					runs: {
						orderBy: (runs, { desc }) => [desc(runs.createdAt)],
					},
					workspace: true,
				},
			});
		}),

	createDiscoveryRun: protectedProcedure
		.input(
			z.object({
				projectId: z.string().uuid(),
				objective: z.string().min(1),
				topK: z.number().int().min(1).max(25).default(5),
				metadata: z.record(z.unknown()).optional(),
			}),
		)
		.mutation(async ({ ctx, input }) => {
			await assertProjectOwner({
				projectId: input.projectId,
				userId: ctx.session.user.id,
			});

			return createDiscoveryRun({
				projectId: input.projectId,
				objective: input.objective,
				topK: input.topK,
				metadata: input.metadata,
			});
		}),

	getRun: protectedProcedure
		.input(z.object({ runId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			const run = await ctx.db.query.autopepAgentRuns.findFirst({
				where: eq(autopepAgentRuns.id, input.runId),
				with: {
					project: true,
				},
			});

			if (!run || run.project.createdById !== ctx.session.user.id) {
				return null;
			}

			return run;
		}),

	listRunEvents: protectedProcedure
		.input(
			z.object({
				runId: z.string().uuid(),
				afterSequence: z.number().int().min(0).default(0),
			}),
		)
		.query(async ({ ctx, input }) => {
			const run = await ctx.db.query.autopepAgentRuns.findFirst({
				where: eq(autopepAgentRuns.id, input.runId),
				with: {
					project: true,
				},
			});

			if (!run || run.project.createdById !== ctx.session.user.id) {
				return [];
			}

			return ctx.db
				.select()
				.from(autopepAgentEvents)
				.where(
					and(
						eq(autopepAgentEvents.runId, input.runId),
						gt(autopepAgentEvents.sequence, input.afterSequence),
					),
				)
				.orderBy(asc(autopepAgentEvents.sequence));
		}),

	listProjectArtifacts: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			await assertProjectOwner({
				projectId: input.projectId,
				userId: ctx.session.user.id,
			});

			return ctx.db
				.select()
				.from(autopepArtifacts)
				.where(eq(autopepArtifacts.projectId, input.projectId))
				.orderBy(desc(autopepArtifacts.createdAt));
		}),

	listProjectProteinCandidates: protectedProcedure
		.input(z.object({ projectId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			await assertProjectOwner({
				projectId: input.projectId,
				userId: ctx.session.user.id,
			});

			return ctx.db
				.select()
				.from(autopepProteinCandidates)
				.where(eq(autopepProteinCandidates.projectId, input.projectId))
				.orderBy(asc(autopepProteinCandidates.rank));
		}),

	listRunLiteratureHits: protectedProcedure
		.input(z.object({ runId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			const run = await ctx.db.query.autopepAgentRuns.findFirst({
				where: eq(autopepAgentRuns.id, input.runId),
				with: {
					project: true,
				},
			});

			if (!run || run.project.createdById !== ctx.session.user.id) {
				return [];
			}

			return ctx.db
				.select()
				.from(autopepLiteratureHits)
				.where(eq(autopepLiteratureHits.runId, input.runId))
				.orderBy(desc(autopepLiteratureHits.relevanceScore));
		}),
});
