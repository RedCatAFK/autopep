import { describe, expect, it } from "vitest";

import { buildArtifactKey } from "./keys";

describe("buildArtifactKey", () => {
	it("builds candidate artifact keys", () => {
		expect(
			buildArtifactKey({
				projectId: "project-1",
				runId: "run-1",
				candidateId: "candidate-1",
				type: "prepared_cif",
				fileName: "6m0j-rbd.cif",
			}),
		).toBe(
			"projects/project-1/runs/run-1/candidates/candidate-1/prepared_cif/6m0j-rbd.cif",
		);
	});

	it("builds run artifact keys", () => {
		expect(
			buildArtifactKey({
				projectId: "project-1",
				runId: "run-1",
				type: "raw_search_json",
				fileName: "rcsb-search-results.json",
			}),
		).toBe(
			"projects/project-1/runs/run-1/run-artifacts/raw_search_json/rcsb-search-results.json",
		);
	});

	it("sanitizes type and filename without changing ids", () => {
		expect(
			buildArtifactKey({
				projectId: "Project 1",
				runId: "Run/1",
				candidateId: "Candidate 1",
				type: " Prepared CIF ",
				fileName: " 6M0J RBD!!.CIF ",
			}),
		).toBe(
			"projects/Project 1/runs/Run/1/candidates/Candidate 1/prepared-cif/6m0j-rbd-.cif",
		);
	});
});
