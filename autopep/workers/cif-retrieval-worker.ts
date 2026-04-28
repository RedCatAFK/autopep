import { and, asc, eq } from "drizzle-orm";

import { env } from "@/env";
import { runCodexHarness } from "@/server/agent/harness-client";
import { runCifRetrievalPipeline } from "@/server/agent/retrieval-pipeline";
import { db } from "@/server/db";
import { agentRuns } from "@/server/db/schema";

const workerId = process.env.AUTOPEP_WORKER_ID ?? `worker-${process.pid}`;
const runOnceOnly = process.argv.includes("--once");
let lastRunClaimedWork = false;

const sleep = (ms: number) =>
	new Promise((resolve) => {
		setTimeout(resolve, ms);
	});

const summarizeError = (error: unknown) =>
	error instanceof Error ? error.message : String(error);

export const claimNextRun = async () => {
	const queuedRun = await db.query.agentRuns.findFirst({
		where: eq(agentRuns.status, "queued"),
		orderBy: [asc(agentRuns.createdAt)],
	});

	if (!queuedRun) {
		return null;
	}

	const [claimedRun] = await db
		.update(agentRuns)
		.set({
			claimedAt: new Date(),
			claimedBy: workerId,
			startedAt: new Date(),
			status: "running",
		})
		.where(and(eq(agentRuns.id, queuedRun.id), eq(agentRuns.status, "queued")))
		.returning();

	return claimedRun ?? null;
};

export const runOnce = async () => {
	const run = await claimNextRun();
	lastRunClaimedWork = !!run;

	if (!run) {
		console.log("No queued runs.");
		return false;
	}

	try {
		if (env.AUTOPEP_AGENT_MODE === "codex") {
			await runCodexHarness({
				projectId: run.projectId,
				prompt: run.prompt,
				runId: run.id,
				topK: run.topK,
			});

			await db
				.update(agentRuns)
				.set({
					finishedAt: new Date(),
					status: "succeeded",
				})
				.where(eq(agentRuns.id, run.id));
		} else {
			await runCifRetrievalPipeline({ db, runId: run.id });
		}

		console.log(`Completed run ${run.id}`);
		return true;
	} catch (error) {
		const errorSummary = summarizeError(error);

		await db
			.update(agentRuns)
			.set({
				errorSummary,
				finishedAt: new Date(),
				status: "failed",
			})
			.where(eq(agentRuns.id, run.id));

		console.error(`Failed run ${run.id}: ${errorSummary}`);
		return false;
	}
};

const runLoop = async () => {
	while (true) {
		await runOnce();
		await sleep(lastRunClaimedWork ? 500 : 3000);
	}
};

if (runOnceOnly) {
	await runOnce();
	process.exit(0);
}

await runLoop();
