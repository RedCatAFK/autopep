import { and, asc, desc, eq, gt } from "drizzle-orm";
import { z } from "zod";

import { createProjectRunWithLaunch } from "@/server/agent/project-run-creator";
import { answerWorkspaceQuestion } from "@/server/agent/workspace-answer";
import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	proteinCandidates,
	workspaces,
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

const answerQuestionInput = z.object({
	projectId: z.string().uuid().optional(),
	question: z.string().min(1).max(1000),
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
		where: eq(workspaces.ownerId, ownerId),
		orderBy: [desc(workspaces.createdAt)],
	});

export const getWorkspacePayload = async (
	db: Db,
	projectId: string,
	ownerId: string,
) => {
	const workspace = await db.query.workspaces.findFirst({
		where: and(eq(workspaces.id, projectId), eq(workspaces.ownerId, ownerId)),
	});

	if (!workspace) {
		return null;
	}

	const runs = await db.query.agentRuns.findMany({
		where: eq(agentRuns.workspaceId, workspace.id),
		orderBy: [desc(agentRuns.createdAt)],
		limit: 10,
	});

	const activeRun = runs[0] ?? null;
	const project = mapWorkspaceToProject(workspace, activeRun);

	if (!activeRun) {
		return {
			activeRun,
			artifacts: [],
			candidates: [],
			events: [],
			project,
			runs,
			targetEntities: [],
			workspace,
		};
	}

	const [eventRows, candidateRows, artifactRows] = await Promise.all([
		db.query.agentEvents.findMany({
			where: eq(agentEvents.runId, activeRun.id),
			orderBy: [asc(agentEvents.sequence)],
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

	const targetEntities = [
		{
			name: inferTargetName(activeRun.prompt),
			organism: activeRun.prompt.toLowerCase().includes("sars-cov-2")
				? "SARS-CoV-2"
				: null,
		},
	];

	return {
		activeRun,
		artifacts: await Promise.all(artifactRows.map(mapArtifact)),
		candidates: candidateRows.map(mapCandidate),
		events: eventRows.map(mapEvent),
		project,
		runs,
		targetEntities,
		workspace,
	};
};

export const workspaceRouter = createTRPCRouter({
	answerQuestion: protectedProcedure
		.input(answerQuestionInput)
		.mutation(async ({ ctx, input }) => {
			const ownerId = ctx.session.user.id;
			const workspace = input.projectId
				? await ctx.db.query.workspaces.findFirst({
						where: and(
							eq(workspaces.id, input.projectId),
							eq(workspaces.ownerId, ownerId),
						),
					})
				: await getLatestWorkspaceForOwner(ctx.db, ownerId);
			const workspacePayload = workspace
				? await getWorkspacePayload(ctx.db, workspace.id, ownerId)
				: null;

			return {
				answer: answerWorkspaceQuestion({
					question: input.question,
					workspace: workspacePayload,
				}),
			};
		}),

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
		const workspace = await getLatestWorkspaceForOwner(
			ctx.db,
			ctx.session.user.id,
		);

		if (!workspace) {
			return null;
		}

		return getWorkspacePayload(ctx.db, workspace.id, ctx.session.user.id);
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

			const events = await ctx.db.query.agentEvents.findMany({
				where: and(
					eq(agentEvents.runId, input.runId),
					gt(agentEvents.sequence, input.afterSequence),
				),
				orderBy: [asc(agentEvents.sequence)],
			});

			return events.map(mapEvent);
		}),
});
