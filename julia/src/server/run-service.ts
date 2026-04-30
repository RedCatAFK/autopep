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

	if (shouldRunProteinWorkflow(content)) {
		if (!env.JULIA_WORKER_START_URL || !env.JULIA_WORKER_WEBHOOK_SECRET) {
			await completeAssistantRun({
				db,
				runId: created.runId,
				assistantMessageId: created.assistantMessageId,
				text: "The protein-design worker is not configured yet.",
				source: "worker-not-configured",
			});
			return created;
		}

		await startWorkerRun({
			runId: created.runId,
			projectId,
			threadId,
			assistantMessageId: created.assistantMessageId,
			content,
			contextReferenceIds,
			dryRun: env.NODE_ENV !== "production",
		});
	} else {
		const responseText = await createDirectChatResponse(content);
		await completeAssistantRun({
			db,
			runId: created.runId,
			assistantMessageId: created.assistantMessageId,
			text: responseText,
			source: env.OPENAI_API_KEY ? "openai-responses" : "local-fallback",
		});
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
	dryRun: boolean;
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

async function completeAssistantRun({
	db,
	runId,
	assistantMessageId,
	text,
	source,
}: {
	db: Database;
	runId: string;
	assistantMessageId: string;
	text: string;
	source: string;
}) {
	await db.transaction(async (tx) => {
		await tx
			.update(runs)
			.set({
				status: "completed",
				startedAt: new Date(),
				completedAt: new Date(),
			})
			.where(eq(runs.id, runId));

		await tx
			.update(messages)
			.set({
				content: text,
				metadata: { status: "completed", source },
			})
			.where(eq(messages.id, assistantMessageId));

		await tx.insert(runEvents).values([
			{
				runId,
				type: "run_status",
				sequence: 2,
				message: "starting",
				metadata: { status: "starting", source },
			},
			{
				runId,
				type: "run_status",
				sequence: 3,
				message: "running",
				metadata: { status: "running", source },
			},
			{
				runId,
				type: "text_delta",
				sequence: 4,
				message: text,
				metadata: { delta: text, text, source },
			},
			{
				runId,
				type: "run_status",
				sequence: 5,
				message: "completed",
				metadata: { status: "completed", source },
			},
		]);
	});
}

function shouldRunProteinWorkflow(content: string): boolean {
	const normalized = content.toLowerCase();
	const hasGenerationIntent =
		/\b(generate|design|create|engineer|build|make|discover|optimi[sz]e)\b/.test(
			normalized,
		);
	const hasProteinObject =
		/\b(protein|peptide|binder|binders|miniprotein|miniproteins|nanobody)\b/.test(
			normalized,
		);
	const hasBindingTarget =
		/\b(bind|binds|binding|target|against|inhibit|inhibitor)\b/.test(
			normalized,
		);

	return hasGenerationIntent && hasProteinObject && hasBindingTarget;
}

async function createDirectChatResponse(content: string): Promise<string> {
	if (!env.OPENAI_API_KEY) {
		return "I'm Julia, a protein-design workspace assistant. Ask me a general question, or ask me to generate a protein binder to start the design workflow.";
	}

	const response = await fetch("https://api.openai.com/v1/responses", {
		method: "POST",
		headers: {
			authorization: `Bearer ${env.OPENAI_API_KEY}`,
			"content-type": "application/json",
		},
		body: JSON.stringify({
			model: env.OPENAI_DEFAULT_MODEL,
			instructions:
				"You are Julia, a concise protein-design workspace assistant. For general chat, answer directly and briefly. If the user wants a protein binder generated, explain that the design workflow will run in the workspace.",
			input: content,
			max_output_tokens: 500,
		}),
	});

	if (!response.ok) {
		return `I'm Julia. I could not reach the chat model for that message (status ${response.status}).`;
	}

	const data = (await response.json()) as {
		output_text?: unknown;
		output?: Array<{
			type?: string;
			content?: Array<{ type?: string; text?: unknown }>;
		}>;
	};

	if (typeof data.output_text === "string" && data.output_text.trim()) {
		return data.output_text.trim();
	}

	const text = data.output
		?.flatMap((item) => item.content ?? [])
		.map((contentItem) =>
			typeof contentItem.text === "string" ? contentItem.text : "",
		)
		.join("")
		.trim();

	return text || "I'm Julia.";
}
