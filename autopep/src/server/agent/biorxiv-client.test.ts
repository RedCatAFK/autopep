import { describe, expect, it, vi } from "vitest";

import { searchBioRxivPreprints } from "./biorxiv-client";

describe("searchBioRxivPreprints", () => {
	it("searches Europe PMC preprints and keeps bioRxiv-like records", async () => {
		const fetchImpl = vi.fn().mockResolvedValue({
			json: async () => ({
				resultList: {
					result: [
						{
							authorString: "Walls AC, et al.",
							doi: "10.1101/2020.02.19.956581",
							firstPublicationDate: "2020-02-20",
							id: "PPR112233",
							journalTitle: "bioRxiv",
							source: "PPR",
							title:
								"Structure, Function, and Antigenicity of the SARS-CoV-2 Spike Glycoprotein",
						},
						{
							doi: "10.21203/rs.3.rs-12345/v1",
							id: "PPR445566",
							journalTitle: "Research Square",
							source: "PPR",
							title: "A non-bioRxiv preprint",
						},
					],
				},
			}),
			ok: true,
		});

		const refs = await searchBioRxivPreprints({
			fetchImpl,
			limit: 5,
			query: "SARS-CoV-2 spike structure",
		});

		expect(fetchImpl).toHaveBeenCalledWith(
			expect.objectContaining({
				searchParams: expect.any(URLSearchParams),
			}),
		);
		expect(refs).toEqual([
			{
				authors: "Walls AC, et al.",
				doi: "10.1101/2020.02.19.956581",
				id: "PPR112233",
				publishedAt: "2020-02-20",
				source: "PPR",
				title:
					"Structure, Function, and Antigenicity of the SARS-CoV-2 Spike Glycoprotein",
				url: "https://doi.org/10.1101%2F2020.02.19.956581",
			},
		]);
	});

	it("throws on failed Europe PMC responses", async () => {
		await expect(
			searchBioRxivPreprints({
				fetchImpl: vi.fn().mockResolvedValue({
					ok: false,
					status: 503,
				}),
				limit: 2,
				query: "RBD",
			}),
		).rejects.toThrow("bioRxiv preprint search failed with 503");
	});
});
