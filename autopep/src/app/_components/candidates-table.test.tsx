// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CandidatesTable } from "./candidates-table";

describe("CandidatesTable", () => {
	it("renders an empty state when no candidates exist", () => {
		render(<CandidatesTable candidateScores={[]} candidates={[]} />);
		expect(screen.getByText(/no candidates yet/i)).toBeInTheDocument();
	});

	it("merges per-candidate scores and shows the aggregate label", () => {
		render(
			<CandidatesTable
				candidateScores={[
					{
						candidateId: "c1",
						label: null,
						scorer: "dscript",
						unit: null,
						value: 0.91,
					},
					{
						candidateId: "c1",
						label: null,
						scorer: "prodigy",
						unit: "kcal/mol",
						value: -10.2,
					},
					{
						candidateId: "c1",
						label: "strong binder",
						scorer: "protein_interaction_aggregate",
						unit: null,
						value: 0.87,
					},
				]}
				candidates={[
					{
						id: "c1",
						method: "X-RAY",
						organism: "SARS-CoV-2",
						rank: 1,
						resolutionAngstrom: 2.4,
						title: "spike RBD",
					},
				]}
			/>,
		);
		expect(screen.getByText("spike RBD")).toBeInTheDocument();
		expect(screen.getByText("SARS-CoV-2")).toBeInTheDocument();
		expect(screen.getByText("X-RAY")).toBeInTheDocument();
		expect(screen.getByText(/0\.91/)).toBeInTheDocument();
		expect(screen.getByText(/-10\.2/)).toBeInTheDocument();
		expect(screen.getByText(/strong binder/i)).toBeInTheDocument();
	});

	it("calls onOpenCandidate when the action button is clicked", async () => {
		const user = userEvent.setup();
		const onOpenCandidate = vi.fn();
		render(
			<CandidatesTable
				candidateScores={[]}
				candidates={[{ id: "c1", rank: 1, title: "spike RBD" }]}
				onOpenCandidate={onOpenCandidate}
			/>,
		);
		await user.click(screen.getByRole("button", { name: /open structure/i }));
		expect(onOpenCandidate).toHaveBeenCalledWith("c1");
	});
});
