import { and, asc, eq } from "drizzle-orm";

import { env } from "@/env";
import { validateRunCompletion } from "@/server/agent/completion";
import { appendRunEvent } from "@/server/agent/events";
import { runCodexHarness } from "@/server/agent/harness-client";
import { runCifRetrievalPipeline } from "@/server/agent/retrieval-pipeline";
import { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	proteinCandidates,
} from "@/server/db/schema";

type AgentRun = typeof agentRuns.$inferSelect;
type AgentMode = "direct" | "codex";

type RunExecutorDeps = {
	appendRunEvent?: typeof appendRunEvent;
	agentMode?: AgentMode;
	db?: typeof appDb;
	logger?: Pick<typeof console, "error" | "log">;
	runCifRetrievalPipeline?: typeof runCifRetrievalPipeline;
	runCodexHarness?: typeof runCodexHarness;
	validateRunCompletion?: typeof validateRunCompletion;
	workerId?: string;
};

type ResolvedRunExecutorDeps = Required<
	Omit<RunExecutorDeps, "db" | "logger" | "workerId">
> & {
	db: typeof appDb;
	logger: Pick<typeof console, "error" | "log">;
	workerId: string;
};

type ClaimRunResult =
	| { run: AgentRun; status: "claimed" }
	| { run: AgentRun; status: "skipped" }
	| { run: null; status: "missing" };

const summarizeError = (error: unknown) =>
	error instanceof Error ? error.message : String(error);

const summarizeHarnessOutput = ({
	stderr,
	stdout,
}: {
	stderr: string;
	stdout: string;
}) => {
	const output = [stdout.trim(), stderr.trim()].filter(Boolean).join("\n\n");
	if (!output) {
		return "Codex completed without terminal output.";
	}

	return output.length > 1400 ? `${output.slice(0, 1400)}...` : output;
};

const resolveDeps = (deps: RunExecutorDeps = {}): ResolvedRunExecutorDeps => ({
	appendRunEvent: deps.appendRunEvent ?? appendRunEvent,
	agentMode: deps.agentMode ?? env.AUTOPEP_AGENT_MODE,
	db: deps.db ?? appDb,
	logger: deps.logger ?? console,
	runCifRetrievalPipeline:
		deps.runCifRetrievalPipeline ?? runCifRetrievalPipeline,
	runCodexHarness: deps.runCodexHarness ?? runCodexHarness,
	validateRunCompletion: deps.validateRunCompletion ?? validateRunCompletion,
	workerId:
		deps.workerId ?? process.env.AUTOPEP_WORKER_ID ?? `worker-${process.pid}`,
});

export const claimNextRun = async (
	deps: RunExecutorDeps = {},
): Promise<AgentRun | null> => {
	const { db, workerId } = resolveDeps(deps);
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

export const claimRunById = async (
	runId: string,
	deps: RunExecutorDeps = {},
): Promise<ClaimRunResult> => {
	const { db, workerId } = resolveDeps(deps);
	const [claimedRun] = await db
		.update(agentRuns)
		.set({
			claimedAt: new Date(),
			claimedBy: workerId,
			startedAt: new Date(),
			status: "running",
		})
		.where(and(eq(agentRuns.id, runId), eq(agentRuns.status, "queued")))
		.returning();

	if (claimedRun) {
		return { run: claimedRun, status: "claimed" };
	}

	const existingRun = await db.query.agentRuns.findFirst({
		where: eq(agentRuns.id, runId),
	});

	if (!existingRun) {
		return { run: null, status: "missing" };
	}

	return { run: existingRun, status: "skipped" };
};

export const executeClaimedRun = async (
	run: AgentRun,
	deps: RunExecutorDeps = {},
) => {
	const {
		appendRunEvent: appendEvent,
		agentMode,
		db,
		logger,
		runCifRetrievalPipeline: runDirectPipeline,
		runCodexHarness: runHarness,
		validateRunCompletion: validateCompletion,
	} = resolveDeps(deps);

	try {
		if (agentMode === "codex") {
			await appendEvent({
				db,
				detail: env.AUTOPEP_CODEX_MODEL,
				runId: run.id,
				title: "Codex agent started",
				type: "codex_agent_started",
			});

			try {
				const harnessResult = await runHarness({
					projectId: run.projectId,
					prompt: run.prompt,
					runId: run.id,
					topK: run.topK,
				});

				await appendEvent({
					db,
					detail: summarizeHarnessOutput(harnessResult),
					runId: run.id,
					title: "Codex agent finished",
					type: "codex_agent_finished",
				});
			} catch (error) {
				await appendEvent({
					db,
					detail: summarizeError(error),
					payload: {
						fallback: "deterministic_retrieval_pipeline",
					},
					runId: run.id,
					title: "Codex agent fallback",
					type: "codex_agent_fallback",
				});
			}

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
			const completion = validateCompletion({
				artifacts: artifactRows,
				candidates,
			});

			if (!completion.ok) {
				await appendEvent({
					db,
					detail: `Codex did not leave a ready CIF artifact. ${completion.reason}`,
					payload: {
						fallback: "deterministic_retrieval_pipeline",
					},
					runId: run.id,
					title: "Running retrieval pipeline",
					type: "codex_agent_fallback",
				});

				await runDirectPipeline({ db, runId: run.id });
				logger.log(`Completed run ${run.id}`);
				return true;
			}

			const existingReadyEvent = await db.query.agentEvents.findFirst({
				where: and(
					eq(agentEvents.runId, run.id),
					eq(agentEvents.type, "ready_for_proteina"),
				),
			});

			if (!existingReadyEvent) {
				await appendEvent({
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
			await runDirectPipeline({ db, runId: run.id });
		}

		logger.log(`Completed run ${run.id}`);
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
				await appendEvent({
					db,
					detail: errorSummary,
					runId: run.id,
					title: "CIF retrieval failed",
					type: "run_failed",
				});
			}
		} catch (eventError) {
			logger.error(
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

		logger.error(`Failed run ${run.id}: ${errorSummary}`);
		return false;
	}
};

export const runRunById = async (runId: string, deps: RunExecutorDeps = {}) => {
	const resolvedDeps = resolveDeps(deps);
	const claim = await claimRunById(runId, resolvedDeps);

	if (claim.status === "claimed") {
		return executeClaimedRun(claim.run, resolvedDeps);
	}

	if (claim.status === "missing") {
		throw new Error(`Agent run ${runId} was not found.`);
	}

	const detail = `Run is already ${claim.run.status}; no sandbox work started.`;
	resolvedDeps.logger.log(`Skipped run ${runId}: ${detail}`);

	try {
		await resolvedDeps.appendRunEvent({
			db: resolvedDeps.db,
			detail,
			runId,
			title: "Run start skipped",
			type: "run_start_skipped",
		});
	} catch (error) {
		resolvedDeps.logger.error(
			`Failed to persist duplicate-start event for run ${runId}: ${summarizeError(
				error,
			)}`,
		);
	}

	return false;
};

export const runOnce = async (deps: RunExecutorDeps = {}) => {
	const resolvedDeps = resolveDeps(deps);
	const run = await claimNextRun(resolvedDeps);

	if (!run) {
		resolvedDeps.logger.log("No queued runs.");
		return false;
	}

	return executeClaimedRun(run, resolvedDeps);
};

const sleep = (ms: number) =>
	new Promise((resolve) => {
		setTimeout(resolve, ms);
	});

export const runLoop = async (deps: RunExecutorDeps = {}) => {
	while (true) {
		const didWork = await runOnce(deps);
		await sleep(didWork ? 500 : 3000);
	}
};
