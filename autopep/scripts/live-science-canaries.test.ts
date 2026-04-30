import { describe, expect, it } from "vitest";

import {
	buildCanaryPrompt,
	type CanarySnapshot,
	DEFAULT_LIVE_CANARIES,
	evaluateCanarySnapshot,
	LIVE_CANARY_REQUIRED_TOOLS,
	type LiveCanaryThresholds,
} from "./live-science-canaries";

const thresholds: LiveCanaryThresholds = {
	allowFailedInferences: false,
	maxTotalMs: 45 * 60 * 1000,
	minArtifacts: 3,
	minCandidates: 1,
	minOkScoreRows: 1,
	minScoreRows: 1,
	requireCitation: true,
	requireExpectedPdbHit: true,
	timeoutMs: 45 * 60 * 1000,
};

const primaryCanary =
	DEFAULT_LIVE_CANARIES[0] ??
	(() => {
		throw new Error("Expected at least one default live canary.");
	})();

const baseSnapshot = (): CanarySnapshot => {
	const events: CanarySnapshot["events"] = [
		{ sequence: 1, type: "run_started" },
	];
	let sequence = 2;
	for (const tool of LIVE_CANARY_REQUIRED_TOOLS) {
		const callId = `call-${tool}`;
		events.push({
			displayJson: { callId, name: tool },
			sequence: sequence++,
			type: "tool_call_started",
		});
		events.push({
			displayJson: { callId },
			sequence: sequence++,
			type: "tool_call_completed",
		});
	}
	events.push({ sequence: sequence++, type: "run_completed" });

	return {
		artifacts: [
			{
				kind: "pdb",
				metadataJson: { pdbId: "6LU7" },
				name: "6LU7.pdb",
				storageKey: "workspaces/w/runs/r/inputs/6LU7.pdb",
			},
			{
				kind: "proteina_result",
				name: "candidate-1.pdb",
				storageKey: "workspaces/w/runs/r/proteina-result/candidate-1.pdb",
			},
			{
				kind: "chai_result",
				name: "candidate-1-complex.cif",
				storageKey: "workspaces/w/runs/r/chai-result/candidate-1.cif",
			},
		],
		candidates: [
			{
				id: "11111111-1111-4111-8111-111111111111",
				rank: 1,
				sequence: "ACDEFGHIK",
				title: "Proteina design #1",
			},
		],
		events,
		inferences: [
			{ modelName: "proteina_complexa", status: "completed" },
			{ modelName: "chai_1", status: "completed" },
			{ modelName: "protein_interaction_scoring", status: "completed" },
		],
		run: {
			finishedAt: new Date(),
			id: "run-1",
			startedAt: new Date(),
			status: "completed",
		},
		scores: [
			{
				scorer: "dscript",
				status: "ok",
				value: 0.84,
			},
			{
				scorer: "prodigy",
				status: "ok",
				value: -9.6,
			},
		],
		threadItems: [
			{
				contentJson: {
					content: [
						{
							text: "Candidate 1 used PDB 6LU7, D-SCRIPT 0.84, PRODIGY -9.6 kcal/mol, PMID 123.",
							type: "output_text",
						},
					],
					role: "assistant",
					type: "message",
				},
				itemType: "message",
				role: "assistant",
				sequence: 10,
			},
		],
	};
};

describe("live science canary helpers", () => {
	it("builds a bounded prompt that names the required live tools", () => {
		const prompt = buildCanaryPrompt(primaryCanary);

		expect(prompt).toContain("num_candidates=3");
		expect(prompt).toContain("Do not run extra Proteina batches");
		for (const tool of LIVE_CANARY_REQUIRED_TOOLS) {
			expect(prompt).toContain(tool);
		}
	});

	it("passes a complete deployed-stack style snapshot", () => {
		const result = evaluateCanarySnapshot({
			definition: primaryCanary,
			snapshot: baseSnapshot(),
			thresholds,
			totalMs: 120_000,
		});

		expect(result.passed).toBe(true);
		expect(result.metrics.candidateCount).toBe(1);
		expect(result.metrics.expectedPdbHit).toBe(true);
	});

	it("fails when scores and the score-backed final answer are missing", () => {
		const snapshot = baseSnapshot();
		snapshot.scores = [];
		snapshot.threadItems = [
			{
				contentJson: { text: "Candidate 1 is ready." },
				itemType: "message",
				role: "assistant",
				sequence: 10,
			},
		];

		const result = evaluateCanarySnapshot({
			definition: primaryCanary,
			snapshot,
			thresholds,
			totalMs: 120_000,
		});

		expect(result.passed).toBe(false);
		expect(result.failures).toContain("expected at least 1 score rows, saw 0");
		expect(result.failures).toContain(
			"final assistant message does not mention scores",
		);
	});
});
