import { randomUUID } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";

import { and, asc, desc, eq } from "drizzle-orm";

import { createMessageRunWithLaunch } from "@/server/agent/project-run-creator";
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
] as const;
type SmokeTaskKind = (typeof smokeTaskKinds)[number];

const usage =
	"Usage: bun run scripts/smoke-roundtrip.ts <smoke_chat|smoke_tool|smoke_sandbox>";

const isSmokeTaskKind = (value: string): value is SmokeTaskKind =>
	(smokeTaskKinds as readonly string[]).includes(value);

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
}) => {
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
		return workspace;
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
	return workspace;
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

const main = async () => {
	const taskKind = process.argv[2];
	if (!taskKind || !isSmokeTaskKind(taskKind)) {
		throw new Error(usage);
	}

	const ownerId = await ensureUser(process.env.AUTOPEP_SMOKE_OWNER_ID);
	const workspace = await ensureWorkspace({
		ownerId,
		workspaceId: process.env.AUTOPEP_SMOKE_WORKSPACE_ID,
	});
	const thread = await ensureThread({
		threadId: process.env.AUTOPEP_SMOKE_THREAD_ID,
		workspace,
	});

	console.log("Smoke IDs for env reuse:");
	console.log(`AUTOPEP_SMOKE_OWNER_ID=${ownerId}`);
	console.log(`AUTOPEP_SMOKE_WORKSPACE_ID=${workspace.id}`);
	console.log(`AUTOPEP_SMOKE_THREAD_ID=${thread.id}`);

	const created = await createMessageRunWithLaunch({
		db,
		input: {
			prompt: "ping",
			recipeRefs: [],
			taskKind,
			threadId: thread.id,
			workspaceId: workspace.id,
		},
		ownerId,
	});

	console.log(`Smoke run launched: ${created.run.id}`);
	const run = await pollRun(created.run.id, taskKind);
	if (run.status !== "completed") {
		throw new Error(`Smoke run failed: ${run.errorSummary ?? "unknown error"}`);
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
