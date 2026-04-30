import { TRPCError } from "@trpc/server";
import { and, eq } from "drizzle-orm";

import { env } from "@/env";
import type { db as dbClient } from "@/server/db";
import {
	messages,
	projects,
	runEvents,
	runs,
	threads,
} from "@/server/db/schema";
import {
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

		await tx.insert(runEvents).values({
			runId: run.id,
			type: "run_status",
			sequence: 1,
			message: "queued",
			metadata: { status: "queued" },
		});

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
