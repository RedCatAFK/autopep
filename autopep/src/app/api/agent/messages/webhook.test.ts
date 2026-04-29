import { describe, expect, it, vi } from "vitest";

import { processAgentMessageWebhook } from "./webhook";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";

type InsertedRow = {
	content: string;
	id: string;
	metadata: Record<string, unknown>;
	role: string;
	threadId: string;
	runId: string;
};

const firstInsertedRow = (values: ReturnType<typeof vi.fn>): InsertedRow => {
	const call = values.mock.calls[0];
	if (!call) {
		throw new Error("expected values() to have been called at least once");
	}
	return call[0] as InsertedRow;
};

const buildDbDouble = () => {
	const onConflictDoUpdate = vi.fn().mockResolvedValue([{ id: "msg-1" }]);
	const values = vi.fn(() => ({ onConflictDoUpdate }));
	const insert = vi.fn(() => ({ values }));
	return {
		db: { insert } as unknown as Parameters<
			typeof processAgentMessageWebhook
		>[0]["db"],
		insert,
		onConflictDoUpdate,
		values,
	};
};

describe("processAgentMessageWebhook", () => {
	it("inserts a deterministic message row for an assistant response", async () => {
		const { db, insert, values, onConflictDoUpdate } = buildDbDouble();

		await processAgentMessageWebhook({
			db,
			payload: {
				content: "Hello!",
				metadata: { finishReason: "stop", model: "gpt-5.5", tokenCount: 12 },
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(insert).toHaveBeenCalledTimes(1);
		expect(values).toHaveBeenCalledTimes(1);
		expect(onConflictDoUpdate).toHaveBeenCalledTimes(1);

		const inserted = firstInsertedRow(values);
		expect(inserted.content).toBe("Hello!");
		expect(inserted.role).toBe("assistant");
		expect(inserted.threadId).toBe(THREAD_ID);
		expect(inserted.runId).toBe(RUN_ID);
		expect(inserted.metadata).toEqual({
			finishReason: "stop",
			model: "gpt-5.5",
			tokenCount: 12,
		});
		expect(inserted.id).toMatch(
			/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/,
		);
	});

	it("derives the same id for the same runId+role pair across calls", async () => {
		const first = buildDbDouble();
		const second = buildDbDouble();

		await processAgentMessageWebhook({
			db: first.db,
			payload: {
				content: "first",
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});
		await processAgentMessageWebhook({
			db: second.db,
			payload: {
				content: "second",
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(firstInsertedRow(first.values).id).toBe(
			firstInsertedRow(second.values).id,
		);
	});

	it("derives different ids for different roles", async () => {
		const first = buildDbDouble();
		const second = buildDbDouble();

		await processAgentMessageWebhook({
			db: first.db,
			payload: {
				content: "assistant body",
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});
		await processAgentMessageWebhook({
			db: second.db,
			payload: {
				content: "system body",
				role: "system",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(firstInsertedRow(first.values).id).not.toBe(
			firstInsertedRow(second.values).id,
		);
	});

	it("defaults metadata to an empty object when omitted", async () => {
		const { db, values } = buildDbDouble();

		await processAgentMessageWebhook({
			db,
			payload: {
				content: "no metadata",
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(firstInsertedRow(values).metadata).toEqual({});
	});
});
