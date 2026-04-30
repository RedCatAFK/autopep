import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { pathToFileURL } from "node:url";

import { asc, eq } from "drizzle-orm";

import { createMessageRunWithLaunch } from "@/server/agent/project-run-creator";
import { db } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	modelInferences,
	proteinCandidates,
	threadItems,
	user,
	workspaces,
} from "@/server/db/schema";

export const LIVE_CANARY_REQUIRED_TOOLS = [
	"literature_search",
	"pdb_search",
	"pdb_fetch",
	"proteina_design",
	"chai_fold_complex",
	"score_candidates",
] as const;

const DEFAULT_TIMEOUT_MS = 45 * 60 * 1000;
const DEFAULT_MAX_TOTAL_MS = 45 * 60 * 1000;
const DEFAULT_POLL_INTERVAL_MS = 5000;

export type LiveCanaryDefinition = {
	expectedPdbIds: string[];
	id: string;
	target: string;
};

export const DEFAULT_LIVE_CANARIES: LiveCanaryDefinition[] = [
	{
		expectedPdbIds: ["6LU7", "7BQY", "6M2N"],
		id: "sars-cov-2-3clpro",
		target: "SARS-CoV-2 3CL main protease",
	},
	{
		expectedPdbIds: ["5J89", "4ZQK", "5C3T"],
		id: "pd-l1",
		target: "human PD-L1 extracellular domain",
	},
	{
		expectedPdbIds: ["6M0J", "6LZG", "7A98"],
		id: "ace2",
		target: "human ACE2 peptidase domain",
	},
];

export type CleanupMode = "always" | "never" | "success";

export type LiveCanaryThresholds = {
	allowFailedInferences: boolean;
	maxTotalMs: number;
	minArtifacts: number;
	minCandidates: number;
	minOkScoreRows: number;
	minScoreRows: number;
	requireCitation: boolean;
	requireExpectedPdbHit: boolean;
	timeoutMs: number;
};

export type CanaryEventRow = {
	createdAt?: Date;
	displayJson?: Record<string, unknown> | null;
	sequence: number;
	type: string;
};

export type CanaryArtifactRow = {
	kind: string;
	metadataJson?: Record<string, unknown> | null;
	name: string;
	storageKey: string;
};

export type CanaryCandidateRow = {
	id: string;
	rank: number;
	sequence?: string | null;
	title: string;
};

export type CanaryScoreRow = {
	scorer: string;
	status: string;
	value?: number | null;
};

export type CanaryInferenceRow = {
	errorSummary?: string | null;
	modelName: string;
	status: string;
};

export type CanaryThreadItemRow = {
	contentJson?: unknown;
	itemType: string;
	role?: string | null;
	sequence: number;
};

export type CanarySnapshot = {
	artifacts: CanaryArtifactRow[];
	candidates: CanaryCandidateRow[];
	events: CanaryEventRow[];
	inferences: CanaryInferenceRow[];
	run: {
		errorSummary?: string | null;
		finishedAt?: Date | null;
		id: string;
		startedAt?: Date | null;
		status: string;
	};
	scores: CanaryScoreRow[];
	threadItems: CanaryThreadItemRow[];
};

export type CanaryEvaluation = {
	failures: string[];
	metrics: Record<string, unknown>;
	passed: boolean;
	warnings: string[];
};

type LiveCanaryConfig = {
	canaryIds: string[];
	cleanup: CleanupMode;
	outputPath?: string;
	pollIntervalMs: number;
	target: "local" | "prod";
	thresholds: LiveCanaryThresholds;
};

type CompletedCanaryResult = {
	definition: LiveCanaryDefinition;
	evaluation: CanaryEvaluation;
	prompt: string;
	runId?: string;
	threadId?: string;
	totalMs: number;
	workspaceId?: string;
};

type RunCanaryResult = CompletedCanaryResult & {
	cleanedUp: boolean;
};

const asBoolean = (value: string | undefined, fallback: boolean) => {
	if (value == null || value === "") {
		return fallback;
	}
	return ["1", "true", "yes", "on"].includes(value.toLowerCase());
};

const asInt = (value: string | undefined, fallback: number) => {
	if (value == null || value === "") {
		return fallback;
	}
	const parsed = Number.parseInt(value, 10);
	return Number.isFinite(parsed) ? parsed : fallback;
};

const parseCsv = (value: string | undefined) =>
	(value ?? "")
		.split(",")
		.map((part) => part.trim())
		.filter(Boolean);

export function buildCanaryPrompt(definition: LiveCanaryDefinition) {
	return [
		`Live science canary for ${definition.target}.`,
		"",
		"Run one bounded computational binder-screening pass only:",
		"1. literature_search for primary/structure evidence, max_results=3.",
		"2. pdb_search for the target, top_k=3, max_chain_length=700.",
		"3. pdb_fetch one relevant target PDB and use the returned chain sequence.",
		"4. proteina_design with num_candidates=3, binder_length_min=45, binder_length_max=70.",
		"5. chai_fold_complex for every generated candidate_id.",
		"6. score_candidates for every folded candidate.",
		"",
		"Do not run extra Proteina batches or open-ended iterations. Finish with a concise ranked table that includes candidate ids, PDB id, artifact ids, D-SCRIPT, PRODIGY, available quality scores, and citation identifiers (DOI or PubMed when available). Use computational-screening language only.",
	].join("\n");
}

const getDisplay = (event: CanaryEventRow) => event.displayJson ?? {};

const getCallId = (event: CanaryEventRow) => {
	const display = getDisplay(event);
	const callId = display.callId ?? display.call_id ?? display.toolCallId;
	return typeof callId === "string" ? callId : null;
};

const getToolName = (event: CanaryEventRow) => {
	const display = getDisplay(event);
	const name = display.name;
	return typeof name === "string" ? name : null;
};

const findCompletedTool = (
	events: CanaryEventRow[],
	startIndex: number,
	toolName: string,
) => {
	const started = events[startIndex];
	const callId = started ? getCallId(started) : null;
	for (let index = startIndex + 1; index < events.length; index++) {
		const event = events[index];
		if (!event || event.type !== "tool_call_completed") {
			continue;
		}
		if (callId && getCallId(event) === callId) {
			return index;
		}
		if (!callId && getToolName(event) === toolName) {
			return index;
		}
	}
	return null;
};

const evaluateTrace = (events: CanaryEventRow[]) => {
	const failures: string[] = [];
	const toolPositions: Record<
		string,
		{ completed: number | null; started: number | null }
	> = {};
	const eventTypes = events.map((event) => event.type);

	if (!eventTypes.includes("run_started")) {
		failures.push("missing run_started event");
	}
	if (!eventTypes.includes("run_completed")) {
		failures.push("missing run_completed event");
	}
	if (eventTypes.includes("run_failed")) {
		failures.push("trace contains run_failed event");
	}

	let previousStart: number | null = null;
	for (const tool of LIVE_CANARY_REQUIRED_TOOLS) {
		const startIndex = events.findIndex(
			(event) =>
				event.type === "tool_call_started" && getToolName(event) === tool,
		);
		const completedIndex =
			startIndex >= 0 ? findCompletedTool(events, startIndex, tool) : null;
		toolPositions[tool] = {
			completed: completedIndex,
			started: startIndex >= 0 ? startIndex : null,
		};

		if (startIndex < 0) {
			failures.push(`missing tool_call_started for ${tool}`);
			continue;
		}
		if (completedIndex == null) {
			failures.push(`missing tool_call_completed for ${tool}`);
		}
		if (previousStart != null && startIndex < previousStart) {
			failures.push(`${tool} started before prior required tool`);
		}
		previousStart = startIndex;
	}

	return {
		failures,
		metrics: {
			requiredToolCount: LIVE_CANARY_REQUIRED_TOOLS.length,
			requiredToolsCompleted: Object.values(toolPositions).filter(
				(position) => position.started != null && position.completed != null,
			).length,
			toolPositions,
		},
	};
};

const contentText = (value: unknown): string => {
	if (typeof value === "string") {
		return value;
	}
	if (Array.isArray(value)) {
		return value.map(contentText).filter(Boolean).join("\n");
	}
	if (value && typeof value === "object") {
		const record = value as Record<string, unknown>;
		if (typeof record.text === "string") {
			return record.text;
		}
		if (typeof record.content === "string") {
			return record.content;
		}
		if (Array.isArray(record.content)) {
			return contentText(record.content);
		}
		if (Array.isArray(record.output)) {
			return contentText(record.output);
		}
	}
	return "";
};

const latestAssistantText = (items: CanaryThreadItemRow[]) => {
	const assistantItems = items
		.filter((item) => item.itemType === "message" && item.role === "assistant")
		.sort((a, b) => a.sequence - b.sequence);
	const latest = assistantItems.at(-1);
	return latest ? contentText(latest.contentJson) : "";
};

const artifactPdbIds = (artifactsRows: CanaryArtifactRow[]) =>
	artifactsRows
		.map((artifact) => artifact.metadataJson?.pdbId)
		.filter((value): value is string => typeof value === "string")
		.map((value) => value.toUpperCase());

const eventPdbIds = (eventRows: CanaryEventRow[]) =>
	eventRows
		.map((event) => getDisplay(event).pdbId)
		.filter((value): value is string => typeof value === "string")
		.map((value) => value.toUpperCase());

const hasCitationLikeText = (text: string) =>
	/(doi\.org|doi\s*:|pubmed|pmid|10\.\d{4,9}\/)/iu.test(text);

const hasScoreLikeText = (text: string) =>
	/(d-?script|prodigy|solubility|score|Δg|delta\s*g|kcal\/mol)/iu.test(text);

export function evaluateCanarySnapshot({
	definition,
	snapshot,
	thresholds,
	totalMs,
}: {
	definition: LiveCanaryDefinition;
	snapshot: CanarySnapshot;
	thresholds: LiveCanaryThresholds;
	totalMs: number;
}): CanaryEvaluation {
	const failures: string[] = [];
	const warnings: string[] = [];

	if (snapshot.run.status !== "completed") {
		failures.push(
			`run status is ${snapshot.run.status}: ${snapshot.run.errorSummary ?? "no error summary"}`,
		);
	}
	if (totalMs > thresholds.maxTotalMs) {
		failures.push(
			`run latency ${totalMs}ms exceeded maxTotalMs ${thresholds.maxTotalMs}ms`,
		);
	}

	const sortedEvents = [...snapshot.events].sort(
		(a, b) => a.sequence - b.sequence,
	);
	for (const [index, event] of sortedEvents.entries()) {
		const expected = index + 1;
		if (event.sequence !== expected) {
			failures.push(
				`event sequence gap: expected ${expected}, got ${event.sequence}`,
			);
			break;
		}
	}

	const trace = evaluateTrace(sortedEvents);
	failures.push(...trace.failures);

	const artifactsByKind = snapshot.artifacts.reduce<Record<string, number>>(
		(acc, artifact) => {
			acc[artifact.kind] = (acc[artifact.kind] ?? 0) + 1;
			return acc;
		},
		{},
	);
	if (snapshot.artifacts.length < thresholds.minArtifacts) {
		failures.push(
			`expected at least ${thresholds.minArtifacts} artifacts, saw ${snapshot.artifacts.length}`,
		);
	}
	for (const kind of ["pdb", "proteina_result", "chai_result"]) {
		if (!artifactsByKind[kind]) {
			failures.push(`missing ${kind} artifact`);
		}
	}

	if (snapshot.candidates.length < thresholds.minCandidates) {
		failures.push(
			`expected at least ${thresholds.minCandidates} candidates, saw ${snapshot.candidates.length}`,
		);
	}

	const okScores = snapshot.scores.filter((score) => score.status === "ok");
	const scorers = Array.from(
		new Set(snapshot.scores.map((score) => score.scorer)),
	).sort();
	if (snapshot.scores.length < thresholds.minScoreRows) {
		failures.push(
			`expected at least ${thresholds.minScoreRows} score rows, saw ${snapshot.scores.length}`,
		);
	}
	if (okScores.length < thresholds.minOkScoreRows) {
		failures.push(
			`expected at least ${thresholds.minOkScoreRows} ok score rows, saw ${okScores.length}`,
		);
	}
	if (!scorers.some((scorer) => scorer === "dscript" || scorer === "prodigy")) {
		failures.push("missing interaction scorer row (dscript or prodigy)");
	}

	const failedInferences = snapshot.inferences.filter(
		(inference) => inference.status === "failed",
	);
	if (failedInferences.length > 0) {
		const summary = failedInferences
			.map(
				(inference) =>
					`${inference.modelName}: ${inference.errorSummary ?? "failed"}`,
			)
			.join("; ");
		if (thresholds.allowFailedInferences) {
			warnings.push(`failed model inferences: ${summary}`);
		} else {
			failures.push(`failed model inferences: ${summary}`);
		}
	}

	const assistantText = latestAssistantText(snapshot.threadItems);
	if (!assistantText.trim()) {
		failures.push("missing final assistant message text");
	} else {
		if (!/candidate/iu.test(assistantText)) {
			failures.push("final assistant message does not mention candidates");
		}
		if (!hasScoreLikeText(assistantText)) {
			failures.push("final assistant message does not mention scores");
		}
		if (thresholds.requireCitation && !hasCitationLikeText(assistantText)) {
			failures.push(
				"final assistant message does not include DOI/PubMed citation identifiers",
			);
		}
	}

	const expectedPdbIds = definition.expectedPdbIds.map((pdbId) =>
		pdbId.toUpperCase(),
	);
	const pdbHaystack = [
		...artifactPdbIds(snapshot.artifacts),
		...eventPdbIds(sortedEvents),
		...snapshot.artifacts.flatMap((artifact) => [
			artifact.name.toUpperCase(),
			artifact.storageKey.toUpperCase(),
		]),
		assistantText.toUpperCase(),
	];
	const expectedPdbHit = expectedPdbIds.some((pdbId) =>
		pdbHaystack.some((part) => part.includes(pdbId)),
	);
	if (!expectedPdbHit) {
		const message = `none of expected PDB ids were observed: ${expectedPdbIds.join(", ")}`;
		if (thresholds.requireExpectedPdbHit) {
			failures.push(message);
		} else {
			warnings.push(message);
		}
	}

	return {
		failures,
		metrics: {
			artifactCount: snapshot.artifacts.length,
			artifactsByKind,
			assistantTextChars: assistantText.length,
			candidateCount: snapshot.candidates.length,
			eventCount: sortedEvents.length,
			expectedPdbHit,
			failedInferenceCount: failedInferences.length,
			inferenceCount: snapshot.inferences.length,
			okScoreRows: okScores.length,
			requiredToolsCompleted: trace.metrics.requiredToolsCompleted,
			scoreRows: snapshot.scores.length,
			scorers,
			totalMs,
		},
		passed: failures.length === 0,
		warnings,
	};
}

const ensureLiveEnv = () => {
	const missing: string[] = [];
	if (!process.env.DATABASE_URL) {
		missing.push("DATABASE_URL");
	}
	if ((process.env.AUTOPEP_RUNNER_BACKEND ?? "local") !== "modal") {
		missing.push("AUTOPEP_RUNNER_BACKEND=modal");
	}
	if (!process.env.AUTOPEP_MODAL_START_URL) {
		missing.push("AUTOPEP_MODAL_START_URL");
	}
	if (!process.env.AUTOPEP_MODAL_WEBHOOK_SECRET) {
		missing.push("AUTOPEP_MODAL_WEBHOOK_SECRET");
	}
	if (missing.length > 0) {
		throw new Error(
			`Live canaries require deployed-stack env: ${missing.join(", ")}`,
		);
	}
};

const ensureCanaryUser = async () => {
	const id = process.env.AUTOPEP_LIVE_CANARY_OWNER_ID || "autopep-live-canary";
	const existing = await db.query.user.findFirst({ where: eq(user.id, id) });
	if (existing) {
		return existing.id;
	}
	const now = new Date();
	await db.insert(user).values({
		createdAt: now,
		email: `${id.replace(/[^a-zA-Z0-9_-]/g, "-")}@canary.autopep.invalid`,
		emailVerified: true,
		id,
		name: "Autopep Live Canary",
		updatedAt: now,
	});
	return id;
};

const pollRun = async ({
	runId,
	timeoutMs,
	pollIntervalMs,
}: {
	pollIntervalMs: number;
	runId: string;
	timeoutMs: number;
}) => {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const run = await db.query.agentRuns.findFirst({
			where: eq(agentRuns.id, runId),
		});
		if (!run) {
			throw new Error(`Canary run disappeared: ${runId}`);
		}
		if (
			run.status === "completed" ||
			run.status === "failed" ||
			run.status === "cancelled"
		) {
			return run;
		}
		await sleep(pollIntervalMs);
	}
	throw new Error(`Timed out waiting for live canary run: ${runId}`);
};

const loadSnapshot = async ({
	runId,
	threadId,
}: {
	runId: string;
	threadId: string;
}): Promise<CanarySnapshot> => {
	const [
		run,
		eventRows,
		artifactRows,
		candidateRows,
		scoreRows,
		inferenceRows,
		itemRows,
	] = await Promise.all([
		db.query.agentRuns.findFirst({ where: eq(agentRuns.id, runId) }),
		db.query.agentEvents.findMany({
			orderBy: [asc(agentEvents.sequence)],
			where: eq(agentEvents.runId, runId),
		}),
		db.query.artifacts.findMany({ where: eq(artifacts.runId, runId) }),
		db.query.proteinCandidates.findMany({
			orderBy: [asc(proteinCandidates.rank)],
			where: eq(proteinCandidates.runId, runId),
		}),
		db.query.candidateScores.findMany({
			where: eq(candidateScores.runId, runId),
		}),
		db.query.modelInferences.findMany({
			where: eq(modelInferences.runId, runId),
		}),
		db.query.threadItems.findMany({
			orderBy: [asc(threadItems.sequence)],
			where: eq(threadItems.threadId, threadId),
		}),
	]);
	if (!run) {
		throw new Error(`Canary run disappeared before snapshot load: ${runId}`);
	}
	return {
		artifacts: artifactRows,
		candidates: candidateRows,
		events: eventRows,
		inferences: inferenceRows,
		run,
		scores: scoreRows,
		threadItems: itemRows,
	};
};

const cleanupWorkspace = async (workspaceId: string) => {
	await db.delete(workspaces).where(eq(workspaces.id, workspaceId));
};

const parseArgs = (argv: string[]): LiveCanaryConfig => {
	const args = argv.slice(2);
	const valueAfter = (flag: string) => {
		const index = args.indexOf(flag);
		return index >= 0 ? args[index + 1] : undefined;
	};
	const hasFlag = (flag: string) => args.includes(flag);
	const limit = asInt(
		valueAfter("--limit") ?? process.env.AUTOPEP_LIVE_CANARY_LIMIT,
		DEFAULT_LIVE_CANARIES.length,
	);
	const explicitIds = parseCsv(
		valueAfter("--canaries") ?? process.env.AUTOPEP_LIVE_CANARIES,
	);
	const targetValue = valueAfter("--target") ?? "prod";
	const cleanupValue =
		valueAfter("--cleanup") ??
		process.env.AUTOPEP_LIVE_CANARY_CLEANUP ??
		"never";
	const cleanup: CleanupMode =
		cleanupValue === "always" || cleanupValue === "success"
			? cleanupValue
			: "never";
	const selectedIds =
		explicitIds.length > 0
			? explicitIds
			: DEFAULT_LIVE_CANARIES.slice(0, Math.max(1, limit)).map(
					(canary) => canary.id,
				);

	return {
		canaryIds: selectedIds,
		cleanup,
		outputPath:
			valueAfter("--output") ?? process.env.AUTOPEP_LIVE_CANARY_OUTPUT,
		pollIntervalMs: asInt(
			valueAfter("--poll-interval-ms") ??
				process.env.AUTOPEP_LIVE_CANARY_POLL_INTERVAL_MS,
			DEFAULT_POLL_INTERVAL_MS,
		),
		target: targetValue === "local" ? "local" : "prod",
		thresholds: {
			allowFailedInferences: asBoolean(
				process.env.AUTOPEP_LIVE_CANARY_ALLOW_FAILED_INFERENCES,
				false,
			),
			maxTotalMs: asInt(
				valueAfter("--max-total-ms") ??
					process.env.AUTOPEP_LIVE_CANARY_MAX_TOTAL_MS,
				DEFAULT_MAX_TOTAL_MS,
			),
			minArtifacts: asInt(process.env.AUTOPEP_LIVE_CANARY_MIN_ARTIFACTS, 3),
			minCandidates: asInt(process.env.AUTOPEP_LIVE_CANARY_MIN_CANDIDATES, 1),
			minOkScoreRows: asInt(
				process.env.AUTOPEP_LIVE_CANARY_MIN_OK_SCORE_ROWS,
				1,
			),
			minScoreRows: asInt(process.env.AUTOPEP_LIVE_CANARY_MIN_SCORE_ROWS, 1),
			requireCitation: asBoolean(
				process.env.AUTOPEP_LIVE_CANARY_REQUIRE_CITATION,
				true,
			),
			requireExpectedPdbHit:
				hasFlag("--require-expected-pdb") ||
				asBoolean(process.env.AUTOPEP_LIVE_CANARY_REQUIRE_EXPECTED_PDB, false),
			timeoutMs: asInt(
				valueAfter("--timeout-ms") ??
					process.env.AUTOPEP_LIVE_CANARY_TIMEOUT_MS,
				DEFAULT_TIMEOUT_MS,
			),
		},
	};
};

const runOneCanary = async ({
	definition,
	ownerId,
	config,
}: {
	config: LiveCanaryConfig;
	definition: LiveCanaryDefinition;
	ownerId: string;
}): Promise<RunCanaryResult> => {
	const prompt = buildCanaryPrompt(definition);
	const startedAt = Date.now();
	let workspaceId: string | undefined;
	let cleanedUp = false;
	let baseResult: CompletedCanaryResult | undefined;

	try {
		const created = await createMessageRunWithLaunch({
			db,
			input: {
				description: `Nightly live science canary for ${definition.target}`,
				name: `Canary ${definition.id} ${new Date().toISOString()}`,
				prompt,
				recipeRefs: [],
				sdkStateJson: {
					canaryId: definition.id,
					canaryRunId: randomUUID(),
					kind: "live_science_canary",
				},
				taskKind: "chat",
			},
			ownerId,
		});
		workspaceId = created.workspace.id;
		console.log(
			`Launched live canary ${definition.id}: run=${created.run.id} workspace=${created.workspace.id}`,
		);
		const run = await pollRun({
			pollIntervalMs: config.pollIntervalMs,
			runId: created.run.id,
			timeoutMs: config.thresholds.timeoutMs,
		});
		const totalMs = Date.now() - startedAt;
		const snapshot = await loadSnapshot({
			runId: created.run.id,
			threadId: created.thread.id,
		});
		const evaluation = evaluateCanarySnapshot({
			definition,
			snapshot: { ...snapshot, run },
			thresholds: config.thresholds,
			totalMs,
		});
		baseResult = {
			definition,
			evaluation,
			prompt,
			runId: created.run.id,
			threadId: created.thread.id,
			totalMs,
			workspaceId: created.workspace.id,
		};
	} catch (error) {
		const totalMs = Date.now() - startedAt;
		const message = error instanceof Error ? error.message : String(error);
		baseResult = {
			definition,
			evaluation: {
				failures: [message],
				metrics: { totalMs },
				passed: false,
				warnings: [],
			},
			prompt,
			totalMs,
			workspaceId,
		};
	} finally {
		const shouldCleanup =
			workspaceId &&
			(config.cleanup === "always" ||
				(config.cleanup === "success" && baseResult?.evaluation.passed));
		if (shouldCleanup) {
			try {
				await cleanupWorkspace(workspaceId as string);
				cleanedUp = true;
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				baseResult?.evaluation.warnings.push(`cleanup failed: ${message}`);
			}
		}
	}
	if (!baseResult) {
		throw new Error(`Live canary ${definition.id} did not produce a result.`);
	}
	return { ...baseResult, cleanedUp };
};

const selectCanaries = (ids: string[]) => {
	const byId = new Map(
		DEFAULT_LIVE_CANARIES.map((canary) => [canary.id, canary]),
	);
	return ids.map((id) => {
		const canary = byId.get(id);
		if (!canary) {
			throw new Error(
				`Unknown live canary '${id}'. Known canaries: ${DEFAULT_LIVE_CANARIES.map((c) => c.id).join(", ")}`,
			);
		}
		return canary;
	});
};

export const runLiveScienceCanaries = async (config: LiveCanaryConfig) => {
	ensureLiveEnv();
	const startedAt = new Date();
	if (config.target !== "prod") {
		console.warn(
			"Live science canaries are intended for deployed-stack runs; continuing with target=local because the launcher env is explicit.",
		);
	}
	const ownerId = await ensureCanaryUser();
	const canaries = selectCanaries(config.canaryIds);
	const results: RunCanaryResult[] = [];
	for (const definition of canaries) {
		const result = await runOneCanary({ config, definition, ownerId });
		results.push(result);
		const status = result.evaluation.passed ? "PASS" : "FAIL";
		console.log(
			`${status} ${definition.id}: run=${result.runId ?? "n/a"} totalMs=${result.totalMs}`,
		);
		for (const warning of result.evaluation.warnings) {
			console.warn(`WARN ${definition.id}: ${warning}`);
		}
		for (const failure of result.evaluation.failures) {
			console.error(`FAIL ${definition.id}: ${failure}`);
		}
	}

	const suite = {
		completedAt: new Date().toISOString(),
		results,
		startedAt: startedAt.toISOString(),
		summary: {
			failed: results.filter((result) => !result.evaluation.passed).length,
			passed: results.filter((result) => result.evaluation.passed).length,
			total: results.length,
		},
		thresholds: config.thresholds,
	};

	if (config.outputPath) {
		await writeFile(config.outputPath, `${JSON.stringify(suite, null, 2)}\n`);
		console.log(`Wrote live canary report to ${config.outputPath}`);
	}
	return suite;
};

const main = async () => {
	const config = parseArgs(process.argv);
	const suite = await runLiveScienceCanaries(config);
	console.log(JSON.stringify(suite.summary, null, 2));
	return suite.summary.failed === 0 ? 0 : 1;
};

if (
	process.argv[1] &&
	import.meta.url === pathToFileURL(process.argv[1]).href
) {
	main()
		.then((code) => {
			process.exit(code);
		})
		.catch((error: unknown) => {
			const message = error instanceof Error ? error.message : String(error);
			console.error(message);
			process.exit(1);
		});
}
