import { describe, expect, it, vi } from "vitest";

import { inferWorkspaceNameWithAi } from "./auto-name";

describe("inferWorkspaceNameWithAi", () => {
	it("returns a 3-6 word title from gpt-5.4-mini", async () => {
		const ai = vi.fn(async () => ({
			choices: [{ message: { content: "Spike RBD binder design" } }],
		}));
		const result = await inferWorkspaceNameWithAi({
			prompt: "design a protein binder for SARS-CoV-2 spike RBD",
			openaiClient: ai,
		});
		expect(result).toBe("Spike RBD binder design");
	});

	it("falls back to first-line trim on AI error", async () => {
		const ai = vi.fn(async () => {
			throw new Error("boom");
		});
		const result = await inferWorkspaceNameWithAi({
			prompt: "  design protein binder  \n more",
			openaiClient: ai,
		});
		expect(result).toBe("design protein binder");
	});

	it("strips quotes and trailing punctuation, caps to 6 words", async () => {
		const ai = vi.fn(async () => ({
			choices: [
				{
					message: {
						content: '"Designing a Spike RBD Binder for SARS-CoV-2 Today!"',
					},
				},
			],
		}));
		const result = await inferWorkspaceNameWithAi({
			prompt: "design",
			openaiClient: ai,
		});
		expect(result).toBe("Designing a Spike RBD Binder for");
	});
});
