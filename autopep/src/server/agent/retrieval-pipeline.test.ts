import { afterEach, describe, expect, it, vi } from "vitest";

import { rankRcsbCandidates } from "./retrieval-pipeline";

describe("rankRcsbCandidates", () => {
	afterEach(() => {
		vi.doUnmock("@/env");
		vi.doUnmock("@/server/artifacts/r2");
		vi.doUnmock("./biorxiv-client");
		vi.doUnmock("./events");
		vi.doUnmock("./pubmed-client");
		vi.doUnmock("./rcsb-client");
		vi.resetModules();
	});

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

	it("uses requestedTopK from run SDK state for structure search", async () => {
		vi.resetModules();

		const appendRunEvent = vi.fn().mockResolvedValue(undefined);
		const searchRcsbEntries = vi.fn().mockResolvedValue([]);

		vi.doMock("@/env", () => ({
			env: {
				R2_BUCKET: "test-bucket",
			},
		}));
		vi.doMock("@/server/artifacts/r2", () => ({
			r2ArtifactStore: {
				upload: vi.fn(),
			},
		}));
		vi.doMock("./biorxiv-client", () => ({
			searchBioRxivPreprints: vi.fn(),
		}));
		vi.doMock("./events", () => ({
			appendRunEvent,
		}));
		vi.doMock("./pubmed-client", () => ({
			searchPubMed: vi.fn(),
		}));
		vi.doMock("./rcsb-client", () => ({
			downloadRcsbCif: vi.fn(),
			getRcsbCifUrl: vi.fn(),
			getRcsbEntryMetadata: vi.fn(),
			searchRcsbEntries,
		}));

		const { runCifRetrievalPipeline } = await import("./retrieval-pipeline");
		const runId = "11111111-1111-4111-8111-111111111111";
		const where = vi.fn().mockResolvedValue([]);
		const set = vi.fn(() => ({ where }));
		const update = vi.fn(() => ({ set }));
		const db = {
			query: {
				agentRuns: {
					findFirst: vi.fn().mockResolvedValue({
						id: runId,
						prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
						sdkStateJson: { requestedTopK: 7 },
						startedAt: null,
						workspaceId: "22222222-2222-4222-8222-222222222222",
					}),
				},
			},
			update,
		};

		await expect(
			runCifRetrievalPipeline({ db: db as never, runId }),
		).rejects.toThrow("No RCSB CIF structures found");

		expect(searchRcsbEntries).toHaveBeenCalledWith(
			expect.objectContaining({
				rows: 7,
			}),
		);
	});
});
