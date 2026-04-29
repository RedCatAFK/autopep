import { and, desc, eq, isNull } from "drizzle-orm";

import { env } from "@/env";
import { launchCreatedRun } from "@/server/agent/run-launcher";
import type { db as appDb } from "@/server/db";
import {
	agentRuns,
	messages,
	recipeVersions,
	recipes,
	runRecipes,
	threads,
	workspaces,
} from "@/server/db/schema";
import { createWorkspaceWithThread } from "@/server/workspaces/repository";

type AgentRunInsert = typeof agentRuns.$inferInsert;
type TaskKind = NonNullable<AgentRunInsert["taskKind"]>;

type CreateMessageRunInput = {
	attachmentRefs?: string[];
	contextRefs?: string[];
	description?: string | null;
	name?: string;
	prompt: string;
	recipeRefs?: string[];
	sdkStateJson?: Record<string, unknown>;
	taskKind?: TaskKind;
	threadId?: string;
	workspaceId?: string;
};

type WorkspaceBundle = {
	thread: typeof threads.$inferSelect;
	workspace: typeof workspaces.$inferSelect;
};

type CreateMessageRunWithLaunchInput = {
	db: typeof appDb;
	input: CreateMessageRunInput;
	launchRun?: typeof launchCreatedRun;
	ownerId: string;
};

type CreateProjectRunInput = {
	goal: string;
	name?: string;
	topK: number;
};

type CreateProjectRunWithLaunchInput = {
	db: typeof appDb;
	input: CreateProjectRunInput;
	launchRun?: typeof launchCreatedRun;
	ownerId: string;
};

type DbWithOptionalTransaction = typeof appDb & {
	transaction?: <T>(callback: (tx: typeof appDb) => Promise<T>) => Promise<T>;
};

const inferWorkspaceName = (prompt: string) => {
	const firstLine = prompt.trim().split(/\r?\n/u)[0]?.trim();
	const name = firstLine || "Untitled workspace";
	return name.length > 120 ? name.slice(0, 120) : name;
};

const createThreadForWorkspace = async ({
	db,
	workspace,
}: {
	db: typeof appDb;
	workspace: typeof workspaces.$inferSelect;
}) => {
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

const insertRunRecipes = async ({
	db,
	ownerId,
	recipeRefs,
	runId,
}: {
	db: typeof appDb;
	ownerId: string;
	recipeRefs: string[];
	runId: string;
}) => {
	for (const recipeId of recipeRefs) {
		const recipe = await db.query.recipes.findFirst({
			where: and(eq(recipes.id, recipeId), eq(recipes.ownerId, ownerId)),
		});
		if (!recipe) {
			continue;
		}

		const latestVersion = await db.query.recipeVersions.findFirst({
			where: eq(recipeVersions.recipeId, recipe.id),
			orderBy: [desc(recipeVersions.version)],
		});
		if (!latestVersion) {
			continue;
		}

		await db.insert(runRecipes).values({
			bodySnapshot: latestVersion.bodyMarkdown,
			nameSnapshot: recipe.name,
			recipeId: recipe.id,
			recipeVersionId: latestVersion.id,
			runId,
		});
	}
};

const ensureOwnedWorkspace = async ({
	db,
	ownerId,
	threadId,
	workspaceId,
}: {
	db: typeof appDb;
	ownerId: string;
	threadId?: string;
	workspaceId: string;
}): Promise<WorkspaceBundle> => {
	const workspace = await db.query.workspaces.findFirst({
		where: and(
			eq(workspaces.id, workspaceId),
			eq(workspaces.ownerId, ownerId),
			isNull(workspaces.archivedAt),
		),
	});

	if (!workspace) {
		throw new Error("Workspace not found.");
	}

	const preferredThreadId = threadId ?? workspace.activeThreadId;
	const thread = preferredThreadId
		? await db.query.threads.findFirst({
				where: and(
					eq(threads.id, preferredThreadId),
					eq(threads.workspaceId, workspace.id),
				),
			})
		: await db.query.threads.findFirst({
				where: eq(threads.workspaceId, workspace.id),
				orderBy: [desc(threads.updatedAt)],
			});

	if (thread) {
		return { thread, workspace };
	}

	return createThreadForWorkspace({ db, workspace });
};

export const createMessageRunWithLaunch = async ({
	db,
	input,
	launchRun = launchCreatedRun,
	ownerId,
}: CreateMessageRunWithLaunchInput) => {
	const createRows = async (writeDb: typeof appDb) => {
		const workspaceBundle = input.workspaceId
			? await ensureOwnedWorkspace({
					db: writeDb,
					ownerId,
					threadId: input.threadId,
					workspaceId: input.workspaceId,
				})
			: await createWorkspaceWithThread({
					db: writeDb,
					description: input.description ?? null,
					name: input.name ?? inferWorkspaceName(input.prompt),
					ownerId,
				});

		const [run] = await writeDb
			.insert(agentRuns)
			.values({
				createdById: ownerId,
				model: env.OPENAI_DEFAULT_MODEL,
				prompt: input.prompt,
				rootRunId: null,
				sdkStateJson: input.sdkStateJson ?? {},
				status: "queued",
				taskKind: input.taskKind ?? "chat",
				threadId: workspaceBundle.thread.id,
				workspaceId: workspaceBundle.workspace.id,
			})
			.returning();

		if (!run) {
			throw new Error("Failed to create agent run.");
		}

		const [message] = await writeDb
			.insert(messages)
			.values({
				attachmentRefsJson: input.attachmentRefs ?? [],
				content: input.prompt,
				contextRefsJson: input.contextRefs ?? [],
				recipeRefsJson: input.recipeRefs ?? [],
				role: "user",
				runId: run.id,
				threadId: workspaceBundle.thread.id,
			})
			.returning();

		if (!message) {
			throw new Error("Failed to create user message.");
		}

		await insertRunRecipes({
			db: writeDb,
			ownerId,
			recipeRefs: input.recipeRefs ?? [],
			runId: run.id,
		});

		return {
			message,
			run,
			thread: workspaceBundle.thread,
			workspace: workspaceBundle.workspace,
		};
	};

	const dbWithTransaction = db as DbWithOptionalTransaction;
	const created = dbWithTransaction.transaction
		? await dbWithTransaction.transaction(async (tx) =>
				createRows(tx as unknown as typeof appDb),
			)
		: await createRows(db);

	const launch = await launchRun({
		db,
		runId: created.run.id,
		threadId: created.thread.id,
		workspaceId: created.workspace.id,
	});

	return {
		message: created.message,
		run: launch.run ?? created.run,
		thread: created.thread,
		workspace: created.workspace,
	};
};

export const createProjectRunWithLaunch = async ({
	db,
	input,
	launchRun = launchCreatedRun,
	ownerId,
}: CreateProjectRunWithLaunchInput) => {
	const result = await createMessageRunWithLaunch({
		db,
		input: {
			description: input.goal,
			name: input.name,
			prompt: input.goal,
			sdkStateJson: { requestedTopK: input.topK },
			taskKind: "structure_search",
		},
		launchRun,
		ownerId,
	});

	return {
		...result,
		project: result.workspace,
	};
};
