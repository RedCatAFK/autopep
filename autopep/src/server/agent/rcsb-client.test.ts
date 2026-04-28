import { describe, expect, it, vi } from "vitest";

import { downloadRcsbCif, searchRcsbEntries } from "./rcsb-client";

describe("searchRcsbEntries", () => {
	it("posts a full-text terminal query and returns identifiers", async () => {
		const fetchImpl = vi.fn(async () =>
			Response.json({
				result_set: [
					{ identifier: "7K3T" },
					{ identifier: "6LU7" },
					{ identifier: 123 },
				],
			}),
		) as unknown as typeof fetch;

		await expect(
			searchRcsbEntries({
				fetchImpl,
				query: "SARS-CoV-2 3CL protease",
				rows: 2,
			}),
		).resolves.toEqual(["7K3T", "6LU7"]);

		expect(fetchImpl).toHaveBeenCalledWith(
			"https://search.rcsb.org/rcsbsearch/v2/query",
			expect.objectContaining({
				method: "POST",
			}),
		);

		const [, init] = vi.mocked(fetchImpl).mock.calls[0] ?? [];
		expect(JSON.parse(String(init?.body))).toMatchObject({
			query: {
				parameters: { value: "SARS-CoV-2 3CL protease" },
				service: "full_text",
				type: "terminal",
			},
			request_options: {
				pager: {
					rows: 2,
					start: 0,
				},
			},
			return_type: "entry",
		});
	});
});

describe("downloadRcsbCif", () => {
	it("downloads CIF text and validates a data block", async () => {
		const fetchImpl = vi.fn(
			async () => new Response("data_6LU7\n#\n"),
		) as unknown as typeof fetch;

		await expect(downloadRcsbCif({ entryId: "6lu7", fetchImpl })).resolves.toBe(
			"data_6LU7\n#\n",
		);

		expect(fetchImpl).toHaveBeenCalledWith(
			"https://files.rcsb.org/download/6LU7.cif",
		);
	});

	it("rejects downloads without a CIF data block", async () => {
		const fetchImpl = vi.fn(
			async () => new Response("not cif"),
		) as unknown as typeof fetch;

		await expect(
			downloadRcsbCif({ entryId: "6lu7", fetchImpl }),
		).rejects.toThrow("invalid");
	});
});
