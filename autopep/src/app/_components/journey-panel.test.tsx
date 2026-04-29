// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JourneyPanel } from "./journey-panel";

describe("JourneyPanel", () => {
	it("shows one-loop candidate score leaves without a branch-again action", () => {
		render(
			<JourneyPanel
				activeRunStatus="completed"
				artifacts={[{ id: "artifact-1", kind: "pdb", name: "candidate-1.pdb" }]}
				candidateScores={[
					{
						candidateId: "candidate-1",
						label: "likely_binder",
						scorer: "protein_interaction_aggregate",
						unit: null,
						value: null,
					},
					{
						candidateId: "candidate-1",
						label: null,
						scorer: "dscript",
						unit: "probability",
						value: 0.74,
					},
					{
						candidateId: "candidate-1",
						label: null,
						scorer: "prodigy",
						unit: "kcal/mol",
						value: -7.4,
					},
				]}
				candidates={[{ id: "candidate-1", rank: 1, title: "Candidate 1" }]}
				objective="Generate a protein that binds to 3CL-protease"
			/>,
		);

		expect(screen.getByText("likely_binder")).toBeInTheDocument();
		expect(screen.getByText("D-SCRIPT 0.74")).toBeInTheDocument();
		expect(screen.getByText("PRODIGY -7.4 kcal/mol")).toBeInTheDocument();
		expect(screen.getByText("MVP loop complete")).toBeInTheDocument();
	});
});
