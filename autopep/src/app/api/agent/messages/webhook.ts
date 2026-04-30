import { and, eq, sql } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import { threadItems } from "@/server/db/schema";

export type AgentMessageWebhookPayload = {
	runId: string;
	threadId: string;
	role: "assistant" | "system" | "user";
	content: string;
	metadata?: Record<string, unknown>;
};

type ProcessArgs = {
	db: typeof appDb;
	payload: AgentMessageWebhookPayload;
};

/**
 * Persist an agent-emitted message into `thread_items`.
 *
 * Phase 0 transitional: this webhook is invoked from `runner.py`'s
 * `_flush_assistant_message` after a tool-less reply. In Phase 1 the runner
 * stops calling it and this route is deleted.
 *
 * Idempotency: there is no `(run_id, role, item_type)` unique constraint on
 * `thread_items`, so we look up an existing assistant `message` row for the
 * same `(threadId, runId)` first and skip the insert if one exists. The
 * `(threadId, sequence)` unique index still protects against double-writes
 * if two callers race past the existence check — Postgres will reject the
 * second insert.
 */
export async function processAgentMessageWebhook({
	db,
	payload,
}: ProcessArgs): Promise<void> {
	if (payload.role !== "assistant") {
		// Phase 0 only writes assistant text via this webhook. Other roles are
		// emitted by the application server itself, never by the agent.
		return;
	}

	await db.transaction(async (tx) => {
		const existing = await tx
			.select({ id: threadItems.id })
			.from(threadItems)
			.where(
				and(
					eq(threadItems.threadId, payload.threadId),
					eq(threadItems.runId, payload.runId),
					eq(threadItems.role, "assistant"),
					eq(threadItems.itemType, "message"),
				),
			)
			.limit(1);

		if (existing.length > 0) {
			return;
		}

		const sequenceRows = await tx
			.select({
				next: sql<number>`coalesce(max(${threadItems.sequence}), 0) + 1`,
			})
			.from(threadItems)
			.where(eq(threadItems.threadId, payload.threadId));

		const sequence = Number(sequenceRows[0]?.next ?? 1);

		await tx
			.insert(threadItems)
			.values({
				contentJson: { text: payload.content, type: "output_text" },
				itemType: "message",
				role: "assistant",
				runId: payload.runId,
				sequence,
				threadId: payload.threadId,
			})
			.onConflictDoNothing();
	});
}
