import { and, asc, desc, eq, gt, inArray, isNull } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	contextReferences,
	proteinCandidates,
	recipes,
	threadItems,
	threads,
	workspaces,
} from "@/server/db/schema";

type Db = typeof appDb;

type CreateWorkspaceWithThreadInput = {
	db: Db;
	description?: string | null;
	name: string;
	ownerId: string;
};

type WorkspacePayloadInput = {
	db: Db;
	ownerId: string;
	workspaceId: string;
};

type RunEventsAfterInput = {
	afterSequence: number;
	db: Db;
	runId: string;
};

export const listWorkspacesForOwner = (db: Db, ownerId: string) =>
	db.query.workspaces.findMany({
		where: and(eq(workspaces.ownerId, ownerId), isNull(workspaces.archivedAt)),
		orderBy: [desc(workspaces.updatedAt)],
	});

export const createWorkspaceWithThread = async ({
	db,
	description = null,
	name,
	ownerId,
}: CreateWorkspaceWithThreadInput) => {
	const [workspace] = await db
		.insert(workspaces)
		.values({ description, name, ownerId })
		.returning();

	if (!workspace) {
		throw new Error("Failed to create workspace.");
	}

	const [thread] = await db
		.insert(threads)
		.values({ title: "Main thread", workspaceId: workspace.id })
		.returning();

	if (!thread) {
		throw new Error("Failed to create thread.");
	}

	const [updatedWorkspace] = await db
		.update(workspaces)
		.set({ activeThreadId: thread.id })
		.where(eq(workspaces.id, workspace.id))
		.returning();

	return {
		thread,
		workspace: updatedWorkspace ?? workspace,
	};
};

export const getWorkspacePayload = async ({
	db,
	ownerId,
	workspaceId,
}: WorkspacePayloadInput) => {
	const workspace = await db.query.workspaces.findFirst({
		where: and(
			eq(workspaces.id, workspaceId),
			eq(workspaces.ownerId, ownerId),
			isNull(workspaces.archivedAt),
		),
	});

	if (!workspace) {
		return null;
	}

	const threadRows = await db.query.threads.findMany({
		where: eq(threads.workspaceId, workspace.id),
		orderBy: [desc(threads.updatedAt)],
	});
	const activeThread =
		threadRows.find((thread) => thread.id === workspace.activeThreadId) ??
		threadRows[0] ??
		null;
	const runRows = activeThread
		? await db.query.agentRuns.findMany({
				where: and(
					eq(agentRuns.workspaceId, workspace.id),
					eq(agentRuns.threadId, activeThread.id),
				),
				orderBy: [desc(agentRuns.createdAt)],
				limit: 20,
			})
		: [];
	const activeRun = runRows[0] ?? null;

	const [
		messageRows,
		eventRows,
		artifactRows,
		candidateRows,
		scoreRows,
		recipeRows,
		contextRows,
	] = await Promise.all([
		activeThread
			? db.query.threadItems.findMany({
					where: and(
						eq(threadItems.threadId, activeThread.id),
						eq(threadItems.itemType, "message"),
						inArray(threadItems.role, ["user", "assistant"]),
					),
					orderBy: [asc(threadItems.sequence)],
				})
			: Promise.resolve([]),
		activeRun
			? db.query.agentEvents.findMany({
					where: eq(agentEvents.runId, activeRun.id),
					orderBy: [asc(agentEvents.sequence)],
				})
			: Promise.resolve([]),
		db.query.artifacts.findMany({
			where: eq(artifacts.workspaceId, workspace.id),
			orderBy: [desc(artifacts.createdAt)],
		}),
		db.query.proteinCandidates.findMany({
			where: eq(proteinCandidates.workspaceId, workspace.id),
			orderBy: [asc(proteinCandidates.rank)],
		}),
		activeRun
			? db.query.candidateScores.findMany({
					where: eq(candidateScores.runId, activeRun.id),
					orderBy: [asc(candidateScores.createdAt)],
				})
			: Promise.resolve([]),
		db.query.recipes.findMany({
			where: and(
				eq(recipes.workspaceId, workspace.id),
				isNull(recipes.archivedAt),
			),
			orderBy: [asc(recipes.name)],
		}),
		db.query.contextReferences.findMany({
			where: eq(contextReferences.workspaceId, workspace.id),
			orderBy: [desc(contextReferences.createdAt)],
		}),
	]);

	return {
		activeRun,
		activeThread,
		artifacts: artifactRows,
		candidateScores: scoreRows,
		candidates: candidateRows,
		contextReferences: contextRows,
		events: eventRows,
		messages: messageRows,
		recipes: recipeRows,
		runs: runRows,
		threads: threadRows,
		workspace,
	};
};

export const getRunEventsAfter = ({
	afterSequence,
	db,
	runId,
}: RunEventsAfterInput) =>
	db.query.agentEvents.findMany({
		where: and(
			eq(agentEvents.runId, runId),
			gt(agentEvents.sequence, afterSequence),
		),
		orderBy: [asc(agentEvents.sequence)],
	});
