import { describe, expect, it } from "vitest";

import { buildStreamItems } from "./build-stream-items";

describe("buildStreamItems", () => {
	it("interleaves messages and tool calls in order", () => {
		const items = buildStreamItems({
			messages: [
				{
					id: "m1",
					role: "user",
					content: "go",
					createdAt: "2026-04-30T10:00:00Z",
				},
				{
					id: "m2",
					role: "assistant",
					content: "ok",
					createdAt: "2026-04-30T10:00:05Z",
				},
			],
			events: [
				{
					id: "e1",
					sequence: 1,
					type: "tool_call_started",
					createdAt: "2026-04-30T10:00:01Z",
					displayJson: {
						callId: "c1",
						name: "rcsb_structure_search",
						args: {},
					},
				},
				{
					id: "e2",
					sequence: 2,
					type: "tool_call_completed",
					createdAt: "2026-04-30T10:00:02Z",
					displayJson: { callId: "c1", output: "ok" },
				},
			],
		});

		expect(items.map((item) => item.kind)).toEqual([
			"user_message",
			"tool_call",
			"assistant_message",
		]);
		const toolCall = items[1];
		if (!toolCall || toolCall.kind !== "tool_call") {
			throw new Error("expected tool_call");
		}
		expect(toolCall.status).toBe("completed");
	});

	it("hides diagnostic events", () => {
		const items = buildStreamItems({
			messages: [],
			events: [
				{
					id: "e1",
					sequence: 1,
					type: "assistant_message_started",
					createdAt: "2026-04-30T10:00:01Z",
					displayJson: {},
				},
			],
		});
		expect(items).toEqual([]);
	});

	it("surfaces an OpenAI prompt block as a blocked chat item", () => {
		const items = buildStreamItems({
			messages: [],
			events: [
				{
					id: "e-blocked",
					sequence: 2,
					type: "run_failed",
					createdAt: "2026-04-30T10:00:03Z",
					displayJson: {
						error:
							"Invalid prompt: we've limited access to this content for safety reasons.",
						message: "Message blocked by OpenAI.",
						provider: "openai",
						reason: "openai_prompt_blocked",
					},
				},
			],
		});

		expect(items).toEqual([
			{
				kind: "run_error",
				id: "e-blocked",
				content: "Message blocked by OpenAI.",
				detail:
					"Invalid prompt: we've limited access to this content for safety reasons.",
				tone: "blocked",
			},
		]);
	});
});
