import { eq } from "drizzle-orm";

import { env } from "@/env";
import { appendRunEvent } from "@/server/agent/events";
import { startModalRun } from "@/server/agent/modal-launcher";
import type { db as appDb } from "@/server/db";
import { agentRuns } from "@/server/db/schema";

type LaunchCreatedRunInput = {
	appendRunEvent?: typeof appendRunEvent;
	db: typeof appDb;
	runId: string;
	startModalRun?: typeof startModalRun;
	threadId: string;
	workspaceId: string;
};

const summarizeError = (error: unknown) =>
	error instanceof Error ? error.message : String(error);

export const launchCreatedRun = async ({
	appendRunEvent: appendEvent = appendRunEvent,
	db,
	runId,
	startModalRun: startRun = startModalRun,
	threadId,
	workspaceId,
}: LaunchCreatedRunInput) => {
	if (env.AUTOPEP_RUNNER_BACKEND === "local") {
		return { backend: "local" as const, launched: false as const };
	}

	try {
		await startRun({ runId, threadId, workspaceId });
		return { backend: "modal" as const, launched: true as const };
	} catch (error) {
		const errorSummary = summarizeError(error);

		const [failedRun] = await db
			.update(agentRuns)
			.set({
				errorSummary,
				finishedAt: new Date(),
				status: "failed",
			})
			.where(eq(agentRuns.id, runId))
			.returning();

		await appendEvent({
			db,
			detail: errorSummary,
			runId,
			title: "Modal launch failed",
			type: "run_failed",
		});

		return {
			backend: "modal" as const,
			errorSummary,
			launched: false as const,
			run: failedRun,
		};
	}
};
