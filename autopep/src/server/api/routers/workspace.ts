import { TRPCError } from "@trpc/server";
import { and, desc, eq, isNull } from "drizzle-orm";
import { z } from "zod";

import { taskKindSchema } from "@/server/agent/contracts";
import {
	createMessageRunWithLaunch,
	createProjectRunWithLaunch,
} from "@/server/agent/project-run-creator";
import { answerWorkspaceQuestion } from "@/server/agent/workspace-answer";
import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import {
	type agentEvents,
	agentRuns,
	type artifacts,
	type proteinCandidates,
	workspaces,
} from "@/server/db/schema";
import {
	createWorkspaceWithThread,
	getWorkspacePayload as getRepositoryWorkspacePayload,
	getRunEventsAfter,
	listWorkspacesForOwner,
} from "@/server/workspaces/repository";

type Db = typeof appDb;

const workspaceIdInput = z.object({
	workspaceId: z.string().uuid(),
});

const compatibleWorkspaceIdInput = z
	.object({
		projectId: z.string().uuid().optional(),
		workspaceId: z.string().uuid().optional(),
	})
	.refine((input) => input.workspaceId ?? input.projectId, {
		message: "workspaceId is required.",
	});

const runEventsInput = z.object({
	afterSequence: z.number().int().min(0).default(0),
	runId: z.string().uuid(),
});

const createProjectRunInput = z.object({
	goal: z.string().min(3),
	name: z.string().min(1).max(120).optional(),
	topK: z.number().int().min(1).max(10).default(5),
});

const answerQuestionInput = z.object({
	projectId: z.string().uuid().optional(),
	question: z.string().min(1).max(1000),
	workspaceId: z.string().uuid().optional(),
});

const sendMessageInput = z.object({
	attachmentRefs: z.array(z.string().uuid()).default([]),
	contextRefs: z.array(z.string().uuid()).default([]),
	prompt: z.string().min(1).max(12000),
	projectId: z.string().uuid().optional(),
	recipeRefs: z.array(z.string().uuid()).default([]),
	taskKind: taskKindSchema.default("chat"),
	workspaceId: z.string().uuid().optional(),
});

const getRecord = (value: unknown): Record<string, unknown> =>
	value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};

const getString = (value: unknown): string | null =>
	typeof value === "string" ? value : null;

const getNumber = (value: unknown): number | null =>
	typeof value === "number" ? value : null;

const getBoolean = (value: unknown): boolean =>
	typeof value === "boolean" ? value : false;

const resolveWorkspaceId = (input: {
	projectId?: string;
	workspaceId?: string;
}) => {
	const workspaceId = input.workspaceId ?? input.projectId;
	if (!workspaceId) {
		throw new TRPCError({
			code: "BAD_REQUEST",
			message: "workspaceId is required.",
		});
	}
	return workspaceId;
};

const inferTargetName = (prompt: string) => {
	const normalized = prompt.toLowerCase();
	if (normalized.includes("3cl") || normalized.includes("protease")) {
		return "SARS-CoV-2 3CL protease";
	}
	if (normalized.includes("spike") || normalized.includes("rbd")) {
		return "SARS-CoV-2 spike receptor binding domain";
	}

	return prompt;
};

const artifactKindToLegacyType = (
	kind: string,
	metadataJson: Record<string, unknown>,
) => {
	const legacyType = getString(metadataJson.legacyType);
	if (legacyType) {
		return legacyType;
	}

	if (kind === "cif" || kind === "mmcif") {
		return "source_cif";
	}

	return kind;
};

const mapWorkspaceToProject = (
	workspace: typeof workspaces.$inferSelect,
	activeRun: typeof agentRuns.$inferSelect | null,
) => ({
	...workspace,
	goal: workspace.description ?? activeRun?.prompt ?? "",
});

const mapEvent = (event: typeof agentEvents.$inferSelect) => ({
	...event,
	detail: event.summary,
	payloadJson: event.displayJson,
});

const mapCandidate = (candidate: typeof proteinCandidates.$inferSelect) => {
	const scoreJson = getRecord(candidate.scoreJson);
	const metadataJson = getRecord(candidate.metadataJson);

	return {
		...candidate,
		citationJson: getRecord(scoreJson.citation),
		confidence: getNumber(scoreJson.confidence) ?? 0,
		ligandIdsJson: Array.isArray(scoreJson.ligands) ? scoreJson.ligands : [],
		method: getString(scoreJson.method),
		organism: getString(metadataJson.organism),
		proteinaReady: getBoolean(metadataJson.proteinaReady),
		rcsbId:
			getString(metadataJson.rcsbId) ?? candidate.structureId ?? candidate.id,
		relevanceScore: getNumber(scoreJson.relevance) ?? 0,
		resolutionAngstrom: getNumber(scoreJson.resolution),
		selectionRationale: candidate.whySelected ?? "",
	};
};

const mapArtifact = async (artifact: typeof artifacts.$inferSelect) => {
	const metadataJson = getRecord(artifact.metadataJson);

	return {
		...artifact,
		byteSize: artifact.sizeBytes,
		candidateId: getString(metadataJson.candidateId),
		fileName: artifact.name,
		objectKey: artifact.storageKey,
		signedUrl: await r2ArtifactStore.getReadUrl({
			key: artifact.storageKey,
		}),
		sourceUrl: getString(metadataJson.sourceUrl),
		type: artifactKindToLegacyType(artifact.kind, metadataJson),
	};
};

const getLatestWorkspaceForOwner = async (db: Db, ownerId: string) =>
	db.query.workspaces.findFirst({
		where: and(eq(workspaces.ownerId, ownerId), isNull(workspaces.archivedAt)),
		orderBy: [desc(workspaces.updatedAt)],
	});

const getWorkspaceCompatibilityPayload = async ({
	db,
	ownerId,
	workspaceId,
}: {
	db: Db;
	ownerId: string;
	workspaceId: string;
}) => {
	const payload = await getRepositoryWorkspacePayload({
		db,
		ownerId,
		workspaceId,
	});

	if (!payload) {
		return null;
	}

	const project = mapWorkspaceToProject(payload.workspace, payload.activeRun);
	const targetEntities = payload.activeRun
		? [
				{
					name: inferTargetName(payload.activeRun.prompt),
					organism: payload.activeRun.prompt
						.toLowerCase()
						.includes("sars-cov-2")
						? "SARS-CoV-2"
						: null,
				},
			]
		: [];

	return {
		...payload,
		artifacts: await Promise.all(payload.artifacts.map(mapArtifact)),
		candidateScores: payload.candidateScores,
		candidates: payload.candidates.map(mapCandidate),
		events: payload.events.map(mapEvent),
		project,
		targetEntities,
	};
};

export const getWorkspacePayload = (
	db: Db,
	projectId: string,
	ownerId: string,
) =>
	getWorkspaceCompatibilityPayload({
		db,
		ownerId,
		workspaceId: projectId,
	});

export const workspaceRouter = createTRPCRouter({
	listWorkspaces: protectedProcedure.query(async ({ ctx }) =>
		listWorkspacesForOwner(ctx.db, ctx.session.user.id),
	),

	createWorkspace: protectedProcedure
		.input(
			z.object({
				description: z.string().max(1000).nullable().optional(),
				name: z.string().min(1).max(120),
			}),
		)
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
				.where(
					and(
						eq(workspaces.id, input.workspaceId),
						eq(workspaces.ownerId, ctx.session.user.id),
						isNull(workspaces.archivedAt),
					),
				)
				.returning();

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			return workspace;
		}),

	archiveWorkspace: protectedProcedure
		.input(workspaceIdInput)
		.mutation(async ({ ctx, input }) => {
			const [workspace] = await ctx.db
				.update(workspaces)
				.set({ archivedAt: new Date() })
				.where(
					and(
						eq(workspaces.id, input.workspaceId),
						eq(workspaces.ownerId, ctx.session.user.id),
					),
				)
				.returning();

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			return workspace;
		}),

	getWorkspace: protectedProcedure
		.input(compatibleWorkspaceIdInput)
		.query(async ({ ctx, input }) =>
			getWorkspaceCompatibilityPayload({
				db: ctx.db,
				ownerId: ctx.session.user.id,
				workspaceId: resolveWorkspaceId(input),
			}),
		),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const workspace = await getLatestWorkspaceForOwner(
			ctx.db,
			ctx.session.user.id,
		);

		if (!workspace) {
			return null;
		}

		return getWorkspaceCompatibilityPayload({
			db: ctx.db,
			ownerId: ctx.session.user.id,
			workspaceId: workspace.id,
		});
	}),

	sendMessage: protectedProcedure
		.input(sendMessageInput)
		.mutation(async ({ ctx, input }) =>
			createMessageRunWithLaunch({
				db: ctx.db,
				input: {
					...input,
					workspaceId: input.workspaceId ?? input.projectId,
				},
				ownerId: ctx.session.user.id,
			}),
		),

	getRunEvents: protectedProcedure
		.input(runEventsInput)
		.query(async ({ ctx, input }) => {
			const run = await ctx.db
				.select({ id: agentRuns.id })
				.from(agentRuns)
				.innerJoin(workspaces, eq(agentRuns.workspaceId, workspaces.id))
				.where(
					and(
						eq(agentRuns.id, input.runId),
						eq(workspaces.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!run[0]) {
				return [];
			}

			const events = await getRunEventsAfter({
				afterSequence: input.afterSequence,
				db: ctx.db,
				runId: input.runId,
			});

			return events.map(mapEvent);
		}),

	answerQuestion: protectedProcedure
		.input(answerQuestionInput)
		.mutation(async ({ ctx, input }) => {
			const ownerId = ctx.session.user.id;
			const requestedWorkspaceId = input.workspaceId ?? input.projectId;
			const workspace = requestedWorkspaceId
				? await getWorkspaceCompatibilityPayload({
						db: ctx.db,
						ownerId,
						workspaceId: requestedWorkspaceId,
					})
				: null;
			const latestWorkspace = requestedWorkspaceId
				? null
				: await getLatestWorkspaceForOwner(ctx.db, ownerId);
			const workspacePayload =
				workspace ??
				(latestWorkspace
					? await getWorkspaceCompatibilityPayload({
							db: ctx.db,
							ownerId,
							workspaceId: latestWorkspace.id,
						})
					: null);

			return {
				answer: answerWorkspaceQuestion({
					question: input.question,
					workspace: workspacePayload,
				}),
			};
		}),

	createProjectRun: protectedProcedure
		.input(createProjectRunInput)
		.mutation(async ({ ctx, input }) =>
			createProjectRunWithLaunch({
				db: ctx.db,
				input,
				ownerId: ctx.session.user.id,
			}),
		),
});
