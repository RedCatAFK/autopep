import { launchCreatedRun } from "@/server/agent/run-launcher";
import type { db as appDb } from "@/server/db";
import { agentRuns, projects } from "@/server/db/schema";

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
	const [project] = await db
		.insert(projects)
		.values({
			ownerId,
			name: input.name ?? input.goal.slice(0, 120),
			goal: input.goal,
		})
		.returning();

	if (!project) {
		throw new Error("Failed to create project");
	}

	const [run] = await db
		.insert(agentRuns)
		.values({
			projectId: project.id,
			createdById: ownerId,
			prompt: input.goal,
			status: "queued",
			topK: input.topK,
		})
		.returning();

	if (!run) {
		throw new Error("Failed to create agent run");
	}

	const launch = await launchRun({
		db,
		projectId: project.id,
		runId: run.id,
	});

	return { project, run: launch.run ?? run };
};
