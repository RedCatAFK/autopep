import { describe, expect, it } from "vitest";

import { rankRcsbCandidates } from "./retrieval-pipeline";

describe("rankRcsbCandidates", () => {
	it("uses RCSB metadata to rank candidates and keeps readiness false", () => {
		const candidates = rankRcsbCandidates({
			biorxivRefs: [
				{
					authors: "Zhang Y",
					doi: "10.1101/2020.01.01.000001",
					id: "PPR1",
					publishedAt: "2020-01-01",
					source: "PPR",
					title: "Preprint protease structure",
					url: "https://doi.org/10.1101/2020.01.01.000001",
				},
			],
			metadataById: new Map([
				[
					"AAAA",
					{
						method: null,
						rcsbId: "AAAA",
						resolutionAngstrom: null,
						title: "Unrelated structure",
					},
				],
				[
					"BBBB",
					{
						method: "X-RAY DIFFRACTION",
						rcsbId: "BBBB",
						resolutionAngstrom: 1.7,
						title: "SARS-CoV-2 main protease high resolution structure",
					},
				],
			]),
			pubmedRefs: [
				{
					id: "123",
					title: "Main protease structure",
					url: "https://pubmed.ncbi.nlm.nih.gov/123/",
				},
			],
			rcsbIds: ["AAAA", "BBBB"],
			target: {
				aliases: ["Mpro"],
				name: "SARS-CoV-2 main protease",
				organism: "SARS-CoV-2",
				rationale: "test target",
				role: "target",
				uniprotId: null,
			},
		});

		expect(candidates[0]).toMatchObject({
			method: "X-RAY DIFFRACTION",
			proteinaReady: false,
			rank: 1,
			rcsbId: "BBBB",
			resolutionAngstrom: 1.7,
			title: "SARS-CoV-2 main protease high resolution structure",
		});
		expect(candidates[1]).toMatchObject({
			proteinaReady: false,
			rank: 2,
			rcsbId: "AAAA",
		});
		expect(candidates[0]?.selectionRationale).toContain(
			"1 PubMed reference considered",
		);
		expect(candidates[0]?.selectionRationale).toContain(
			"1 bioRxiv preprint considered",
		);
	});
});
