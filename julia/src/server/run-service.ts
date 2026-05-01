import { TRPCError } from "@trpc/server";
import { and, eq } from "drizzle-orm";

import { env } from "@/env";
import type { db as dbClient } from "@/server/db";
import { messages, projects, runs, threads } from "@/server/db/schema";
import {
	buildWorkerCancelUrl,
	buildWorkerWebSocketUrl,
	mintWorkerWebSocketToken,
	signWorkerPayload,
} from "@/server/worker-signing";

type Database = typeof dbClient;

type CreateRunForPromptInput = {
	db: Database;
	userId: string;
	projectId: string;
	threadId: string;
	content: string;
	contextReferenceIds?: string[];
};

type CreatedRun = {
	runId: string;
	assistantMessageId: string;
	wsUrl: string;
	wsToken: string;
};

/**
 * Create a run, kick off the Modal worker, and return the data the browser
 * needs to subscribe to live events. The worker runs the agent — there is no
 * separate "general chat" path; the agent decides whether to call tools.
 */
export async function createRunForPrompt({
	db,
	userId,
	projectId,
	threadId,
	content,
	contextReferenceIds = [],
}: CreateRunForPromptInput): Promise<CreatedRun> {
	if (!env.JULIA_WORKER_START_URL || !env.JULIA_WORKER_WEBHOOK_SECRET) {
		throw new TRPCError({
			code: "PRECONDITION_FAILED",
			message:
				"Julia worker is not configured. Set JULIA_WORKER_START_URL and JULIA_WORKER_WEBHOOK_SECRET.",
		});
	}

	const ownership = await db
		.select({
			projectId: projects.id,
			threadId: threads.id,
		})
		.from(projects)
		.innerJoin(
			threads,
			and(eq(threads.projectId, projects.id), eq(threads.id, threadId)),
		)
		.where(and(eq(projects.id, projectId), eq(projects.ownerId, userId)))
		.limit(1);

	if (!ownership[0]) {
		throw new TRPCError({
			code: "NOT_FOUND",
			message: "Project or thread not found",
		});
	}

	const created = await db.transaction(async (tx) => {
		const [userMessage] = await tx
			.insert(messages)
			.values({
				threadId,
				role: "user",
				content,
				metadata: { contextReferenceIds },
			})
			.returning({ id: messages.id });

		const [assistantMessage] = await tx
			.insert(messages)
			.values({
				threadId,
				role: "assistant",
				content: "",
				metadata: { status: "placeholder" },
			})
			.returning({ id: messages.id });

		const [run] = await tx
			.insert(runs)
			.values({
				projectId,
				threadId,
				status: "queued",
				mode: "chat",
				input: content,
				metadata: {
					assistantMessageId: assistantMessage?.id,
					contextReferenceIds,
					userMessageId: userMessage?.id,
				},
			})
			.returning({ id: runs.id });

		if (!run || !assistantMessage) {
			throw new TRPCError({
				code: "INTERNAL_SERVER_ERROR",
				message: "Failed to create run",
			});
		}

		return { runId: run.id, assistantMessageId: assistantMessage.id };
	});

	await startWorkerRun({
		runId: created.runId,
		projectId,
		threadId,
		assistantMessageId: created.assistantMessageId,
		content,
		contextReferenceIds,
	});

	const wsUrl = buildWorkerWebSocketUrl(
		env.JULIA_WORKER_START_URL,
		created.runId,
	);
	const wsToken = mintWorkerWebSocketToken(
		created.runId,
		env.JULIA_WORKER_WEBHOOK_SECRET,
	);

	return {
		runId: created.runId,
		assistantMessageId: created.assistantMessageId,
		wsUrl,
		wsToken,
	};
}

type CancelRunInput = {
	db: Database;
	userId: string;
	runId: string;
};

/**
 * Ask the Modal worker to cancel a still-running agent task. Ownership is
 * checked via the run's project owner. The worker emits a `run_status=canceled`
 * event and updates the run row; the browser sees it through the existing
 * WebSocket stream and treats it as terminal.
 */
export async function cancelRunForUser({
	db,
	userId,
	runId,
}: CancelRunInput): Promise<{
	runId: string;
	status: "canceling" | "not_running";
}> {
	if (!env.JULIA_WORKER_START_URL || !env.JULIA_WORKER_WEBHOOK_SECRET) {
		throw new TRPCError({
			code: "PRECONDITION_FAILED",
			message:
				"Julia worker is not configured. Set JULIA_WORKER_START_URL and JULIA_WORKER_WEBHOOK_SECRET.",
		});
	}

	const ownership = await db
		.select({ runId: runs.id })
		.from(runs)
		.innerJoin(projects, eq(projects.id, runs.projectId))
		.where(and(eq(runs.id, runId), eq(projects.ownerId, userId)))
		.limit(1);

	if (!ownership[0]) {
		throw new TRPCError({
			code: "NOT_FOUND",
			message: "Run not found",
		});
	}

	const rawJson = JSON.stringify({ runId });
	const signature = signWorkerPayload(rawJson, env.JULIA_WORKER_WEBHOOK_SECRET);
	const cancelUrl = buildWorkerCancelUrl(env.JULIA_WORKER_START_URL);

	const response = await fetch(cancelUrl, {
		method: "POST",
		headers: {
			"content-type": "application/json",
			"x-julia-signature": signature,
		},
		body: rawJson,
	});

	if (!response.ok) {
		const detail = await response.text().catch(() => "");
		throw new TRPCError({
			code: "BAD_GATEWAY",
			message: `Worker cancel failed (${response.status}): ${detail.slice(0, 200)}`,
		});
	}

	const result = (await response.json().catch(() => ({}))) as {
		status?: string;
	};
	const status = result.status === "canceling" ? "canceling" : "not_running";
	return { runId, status };
}

async function startWorkerRun(payload: {
	runId: string;
	projectId: string;
	threadId: string;
	assistantMessageId: string;
	content: string;
	contextReferenceIds: string[];
}) {
	if (!env.JULIA_WORKER_START_URL || !env.JULIA_WORKER_WEBHOOK_SECRET) return;

	const rawJson = JSON.stringify(payload);
	const signature = signWorkerPayload(rawJson, env.JULIA_WORKER_WEBHOOK_SECRET);

	const response = await fetch(env.JULIA_WORKER_START_URL, {
		method: "POST",
		headers: {
			"content-type": "application/json",
			"x-julia-signature": signature,
		},
		body: rawJson,
	});

	if (!response.ok) {
		const detail = await response.text().catch(() => "");
		throw new TRPCError({
			code: "BAD_GATEWAY",
			message: `Worker start failed (${response.status}): ${detail.slice(0, 200)}`,
		});
	}
}
