import { createHash } from "node:crypto";

import type { db as appDb } from "@/server/db";
import { messages } from "@/server/db/schema";

export type AgentMessageWebhookPayload = {
	runId: string;
	threadId: string;
	role: "assistant" | "system" | "user";
	content: string;
	metadata?: Record<string, unknown>;
};

type ProcessArgs = {
	db: Pick<typeof appDb, "insert">;
	payload: AgentMessageWebhookPayload;
};

const deriveMessageId = (runId: string, role: string): string =>
	createHash("sha256")
		.update(`${runId}:${role}:final`)
		.digest("hex")
		.slice(0, 32);

const formatUuid = (raw: string): string =>
	`${raw.slice(0, 8)}-${raw.slice(8, 12)}-4${raw.slice(13, 16)}-8${raw.slice(
		17,
		20,
	)}-${raw.slice(20, 32)}`;

export async function processAgentMessageWebhook({
	db,
	payload,
}: ProcessArgs): Promise<void> {
	const baseId = deriveMessageId(payload.runId, payload.role);
	const id = formatUuid(baseId);

	await db
		.insert(messages)
		.values({
			content: payload.content,
			id,
			metadata: payload.metadata ?? {},
			role: payload.role,
			runId: payload.runId,
			threadId: payload.threadId,
		})
		.onConflictDoUpdate({
			set: {
				content: payload.content,
				metadata: payload.metadata ?? {},
			},
			target: messages.id,
		});
}
