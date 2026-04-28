import { describe, expect, it, vi } from "vitest";

import { searchPubMed } from "./pubmed-client";

describe("searchPubMed", () => {
	it("calls NCBI ESearch JSON and returns lightweight refs", async () => {
		const fetchImpl = vi.fn(async () =>
			Response.json({
				esearchresult: {
					idlist: ["12345", "67890"],
				},
			}),
		) as unknown as typeof fetch;

		await expect(
			searchPubMed({
				fetchImpl,
				query: "SARS-CoV-2 3CL protease structure",
				retmax: 2,
			}),
		).resolves.toEqual([
			{
				id: "12345",
				title: "PubMed result 12345",
				url: "https://pubmed.ncbi.nlm.nih.gov/12345/",
			},
			{
				id: "67890",
				title: "PubMed result 67890",
				url: "https://pubmed.ncbi.nlm.nih.gov/67890/",
			},
		]);

		const [url] = vi.mocked(fetchImpl).mock.calls[0] ?? [];
		expect(url).toBeInstanceOf(URL);
		const searchUrl = url as URL;
		expect(searchUrl.origin).toBe("https://eutils.ncbi.nlm.nih.gov");
		expect(searchUrl.searchParams.get("db")).toBe("pubmed");
		expect(searchUrl.searchParams.get("retmode")).toBe("json");
		expect(searchUrl.searchParams.get("retmax")).toBe("2");
		expect(searchUrl.searchParams.get("term")).toBe(
			"SARS-CoV-2 3CL protease structure",
		);
	});
});
