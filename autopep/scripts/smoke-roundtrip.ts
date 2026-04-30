import { randomUUID } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";

import { and, asc, desc, eq } from "drizzle-orm";

import { createMessageRunWithLaunch } from "@/server/agent/project-run-creator";
import { signRunStreamToken } from "@/server/agent/run-stream-token";
import { db } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	threads,
	user,
	workspaces,
} from "@/server/db/schema";

const smokeTaskKinds = [
	"smoke_chat",
	"smoke_tool",
	"smoke_sandbox",
	"smoke_phase_1",
	"backend_streaming",
] as const;
type SmokeTaskKind = (typeof smokeTaskKinds)[number];
type UnderlyingTaskKind = "smoke_chat" | "smoke_tool" | "smoke_sandbox";
type AgentEventRow = typeof agentEvents.$inferSelect;
type AgentRunRow = typeof agentRuns.$inferSelect;

const usage =
	"Usage: bun run scripts/smoke-roundtrip.ts <smoke_chat|smoke_tool|smoke_sandbox|smoke_phase_1|backend_streaming> [--target local|prod] [--runs N] [--ttfd-ms N] [--first-tool-ms N] [--max-total-ms N]";

const DEFAULT_TTFD_THRESHOLD_MS = 5000;
const DEFAULT_FIRST_TOOL_THRESHOLD_MS = 10_000;

const isSmokeTaskKind = (value: string): value is SmokeTaskKind =>
	(smokeTaskKinds as readonly string[]).includes(value);

// Both names measure SSE token latency; backend_streaming additionally routes
// through smoke_tool so it can assert tool-card timing.
const isBackendStreamingScenario = (
	taskKind: SmokeTaskKind,
): taskKind is "smoke_phase_1" | "backend_streaming" =>
	taskKind === "smoke_phase_1" || taskKind === "backend_streaming";

// Backend-streaming uses the smoke tool agent so the eval can time both the
// first SSE token and the first durable tool-card event. The older
// smoke_phase_1 alias keeps exercising smoke_chat for the phase gate.
const underlyingTaskKind = (taskKind: SmokeTaskKind): UnderlyingTaskKind => {
	if (taskKind === "backend_streaming") {
		return "smoke_tool";
	}
	if (taskKind === "smoke_phase_1") {
		return "smoke_chat";
	}
	return taskKind;
};

const requiredEventTypes = (taskKind: SmokeTaskKind) => {
	const required = [
		"run_started",
		"assistant_message_completed",
		"run_completed",
	];
	if (taskKind === "smoke_tool" || taskKind === "backend_streaming") {
		required.push("tool_call_completed");
	}
	if (taskKind === "smoke_sandbox") {
		required.push("sandbox_command_completed");
	}
	return required;
};

const ensureUser = async (ownerId?: string) => {
	const id = ownerId ?? `autopep-smoke-${randomUUID()}`;
	const existing = await db.query.user.findFirst({ where: eq(user.id, id) });
	if (existing) {
		return existing.id;
	}

	const now = new Date();
	await db.insert(user).values({
		createdAt: now,
		email: `${id.replace(/[^a-zA-Z0-9_-]/g, "-")}@smoke.autopep.invalid`,
		emailVerified: true,
		id,
		name: "Autopep Smoke",
		updatedAt: now,
	});
	return id;
};

const ensureWorkspace = async ({
	ownerId,
	workspaceId,
}: {
	ownerId: string;
	workspaceId?: string;
}): Promise<{
	workspace: typeof workspaces.$inferSelect;
	created: boolean;
}> => {
	if (workspaceId) {
		const workspace = await db.query.workspaces.findFirst({
			where: eq(workspaces.id, workspaceId),
		});
		if (!workspace) {
			throw new Error(`Smoke workspace not found: ${workspaceId}`);
		}
		if (workspace.ownerId !== ownerId) {
			throw new Error("Smoke workspace is not owned by the smoke owner.");
		}
		return { workspace, created: false };
	}

	const [workspace] = await db
		.insert(workspaces)
		.values({
			description: "Autopep integration smoke workspace",
			name: "Autopep smoke",
			ownerId,
		})
		.returning();

	if (!workspace) {
		throw new Error("Failed to create smoke workspace.");
	}
	return { workspace, created: true };
};

const ensureThread = async ({
	threadId,
	workspace,
}: {
	threadId?: string;
	workspace: typeof workspaces.$inferSelect;
}) => {
	if (threadId) {
		const thread = await db.query.threads.findFirst({
			where: and(
				eq(threads.id, threadId),
				eq(threads.workspaceId, workspace.id),
			),
		});
		if (!thread) {
			throw new Error(`Smoke thread not found in workspace: ${threadId}`);
		}
		return thread;
	}

	if (workspace.activeThreadId) {
		const activeThread = await db.query.threads.findFirst({
			where: and(
				eq(threads.id, workspace.activeThreadId),
				eq(threads.workspaceId, workspace.id),
			),
		});
		if (activeThread) {
			return activeThread;
		}
	}

	const latestThread = await db.query.threads.findFirst({
		orderBy: [desc(threads.updatedAt)],
		where: eq(threads.workspaceId, workspace.id),
	});
	if (latestThread) {
		return latestThread;
	}

	const [thread] = await db
		.insert(threads)
		.values({
			title: "Smoke thread",
			workspaceId: workspace.id,
		})
		.returning();
	if (!thread) {
		throw new Error("Failed to create smoke thread.");
	}

	await db
		.update(workspaces)
		.set({ activeThreadId: thread.id })
		.where(eq(workspaces.id, workspace.id));
	return thread;
};

const pollRun = async (runId: string, _taskKind: SmokeTaskKind) => {
	const deadline = Date.now() + 180_000;
	while (Date.now() < deadline) {
		const run = await db.query.agentRuns.findFirst({
			where: eq(agentRuns.id, runId),
		});
		if (!run) {
			throw new Error(`Smoke run disappeared: ${runId}`);
		}
		if (run.status === "completed" || run.status === "failed") {
			return run;
		}
		await sleep(2_000);
	}
	throw new Error(`Timed out waiting for smoke run: ${runId}`);
};

const assertEvents = async ({
	runId,
	taskKind,
}: {
	runId: string;
	taskKind: SmokeTaskKind;
}) => {
	const events = await db.query.agentEvents.findMany({
		orderBy: [asc(agentEvents.sequence)],
		where: eq(agentEvents.runId, runId),
	});
	if (events.length === 0) {
		throw new Error("Smoke run did not record any events.");
	}

	for (const [index, event] of events.entries()) {
		const expectedSequence = index + 1;
		if (event.sequence !== expectedSequence) {
			throw new Error(
				`Smoke event sequence gap: expected ${expectedSequence}, got ${event.sequence}`,
			);
		}
	}

	const eventTypes = new Set(events.map((event) => event.type));
	for (const required of requiredEventTypes(taskKind)) {
		if (!eventTypes.has(required)) {
			throw new Error(`Smoke event missing required type: ${required}`);
		}
	}

	if (taskKind === "smoke_sandbox") {
		// Stdout deltas are no longer ledgered as separate rows; the runner
		// coalesces them into the parent sandbox_command_completed event's
		// display.stdout (Task 2.8). Look there instead.
		const stdout = events
			.filter((event) => event.type === "sandbox_command_completed")
			.map((event) => {
				const display = (event.displayJson ?? {}) as Record<string, unknown>;
				return typeof display.stdout === "string" ? display.stdout : "";
			})
			.join("\n");
		if (!stdout.includes("sandbox-ok")) {
			throw new Error(
				"Smoke sandbox stdout did not contain sandbox-ok (checked sandbox_command_completed.display.stdout).",
			);
		}
	}

	return events;
};

const getCallId = (event: AgentEventRow): string | null => {
	const display = (event.displayJson ?? {}) as Record<string, unknown>;
	const callId =
		display.callId ??
		display.call_id ??
		display.toolCallId ??
		display.commandId ??
		display.command_id;
	return typeof callId === "string" ? callId : null;
};

type PairTiming = {
	name: string;
	startSequence: number;
	completedSequence: number;
	durationMs: number;
};

const eventDisplayName = (event: AgentEventRow): string => {
	const display = (event.displayJson ?? {}) as Record<string, unknown>;
	const name =
		display.name ?? display.command ?? display.toolName ?? event.title;
	return typeof name === "string" && name.trim() ? name.trim() : event.type;
};

const pairEventTimings = (
	events: AgentEventRow[],
	startedType: string,
	completedType: string,
): PairTiming[] => {
	const starts = events.filter((e) => e.type === startedType);
	const completes = events.filter((e) => e.type === completedType);
	const usedCompleteIndexes = new Set<number>();
	const timings: PairTiming[] = [];

	for (const start of starts) {
		const callId = getCallId(start);
		const pairLabel = callId ?? `(seq ${start.sequence})`;
		// Fall back to sequence pairing when a callId isn't available.
		const matchingIndex = completes.findIndex((candidate, index) => {
			if (usedCompleteIndexes.has(index)) {
				return false;
			}
			return callId
				? getCallId(candidate) === callId
				: candidate.sequence > start.sequence;
		});
		if (matchingIndex < 0) {
			throw new Error(
				`backend_streaming: missing ${completedType} for ${startedType} ${pairLabel}`,
			);
		}

		const matching = completes[matchingIndex];
		if (!matching) {
			throw new Error(`backend_streaming: failed to pair ${startedType}.`);
		}
		usedCompleteIndexes.add(matchingIndex);

		if (matching.createdAt.getTime() < start.createdAt.getTime()) {
			throw new Error(
				`backend_streaming: ${completedType} arrived before ${startedType} for ${pairLabel}`,
			);
		}

		timings.push({
			completedSequence: matching.sequence,
			durationMs: matching.createdAt.getTime() - start.createdAt.getTime(),
			name: eventDisplayName(start),
			startSequence: start.sequence,
		});
	}
	return timings;
};

// Tail the Modal SSE run-stream and resolve as soon as we see the first
// `event: delta` frame. Returns the elapsed milliseconds since `startTime`.
// Rejects on timeout or on an SSE `event: done` without any prior delta.
const waitForFirstSseDelta = async ({
	runId,
	startTime,
	timeoutMs,
}: {
	runId: string;
	startTime: number;
	timeoutMs: number;
}): Promise<number> => {
	const streamBaseUrl =
		process.env.AUTOPEP_MODAL_RUN_STREAM_URL ??
		"https://chrisyooak--run-stream.modal.run";
	const secret = process.env.AUTOPEP_MODAL_WEBHOOK_SECRET;
	if (!secret) {
		throw new Error(
			"backend_streaming: AUTOPEP_MODAL_WEBHOOK_SECRET is required to mint the SSE token.",
		);
	}
	// Fetch a temporary userId only for the JWT payload; the verifier on the
	// Modal side only checks runId + signature + expiry.
	const token = signRunStreamToken({
		expiresInSeconds: 300,
		payload: { runId, userId: "smoke" },
		secret,
	});
	const url = `${streamBaseUrl}?runId=${encodeURIComponent(runId)}&token=${encodeURIComponent(token)}`;

	const controller = new AbortController();
	const abortTimer = setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await fetch(url, {
			headers: { Accept: "text/event-stream" },
			signal: controller.signal,
		});
		if (!response.ok || !response.body) {
			throw new Error(
				`backend_streaming: SSE connect failed (${response.status}).`,
			);
		}
		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		while (true) {
			const { value, done } = await reader.read();
			if (done) {
				throw new Error(
					"backend_streaming: SSE stream ended before any delta arrived.",
				);
			}
			buffer += decoder.decode(value, { stream: true });
			// SSE frames are separated by blank lines. Inspect each complete
			// frame for an `event: delta` line.
			while (true) {
				const frameEnd = buffer.indexOf("\n\n");
				if (frameEnd < 0) {
					break;
				}
				const frame = buffer.slice(0, frameEnd);
				buffer = buffer.slice(frameEnd + 2);
				const lines = frame.split("\n");
				for (const line of lines) {
					if (line.startsWith("event:") && line.slice(6).trim() === "delta") {
						const elapsed = Date.now() - startTime;
						try {
							await reader.cancel();
						} catch {
							// ignore
						}
						return elapsed;
					}
					if (line.startsWith("event:") && line.slice(6).trim() === "done") {
						throw new Error(
							"backend_streaming: SSE 'done' arrived before any delta.",
						);
					}
				}
			}
		}
	} finally {
		clearTimeout(abortTimer);
	}
};

const cleanupWorkspace = async (workspaceId: string): Promise<void> => {
	// Best-effort; cascades to threads -> thread_items -> agent_runs ->
	// agent_events via existing FK cascades. Never fail the test on cleanup.
	try {
		await db.delete(workspaces).where(eq(workspaces.id, workspaceId));
		console.log(`Cleaned up smoke workspace ${workspaceId}.`);
	} catch (e) {
		console.warn("Cleanup failed (non-fatal):", e);
	}
};

type CliArgs = {
	firstToolThresholdMs: number;
	maxTotalMs: number | null;
	runs: number;
	target: string;
	taskKind: string | undefined;
	ttfdThresholdMs: number;
};

const parseArgs = (argv: string[]): CliArgs => {
	const args = argv.slice(2);
	const readFlagValue = (flag: string): string | undefined => {
		const index = args.indexOf(flag);
		if (index < 0) {
			return undefined;
		}
		const value = args[index + 1];
		if (!value || value.startsWith("--")) {
			throw new Error(`${flag} requires a value.`);
		}
		return value;
	};
	const parsePositiveInt = (
		flag: string,
		defaultValue: number | null,
	): number | null => {
		const raw = readFlagValue(flag);
		if (raw === undefined) {
			return defaultValue;
		}
		const value = Number(raw);
		if (!Number.isInteger(value) || value <= 0) {
			throw new Error(`${flag} must be a positive integer.`);
		}
		return value;
	};

	const target = readFlagValue("--target") ?? "local";
	const valueFlags = new Set([
		"--target",
		"--runs",
		"--ttfd-ms",
		"--first-tool-ms",
		"--max-total-ms",
	]);
	// First positional arg (i.e. not `--target` or its value) is the task kind.
	let taskKind: string | undefined;
	for (let i = 0; i < args.length; i++) {
		const arg = args[i];
		if (arg && valueFlags.has(arg)) {
			i++;
			continue;
		}
		if (arg && !arg.startsWith("--")) {
			taskKind = arg;
			break;
		}
	}
	return {
		firstToolThresholdMs:
			parsePositiveInt("--first-tool-ms", DEFAULT_FIRST_TOOL_THRESHOLD_MS) ??
			DEFAULT_FIRST_TOOL_THRESHOLD_MS,
		maxTotalMs: parsePositiveInt("--max-total-ms", null),
		runs: parsePositiveInt("--runs", 1) ?? 1,
		target,
		taskKind,
		ttfdThresholdMs:
			parsePositiveInt("--ttfd-ms", DEFAULT_TTFD_THRESHOLD_MS) ??
			DEFAULT_TTFD_THRESHOLD_MS,
	};
};

type SmokeRunMetrics = {
	eventCount: number;
	firstToolCardMs: number | null;
	maxEventGapMs: number;
	runDurationMs: number | null;
	runId: string;
	runIndex: number;
	sandboxTimings: PairTiming[];
	taskKind: SmokeTaskKind;
	toolTimings: PairTiming[];
	totalWallClockMs: number;
	ttfdMs: number | null;
	underlyingTaskKind: UnderlyingTaskKind;
};

const promptForTaskKind = (taskKind: SmokeTaskKind): string => {
	if (taskKind === "backend_streaming") {
		return `streaming-eval-${Date.now()}: call the smoke tool once`;
	}
	if (taskKind === "smoke_phase_1") {
		return `streaming-eval-${Date.now()}: respond with the word ack`;
	}
	return "ping";
};

const formatMs = (value: number | null): string =>
	value === null ? "n/a" : `${Math.round(value)}ms`;

const percentile = (values: number[], p: number): number | null => {
	if (values.length === 0) {
		return null;
	}
	const sorted = [...values].sort((a, b) => a - b);
	const index = Math.min(
		sorted.length - 1,
		Math.max(0, Math.ceil((p / 100) * sorted.length) - 1),
	);
	return sorted[index] ?? null;
};

const summarizeValues = (label: string, values: number[]): void => {
	if (values.length === 0) {
		return;
	}
	const min = Math.min(...values);
	const max = Math.max(...values);
	console.log(
		`${label}: n=${values.length} p50=${formatMs(percentile(values, 50))} p95=${formatMs(percentile(values, 95))} min=${formatMs(min)} max=${formatMs(max)}`,
	);
};

const maxConsecutiveEventGapMs = (events: AgentEventRow[]): number => {
	let maxGap = 0;
	for (let index = 1; index < events.length; index++) {
		const previous = events[index - 1];
		const current = events[index];
		if (!previous || !current) {
			continue;
		}
		maxGap = Math.max(
			maxGap,
			current.createdAt.getTime() - previous.createdAt.getTime(),
		);
	}
	return maxGap;
};

const firstToolCardMs = (
	events: AgentEventRow[],
	launchedAt: number,
): number | null => {
	const firstToolEvent = events.find(
		(event) =>
			event.type === "tool_call_started" ||
			event.type === "sandbox_command_started",
	);
	if (!firstToolEvent) {
		return null;
	}
	return Math.max(0, firstToolEvent.createdAt.getTime() - launchedAt);
};

const runDurationMs = (run: AgentRunRow): number | null => {
	if (!run.startedAt || !run.finishedAt) {
		return null;
	}
	return Math.max(0, run.finishedAt.getTime() - run.startedAt.getTime());
};

const printRunMetrics = (metrics: SmokeRunMetrics): void => {
	console.log(
		`Run ${metrics.runIndex} metrics: run=${metrics.runId} task=${metrics.underlyingTaskKind} events=${metrics.eventCount} wall=${formatMs(metrics.totalWallClockMs)} runDuration=${formatMs(metrics.runDurationMs)} ttfd=${formatMs(metrics.ttfdMs)} firstToolCard=${formatMs(metrics.firstToolCardMs)} maxEventGap=${formatMs(metrics.maxEventGapMs)}`,
	);
	for (const pair of metrics.toolTimings) {
		console.log(
			`  tool ${pair.name}: ${formatMs(pair.durationMs)} (events ${pair.startSequence}->${pair.completedSequence})`,
		);
	}
	for (const pair of metrics.sandboxTimings) {
		console.log(
			`  sandbox ${pair.name}: ${formatMs(pair.durationMs)} (events ${pair.startSequence}->${pair.completedSequence})`,
		);
	}
};

const printSummary = (metrics: SmokeRunMetrics[]): void => {
	if (metrics.length === 0) {
		return;
	}

	console.log("\nStreaming/performance summary:");
	summarizeValues(
		"total wall clock",
		metrics.map((metric) => metric.totalWallClockMs),
	);
	summarizeValues(
		"worker run duration",
		metrics
			.map((metric) => metric.runDurationMs)
			.filter((value): value is number => value !== null),
	);
	summarizeValues(
		"time to first token",
		metrics
			.map((metric) => metric.ttfdMs)
			.filter((value): value is number => value !== null),
	);
	summarizeValues(
		"time to first tool card",
		metrics
			.map((metric) => metric.firstToolCardMs)
			.filter((value): value is number => value !== null),
	);
	summarizeValues(
		"max consecutive event gap",
		metrics.map((metric) => metric.maxEventGapMs),
	);

	const stages = new Map<string, number[]>();
	for (const metric of metrics) {
		for (const pair of [...metric.toolTimings, ...metric.sandboxTimings]) {
			const values = stages.get(pair.name) ?? [];
			values.push(pair.durationMs);
			stages.set(pair.name, values);
		}
	}
	for (const [name, values] of stages) {
		summarizeValues(`stage ${name}`, values);
	}
};

const runSmokeAttempt = async ({
	firstToolThresholdMs,
	maxTotalMs,
	ownerId,
	runIndex,
	taskKind,
	thread,
	totalRuns,
	ttfdThresholdMs,
	workspace,
}: {
	firstToolThresholdMs: number;
	maxTotalMs: number | null;
	ownerId: string;
	runIndex: number;
	taskKind: SmokeTaskKind;
	thread: typeof threads.$inferSelect;
	totalRuns: number;
	ttfdThresholdMs: number;
	workspace: typeof workspaces.$inferSelect;
}): Promise<SmokeRunMetrics> => {
	const taskKindForRun = underlyingTaskKind(taskKind);
	const prompt = promptForTaskKind(taskKind);
	const created = await createMessageRunWithLaunch({
		db,
		input: {
			prompt,
			recipeRefs: [],
			taskKind: taskKindForRun,
			threadId: thread.id,
			workspaceId: workspace.id,
		},
		ownerId,
	});
	const launchedAt = Date.now();

	console.log(
		`Smoke run ${runIndex}/${totalRuns} launched: ${created.run.id} (${taskKindForRun})`,
	);

	const ssePromise = isBackendStreamingScenario(taskKind)
		? waitForFirstSseDelta({
				runId: created.run.id,
				startTime: launchedAt,
				timeoutMs: 30_000,
			}).then(
				(ms) => ({ ms, ok: true as const }),
				(error: unknown) => ({ error, ok: false as const }),
			)
		: null;

	const run = await pollRun(created.run.id, taskKind);
	const completedObservedAt = Date.now();
	if (run.status !== "completed") {
		throw new Error(`Smoke run failed: ${run.errorSummary ?? "unknown error"}`);
	}
	if (!run.finishedAt) {
		throw new Error("Smoke run completed without finishedAt.");
	}

	const events = await assertEvents({ runId: run.id, taskKind });
	console.log(
		`Smoke ${taskKind} run ${runIndex}/${totalRuns} completed with ${events.length} contiguous events.`,
	);
	if (run.lastResponseId) {
		console.log(`Last response ID: ${run.lastResponseId}`);
	}

	let ttfdMs: number | null = null;
	if (ssePromise) {
		const sseResult = await ssePromise;
		if (!sseResult.ok) {
			throw sseResult.error;
		}
		ttfdMs = sseResult.ms;
		if (ttfdMs > ttfdThresholdMs) {
			throw new Error(
				`backend_streaming: TTFD ${ttfdMs}ms exceeds ${ttfdThresholdMs}ms threshold.`,
			);
		}
	}

	const toolTimings = pairEventTimings(
		events,
		"tool_call_started",
		"tool_call_completed",
	);
	const sandboxTimings = pairEventTimings(
		events,
		"sandbox_command_started",
		"sandbox_command_completed",
	);
	const firstToolMs = firstToolCardMs(events, launchedAt);
	if (taskKind === "backend_streaming") {
		if (firstToolMs === null) {
			throw new Error("backend_streaming: no tool card event was recorded.");
		}
		if (firstToolMs > firstToolThresholdMs) {
			throw new Error(
				`backend_streaming: first tool card ${firstToolMs}ms exceeds ${firstToolThresholdMs}ms threshold.`,
			);
		}
	}

	const totalWallClockMs = completedObservedAt - launchedAt;
	if (maxTotalMs !== null && totalWallClockMs > maxTotalMs) {
		throw new Error(
			`Smoke run wall clock ${totalWallClockMs}ms exceeds ${maxTotalMs}ms threshold.`,
		);
	}

	const metrics: SmokeRunMetrics = {
		eventCount: events.length,
		firstToolCardMs: firstToolMs,
		maxEventGapMs: maxConsecutiveEventGapMs(events),
		runDurationMs: runDurationMs(run),
		runId: run.id,
		runIndex,
		sandboxTimings,
		taskKind,
		toolTimings,
		totalWallClockMs,
		ttfdMs,
		underlyingTaskKind: taskKindForRun,
	};
	printRunMetrics(metrics);

	if (isBackendStreamingScenario(taskKind)) {
		console.log(
			`${taskKind}: TTFD ${formatMs(ttfdMs)} (<${ttfdThresholdMs}ms)`,
		);
		if (taskKind === "backend_streaming") {
			console.log(
				`${taskKind}: first tool card ${formatMs(firstToolMs)} (<${firstToolThresholdMs}ms)`,
			);
		}
		console.log(
			`${taskKind}: ${toolTimings.length} tool calls, ${sandboxTimings.length} sandbox commands, all well-ordered`,
		);
	}

	return metrics;
};

const main = async () => {
	const {
		firstToolThresholdMs,
		maxTotalMs,
		runs,
		taskKind,
		target,
		ttfdThresholdMs,
	} = parseArgs(process.argv);
	if (!taskKind || !isSmokeTaskKind(taskKind)) {
		throw new Error(usage);
	}
	if (target !== "local" && target !== "prod") {
		console.error(`Invalid --target ${target}. Use 'local' or 'prod'.`);
		process.exit(1);
	}

	// Resolve baseUrl/apiToken even though the script currently drives Modal
	// via the in-process path; future tasks (per the plan) may swap to HTTP.
	// For now, both targets read/write the same Neon (one branch) and trigger
	// the deployed Modal worker — so the only actual behavioural difference is
	// best-effort cleanup at the end.
	const baseUrl =
		target === "prod"
			? (process.env.AUTOPEP_PROD_BASE_URL ?? "https://autopep.vercel.app")
			: "http://localhost:3000";
	const apiToken =
		target === "prod" ? process.env.AUTOPEP_PROD_API_TOKEN : undefined;
	void baseUrl;
	void apiToken;

	const ownerId = await ensureUser(process.env.AUTOPEP_SMOKE_OWNER_ID);
	const { workspace, created: workspaceCreated } = await ensureWorkspace({
		ownerId,
		workspaceId: process.env.AUTOPEP_SMOKE_WORKSPACE_ID,
	});
	const thread = await ensureThread({
		threadId: process.env.AUTOPEP_SMOKE_THREAD_ID,
		workspace,
	});

	console.log(`Smoke target: ${target}`);
	console.log("Smoke IDs for env reuse:");
	console.log(`AUTOPEP_SMOKE_OWNER_ID=${ownerId}`);
	console.log(`AUTOPEP_SMOKE_WORKSPACE_ID=${workspace.id}`);
	console.log(`AUTOPEP_SMOKE_THREAD_ID=${thread.id}`);
	console.log(
		`Smoke eval config: scenario=${taskKind} underlying=${underlyingTaskKind(taskKind)} runs=${runs} ttfdThreshold=${ttfdThresholdMs}ms firstToolThreshold=${firstToolThresholdMs}ms maxTotal=${maxTotalMs ?? "none"}`,
	);

	const metrics: SmokeRunMetrics[] = [];
	try {
		for (let runIndex = 1; runIndex <= runs; runIndex++) {
			metrics.push(
				await runSmokeAttempt({
					firstToolThresholdMs,
					maxTotalMs,
					ownerId,
					runIndex,
					taskKind,
					thread,
					totalRuns: runs,
					ttfdThresholdMs,
					workspace,
				}),
			);
		}
		printSummary(metrics);
		if (isBackendStreamingScenario(taskKind)) {
			console.log(`${taskKind} scenario green`);
		}
	} finally {
		// Best-effort cleanup of the smoke workspace when running against prod
		// and we created it ourselves (i.e. the caller didn't pin a workspace
		// via env). Cleanup is non-fatal.
		if (target === "prod" && workspaceCreated) {
			await cleanupWorkspace(workspace.id);
		}
	}
};

main()
	.then(() => {
		process.exit(0);
	})
	.catch((error: unknown) => {
		const message = error instanceof Error ? error.message : String(error);
		console.error(message);
		process.exit(1);
	});
