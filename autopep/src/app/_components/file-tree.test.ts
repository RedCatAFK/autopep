import { describe, expect, it } from "vitest";

import { groupArtifacts } from "./file-tree";

describe("groupArtifacts", () => {
	it("places attachments under Attachments/", () => {
		const groups = groupArtifacts({
			artifacts: [
				{
					id: "a1",
					fileName: "ref.pdb",
					kind: "attachment",
					candidateId: null,
					runId: "r1",
					signedUrl: null,
					byteSize: 1024,
				},
			],
			candidates: [],
			runs: [],
		});
		expect(groups).toContainEqual(
			expect.objectContaining({
				label: "Attachments",
				files: expect.arrayContaining([
					expect.objectContaining({ fileName: "ref.pdb" }),
				]),
			}),
		);
	});

	it("groups candidate artifacts under Candidates/<rank> <title>/", () => {
		const groups = groupArtifacts({
			artifacts: [
				{
					id: "a1",
					fileName: "prepared.cif",
					kind: "cif",
					candidateId: "c1",
					runId: "r1",
					signedUrl: null,
					byteSize: 0,
				},
			],
			candidates: [{ id: "c1", rank: 1, title: "spike RBD" }],
			runs: [],
		});
		const cand = groups.find((group) => group.kind === "candidate");
		expect(cand?.label).toBe("#1 spike RBD");
	});
});
