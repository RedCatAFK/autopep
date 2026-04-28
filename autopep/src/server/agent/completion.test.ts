import { describe, expect, it } from "vitest";

import { validateRunCompletion } from "./completion";

describe("validateRunCompletion", () => {
	it("selects the lowest-rank proteina-ready candidate with a CIF artifact", () => {
		expect(
			validateRunCompletion({
				candidates: [
					{ id: "candidate-1", rank: 2, proteinaReady: true },
					{ id: "candidate-2", rank: 1, proteinaReady: true },
					{ id: "candidate-3", rank: 0, proteinaReady: false },
				],
				artifacts: [
					{
						id: "artifact-1",
						candidateId: "candidate-1",
						type: "prepared_cif",
					},
					{ id: "artifact-2", candidateId: "candidate-2", type: "source_cif" },
				],
			}),
		).toEqual({
			ok: true,
			selectedArtifactId: "artifact-2",
			selectedCandidateId: "candidate-2",
		});
	});

	it("rejects runs without a proteina-ready candidate", () => {
		expect(
			validateRunCompletion({
				candidates: [
					{ id: "candidate-1", rank: 1, proteinaReady: false },
					{ id: "candidate-2", rank: 2, proteinaReady: false },
				],
				artifacts: [
					{
						id: "artifact-1",
						candidateId: "candidate-1",
						type: "prepared_cif",
					},
				],
			}),
		).toEqual({
			ok: false,
			reason: "No proteina-ready candidate exists.",
		});
	});

	it("rejects a ready candidate linked only to non-CIF artifacts", () => {
		expect(
			validateRunCompletion({
				candidates: [{ id: "candidate-1", rank: 1, proteinaReady: true }],
				artifacts: [
					{ id: "artifact-1", candidateId: "candidate-1", type: "report" },
					{ id: "artifact-2", candidateId: "candidate-1", type: "fasta" },
				],
			}),
		).toEqual({
			ok: false,
			reason:
				"No proteina-ready CIF artifact is linked to the selected candidate.",
		});
	});
});
