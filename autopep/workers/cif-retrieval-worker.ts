import { and, asc, eq } from "drizzle-orm";

import { env } from "@/env";
import { validateRunCompletion } from "@/server/agent/completion";
import { appendRunEvent } from "@/server/agent/events";
import { runCodexHarness } from "@/server/agent/harness-client";
import { runCifRetrievalPipeline } from "@/server/agent/retrieval-pipeline";
import { db } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	proteinCandidates,
} from "@/server/db/schema";

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

			const [candidates, artifactRows] = await Promise.all([
				db
					.select({
						id: proteinCandidates.id,
						proteinaReady: proteinCandidates.proteinaReady,
						rank: proteinCandidates.rank,
					})
					.from(proteinCandidates)
					.where(eq(proteinCandidates.runId, run.id)),
				db
					.select({
						candidateId: artifacts.candidateId,
						id: artifacts.id,
						type: artifacts.type,
					})
					.from(artifacts)
					.where(eq(artifacts.runId, run.id)),
			]);
			const completion = validateRunCompletion({
				artifacts: artifactRows,
				candidates,
			});

			if (!completion.ok) {
				throw new Error(
					`Codex harness finished without a ready CIF artifact. ${completion.reason}`,
				);
			}

			const existingReadyEvent = await db.query.agentEvents.findFirst({
				where: and(
					eq(agentEvents.runId, run.id),
					eq(agentEvents.type, "ready_for_proteina"),
				),
			});

			if (!existingReadyEvent) {
				await appendRunEvent({
					db,
					detail: `Ready CIF artifact ${completion.selectedArtifactId} is available.`,
					payload: {
						artifactId: completion.selectedArtifactId,
						candidateId: completion.selectedCandidateId,
					},
					runId: run.id,
					title: "Ready for Proteina",
					type: "ready_for_proteina",
				});
			}

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

		try {
			const existingFailureEvent = await db.query.agentEvents.findFirst({
				where: and(
					eq(agentEvents.runId, run.id),
					eq(agentEvents.type, "run_failed"),
				),
			});

			if (!existingFailureEvent) {
				await appendRunEvent({
					db,
					detail: errorSummary,
					runId: run.id,
					title: "CIF retrieval failed",
					type: "run_failed",
				});
			}
		} catch (eventError) {
			console.error(
				`Failed to persist failure event for run ${run.id}: ${summarizeError(
					eventError,
				)}`,
			);
		}

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
