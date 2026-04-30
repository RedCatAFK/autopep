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

const usage =
	"Usage: bun run scripts/smoke-roundtrip.ts <smoke_chat|smoke_tool|smoke_sandbox|smoke_phase_1|backend_streaming> [--target local|prod]";

const isSmokeTaskKind = (value: string): value is SmokeTaskKind =>
	(smokeTaskKinds as readonly string[]).includes(value);

// `backend_streaming` is an alias for `smoke_phase_1`.
const isBackendStreamingScenario = (
	taskKind: SmokeTaskKind,
): taskKind is "smoke_phase_1" | "backend_streaming" =>
	taskKind === "smoke_phase_1" || taskKind === "backend_streaming";

// Backend-streaming scenario runs against the chat agent under the hood; the
// scenario asserts streaming-specific event ordering on top of the run.
const underlyingTaskKind = (
	taskKind: SmokeTaskKind,
): "smoke_chat" | "smoke_tool" | "smoke_sandbox" =>
	isBackendStreamingScenario(taskKind) ? "smoke_chat" : taskKind;

const requiredEventTypes = (taskKind: SmokeTaskKind) => {
	const required = [
		"run_started",
		"assistant_message_completed",
		"run_completed",
	];
	if (taskKind === "smoke_tool") {
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
			where: and(eq(threads.id, threadId), eq(threads.workspaceId, workspace.id)),
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

const getCallId = (
	event: typeof agentEvents.$inferSelect,
): string | null => {
	const display = (event.displayJson ?? {}) as Record<string, unknown>;
	const callId = display.callId ?? display.call_id ?? display.toolCallId;
	return typeof callId === "string" ? callId : null;
};

const assertWellOrderedPairs = (
	events: (typeof agentEvents.$inferSelect)[],
	startedType: string,
	completedType: string,
): number => {
	const starts = events.filter((e) => e.type === startedType);
	const completes = events.filter((e) => e.type === completedType);
	for (const start of starts) {
		const callId = getCallId(start);
		// Fall back to sequence pairing when a callId isn't available.
		const matching = callId
			? completes.find((c) => getCallId(c) === callId)
			: completes.find((c) => c.sequence > start.sequence);
		if (
			matching &&
			matching.createdAt.getTime() < start.createdAt.getTime()
		) {
			throw new Error(
				`backend_streaming: ${completedType} arrived before ${startedType} for ${callId ?? "(seq " + start.sequence + ")"}`,
			);
		}
	}
	return starts.length;
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
			let frameEnd: number;
			while ((frameEnd = buffer.indexOf("\n\n")) >= 0) {
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

const parseArgs = (
	argv: string[],
): { taskKind: string | undefined; target: string } => {
	const args = argv.slice(2);
	const targetIdx = args.indexOf("--target");
	const target = targetIdx >= 0 ? (args[targetIdx + 1] ?? "") : "local";
	// First positional arg (i.e. not `--target` or its value) is the task kind.
	let taskKind: string | undefined;
	for (let i = 0; i < args.length; i++) {
		const arg = args[i];
		if (arg === "--target") {
			i++;
			continue;
		}
		if (arg && !arg.startsWith("--")) {
			taskKind = arg;
			break;
		}
	}
	return { taskKind, target };
};

const main = async () => {
	const { taskKind, target } = parseArgs(process.argv);
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

	const prompt = isBackendStreamingScenario(taskKind)
		? `smoke-${Date.now()}: respond with the word ack`
		: "ping";

	try {
		const created = await createMessageRunWithLaunch({
			db,
			input: {
				prompt,
				recipeRefs: [],
				taskKind: underlyingTaskKind(taskKind),
				threadId: thread.id,
				workspaceId: workspace.id,
			},
			ownerId,
		});
		const launchedAt = Date.now();

		console.log(`Smoke run launched: ${created.run.id}`);

		// For backend_streaming, race the SSE tail against the run; we want
		// TTFD measured from launch, not from completion.
		const ssePromise = isBackendStreamingScenario(taskKind)
			? waitForFirstSseDelta({
					runId: created.run.id,
					startTime: launchedAt,
					timeoutMs: 30_000,
				})
			: null;

		const run = await pollRun(created.run.id, taskKind);
		if (run.status !== "completed") {
			throw new Error(
				`Smoke run failed: ${run.errorSummary ?? "unknown error"}`,
			);
		}
		if (!run.finishedAt) {
			throw new Error("Smoke run completed without finishedAt.");
		}

		const events = await assertEvents({ runId: run.id, taskKind });
		console.log(
			`Smoke ${taskKind} completed with ${events.length} contiguous events.`,
		);
		if (run.lastResponseId) {
			console.log(`Last response ID: ${run.lastResponseId}`);
		}

		if (isBackendStreamingScenario(taskKind) && ssePromise) {
			const ttfdMs = await ssePromise;
			if (ttfdMs > 5000) {
				throw new Error(
					`backend_streaming: TTFD ${ttfdMs}ms exceeds 5000ms threshold.`,
				);
			}
			console.log(`backend_streaming: TTFD ${ttfdMs}ms (<5000ms)`);

			const toolPairs = assertWellOrderedPairs(
				events,
				"tool_call_started",
				"tool_call_completed",
			);
			const sandboxPairs = assertWellOrderedPairs(
				events,
				"sandbox_command_started",
				"sandbox_command_completed",
			);
			console.log(
				`backend_streaming: ${toolPairs} tool calls, ${sandboxPairs} sandbox commands, all well-ordered`,
			);
			console.log("backend_streaming scenario green");
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
