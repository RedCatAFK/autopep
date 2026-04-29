import { eq } from "drizzle-orm";

import { launchCreatedRun } from "@/server/agent/run-launcher";
import type { db as appDb } from "@/server/db";
import { agentRuns, messages, threads, workspaces } from "@/server/db/schema";

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

export const createProjectRunWithLaunch = async ({
	db,
	input,
	launchRun = launchCreatedRun,
	ownerId,
}: CreateProjectRunWithLaunchInput) => {
	const [workspace] = await db
		.insert(workspaces)
		.values({
			ownerId,
			name: input.name ?? input.goal.slice(0, 120),
			description: input.goal,
		})
		.returning();

	if (!workspace) {
		throw new Error("Failed to create workspace");
	}

	const [thread] = await db
		.insert(threads)
		.values({
			title: input.name ?? input.goal.slice(0, 120),
			workspaceId: workspace.id,
		})
		.returning();

	if (!thread) {
		throw new Error("Failed to create thread");
	}

	await db
		.update(workspaces)
		.set({ activeThreadId: thread.id })
		.where(eq(workspaces.id, workspace.id));

	const [run] = await db
		.insert(agentRuns)
		.values({
			createdById: ownerId,
			prompt: input.goal,
			sdkStateJson: { requestedTopK: input.topK },
			status: "queued",
			taskKind: "structure_search",
			threadId: thread.id,
			workspaceId: workspace.id,
		})
		.returning();

	if (!run) {
		throw new Error("Failed to create agent run");
	}

	const [message] = await db
		.insert(messages)
		.values({
			content: input.goal,
			role: "user",
			runId: run.id,
			threadId: thread.id,
		})
		.returning();

	if (!message) {
		throw new Error("Failed to create message");
	}

	const launch = await launchRun({
		db,
		projectId: workspace.id,
		runId: run.id,
	});

	return {
		message,
		project: workspace,
		run: launch.run ?? run,
		thread,
		workspace,
	};
};
