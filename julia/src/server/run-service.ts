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
import { signWorkerPayload } from "@/server/worker-signing";

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
};

export async function createRunForPrompt({
	db,
	userId,
	projectId,
	threadId,
	content,
	contextReferenceIds = [],
}: CreateRunForPromptInput): Promise<CreatedRun> {
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
					executionMode: "single",
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

	if (env.JULIA_WORKER_START_URL && env.JULIA_WORKER_WEBHOOK_SECRET) {
		await startWorkerRun({
			runId: created.runId,
			projectId,
			threadId,
			assistantMessageId: created.assistantMessageId,
			content,
			contextReferenceIds,
		});
	} else if (env.NODE_ENV !== "production") {
		await insertLocalDryRunEvents(db, created.runId);
	}

	return created;
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
		throw new TRPCError({
			code: "BAD_GATEWAY",
			message: `Worker start failed with status ${response.status}`,
		});
	}
}

async function insertLocalDryRunEvents(db: Database, runId: string) {
	await db.transaction(async (tx) => {
		await tx
			.update(runs)
			.set({
				status: "completed",
				startedAt: new Date(),
				completedAt: new Date(),
			})
			.where(eq(runs.id, runId));

		await tx.insert(runEvents).values([
			{
				runId,
				type: "run_status",
				sequence: 2,
				message: "starting",
				metadata: { status: "starting", source: "local-dry-run" },
			},
			{
				runId,
				type: "run_status",
				sequence: 3,
				message: "running",
				metadata: { status: "running", source: "local-dry-run" },
			},
			{
				runId,
				type: "text_delta",
				sequence: 4,
				message: "Local dry run response.",
				metadata: { delta: "Local dry run response." },
			},
			{
				runId,
				type: "tool_call_started",
				sequence: 5,
				message: "literature_research started",
				metadata: { toolName: "literature_research" },
			},
			{
				runId,
				type: "tool_call_completed",
				sequence: 6,
				message: "literature_research completed",
				metadata: { toolName: "literature_research" },
			},
			{
				runId,
				type: "run_status",
				sequence: 7,
				message: "completed",
				metadata: { status: "completed", source: "local-dry-run" },
			},
		]);
	});
}
