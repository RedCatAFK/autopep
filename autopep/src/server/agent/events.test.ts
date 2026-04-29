import { describe, expect, it, vi } from "vitest";

import { appendRunEvent, deriveNextSequence } from "./events";

describe("deriveNextSequence", () => {
	it("starts at 1 when no events exist", () => {
		expect(deriveNextSequence(undefined)).toBe(1);
	});

	it("increments the latest sequence", () => {
		expect(deriveNextSequence(41)).toBe(42);
	});
});

describe("appendRunEvent", () => {
	it("stores compact display JSON and raw JSON separately", async () => {
		const returning = vi.fn().mockResolvedValue([
			{
				id: "event-1",
				sequence: 1,
				type: "tool_call_started",
			},
		]);
		const onConflictDoNothing = vi.fn(() => ({ returning }));
		const values = vi.fn(() => ({ onConflictDoNothing }));
		const insert = vi.fn(() => ({ values }));
		const db = {
			insert,
			select: vi.fn(() => ({
				from: () => ({
					where: () => ({
						orderBy: () => ({
							limit: () => Promise.resolve([]),
						}),
					}),
				}),
			})),
		};

		await appendRunEvent({
			db: db as never,
			display: { toolName: "search_structures" },
			raw: { provider: "agents-sdk", item: { name: "tool_called" } },
			runId: "11111111-1111-4111-8111-111111111111",
			summary: "Searching RCSB",
			title: "Search structures",
			type: "tool_call_started",
		});

		expect(values).toHaveBeenCalledWith(
			expect.objectContaining({
				displayJson: { toolName: "search_structures" },
				rawJson: { provider: "agents-sdk", item: { name: "tool_called" } },
				sequence: 1,
				summary: "Searching RCSB",
			}),
		);
	});

	it("retries past five sequence conflicts before appending", async () => {
		const insertedEvent = {
			id: "event-7",
			sequence: 7,
			type: "tool_call_started",
		};
		const returning = vi
			.fn()
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([])
			.mockResolvedValueOnce([insertedEvent]);
		const onConflictDoNothing = vi.fn(() => ({ returning }));
		const values = vi.fn(() => ({ onConflictDoNothing }));
		const insert = vi.fn(() => ({ values }));
		const select = vi.fn(() => ({
			from: () => ({
				where: () => ({
					orderBy: () => ({
						limit: () => Promise.resolve([{ sequence: 41 }]),
					}),
				}),
			}),
		}));
		const db = { insert, select };

		const result = await appendRunEvent({
			db: db as never,
			runId: "11111111-1111-4111-8111-111111111111",
			title: "Search structures",
			type: "tool_call_started",
		});

		expect(result).toEqual(insertedEvent);
		expect(returning).toHaveBeenCalledTimes(7);
	});
});
