import { describe, expect, it, vi } from "vitest";

import { processAgentMessageWebhook } from "./webhook";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";

type InsertedRow = {
	contentJson: { text: string; type: string };
	itemType: string;
	role: string;
	runId: string;
	sequence: number;
	threadId: string;
};

const firstInsertedRow = (
	values: ReturnType<typeof vi.fn>,
): InsertedRow | undefined => {
	const call = values.mock.calls[0];
	if (!call) return undefined;
	return call[0] as InsertedRow;
};

/**
 * Minimal Drizzle stub: `db.transaction(cb)` runs the callback with a tx
 * object that records calls to `select`/`insert`/etc. Each select returns
 * predefined rows so the webhook can compute the next sequence and decide
 * whether a duplicate already exists.
 */
const buildDbDouble = (options?: {
	existingAssistantRow?: boolean;
	currentMaxSequence?: number;
}) => {
	const existingAssistantRow = options?.existingAssistantRow ?? false;
	const currentMaxSequence = options?.currentMaxSequence ?? 0;

	const onConflictDoNothing = vi.fn().mockResolvedValue([]);
	const insertValues = vi.fn(() => ({ onConflictDoNothing }));
	const insert = vi.fn(() => ({ values: insertValues }));

	let selectCallIndex = 0;
	const select = vi.fn(() => ({
		from: vi.fn(() => ({
			where: vi.fn((..._args: unknown[]) => {
				const idx = selectCallIndex++;
				if (idx === 0) {
					// existence-check select
					return {
						limit: vi.fn(() =>
							Promise.resolve(
								existingAssistantRow ? [{ id: "existing-id" }] : [],
							),
						),
					};
				}
				// next-sequence select
				return Promise.resolve([{ next: currentMaxSequence + 1 }]);
			}),
		})),
	}));

	const transaction = vi.fn(
		async (
			cb: (tx: { insert: typeof insert; select: typeof select }) => Promise<void>,
		) => {
			await cb({ insert, select });
		},
	);

	return {
		db: { insert, select, transaction } as unknown as Parameters<
			typeof processAgentMessageWebhook
		>[0]["db"],
		insert,
		insertValues,
		onConflictDoNothing,
		select,
		transaction,
	};
};

describe("processAgentMessageWebhook", () => {
	it("inserts an assistant thread_item when none exists yet", async () => {
		const { db, insert, insertValues } = buildDbDouble({
			currentMaxSequence: 4,
		});

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
		const inserted = firstInsertedRow(insertValues);
		expect(inserted).toBeDefined();
		expect(inserted?.itemType).toBe("message");
		expect(inserted?.role).toBe("assistant");
		expect(inserted?.threadId).toBe(THREAD_ID);
		expect(inserted?.runId).toBe(RUN_ID);
		expect(inserted?.contentJson).toEqual({
			text: "Hello!",
			type: "output_text",
		});
		expect(inserted?.sequence).toBe(5);
	});

	it("skips the insert when a prior assistant row already exists", async () => {
		const { db, insert } = buildDbDouble({ existingAssistantRow: true });

		await processAgentMessageWebhook({
			db,
			payload: {
				content: "duplicate retry",
				role: "assistant",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(insert).not.toHaveBeenCalled();
	});

	it("does nothing for non-assistant roles", async () => {
		const { db, insert, transaction } = buildDbDouble();

		await processAgentMessageWebhook({
			db,
			payload: {
				content: "system body",
				role: "system",
				runId: RUN_ID,
				threadId: THREAD_ID,
			},
		});

		expect(transaction).not.toHaveBeenCalled();
		expect(insert).not.toHaveBeenCalled();
	});
});
