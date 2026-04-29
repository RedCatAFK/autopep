import { describe, expect, it } from "vitest";

import { answerWorkspaceQuestion } from "./workspace-answer";

const workspace = {
	activeRun: {
		errorSummary: null,
		prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
		status: "succeeded",
	},
	artifacts: [
		{
			fileName: "6m0j-source.cif",
			signedUrl: "https://example.com/6m0j-source.cif",
			sourceUrl: "https://files.rcsb.org/download/6M0J.cif",
			type: "source_cif",
		},
	],
	candidates: [
		{
			citationJson: {
				biorxiv: [
					{
						id: "PPR1",
						title: "Spike structure preprint",
						url: "https://doi.org/10.1101/example",
					},
				],
				pubmed: [
					{
						id: "123",
						title: "Spike RBD structure",
						url: "https://pubmed.ncbi.nlm.nih.gov/123/",
					},
				],
			},
			method: "X-RAY DIFFRACTION",
			proteinaReady: true,
			rank: 1,
			rcsbId: "6M0J",
			relevanceScore: 0.91,
			resolutionAngstrom: 2.45,
			selectionRationale: "High-ranking RCSB result with literature support.",
			title: "SARS-CoV-2 spike receptor-binding domain bound to ACE2",
		},
	],
	events: [
		{
			detail: "6M0J source CIF is ready.",
			title: "Ready for Proteina",
			type: "ready_for_proteina",
		},
	],
	targetEntities: [
		{
			name: "SARS-CoV-2 spike receptor binding domain",
			organism: "SARS-CoV-2",
		},
	],
};

describe("answerWorkspaceQuestion", () => {
	it("answers structure questions from ranked candidates", () => {
		expect(
			answerWorkspaceQuestion({
				question: "Which PDB structure did you pick?",
				workspace,
			}),
		).toContain("6M0J");
	});

	it("answers literature questions with PubMed and bioRxiv references", () => {
		const answer = answerWorkspaceQuestion({
			question: "What literature did you review?",
			workspace,
		});

		expect(answer).toContain("Spike RBD structure");
		expect(answer).toContain("Spike structure preprint");
	});

	it("answers compound structure, literature, and CIF questions", () => {
		const answer = answerWorkspaceQuestion({
			question:
				"Which PDB did you select, what bioRxiv evidence did you review, and is the CIF ready to download?",
			workspace,
		});

		expect(answer).toContain("6M0J");
		expect(answer).toContain("6m0j-source.cif");
		expect(answer).toContain("Spike structure preprint");
	});
});
