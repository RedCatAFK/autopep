// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MolstarStage, type ProteinSelection } from "./molstar-stage";

describe("MolstarStage", () => {
	it("renders compact viewer actions", () => {
		render(
			<MolstarStage
				artifact={{
					id: "artifact-1",
					label: "6M0J prepared CIF",
					name: "6m0j-prepared.cif",
					url: "https://example.test/6m0j.cif",
				}}
				candidate={{ id: "candidate-1", title: "6M0J 3CL protease" }}
				onProteinSelection={vi.fn()}
			/>,
		);

		expect(screen.getByLabelText("Fullscreen viewer")).toBeInTheDocument();
		expect(screen.getByLabelText("Download structure")).toBeInTheDocument();
		expect(screen.getByLabelText("Reset camera")).toBeInTheDocument();
		expect(screen.getByLabelText("Viewer settings")).toBeInTheDocument();
	});

	it("surfaces protein selections from the viewer", () => {
		const onProteinSelection = vi.fn();
		const FakeViewer = ({
			onProteinSelection: onSelection,
		}: {
			onProteinSelection?: (selection: ProteinSelection) => void;
		}) => (
			<button
				onClick={() =>
					onSelection?.({
						artifactId: "artifact-1",
						candidateId: "candidate-1",
						label: "6M0J chain A residue 145",
						selector: {
							authAsymId: "A",
							residueRanges: [{ end: 145, start: 145 }],
						},
					})
				}
				type="button"
			>
				Select residue
			</button>
		);

		render(
			<MolstarStage
				artifact={{
					id: "artifact-1",
					label: "6M0J prepared CIF",
					name: "6m0j-prepared.cif",
					url: "https://example.test/6m0j.cif",
				}}
				candidate={{ id: "candidate-1", title: "6M0J 3CL protease" }}
				onProteinSelection={onProteinSelection}
				viewerComponent={FakeViewer}
			/>,
		);

		fireEvent.click(screen.getByText("Select residue"));

		expect(onProteinSelection).toHaveBeenCalledWith(
			expect.objectContaining({
				artifactId: "artifact-1",
				candidateId: "candidate-1",
				label: "6M0J chain A residue 145",
			}),
		);
		expect(screen.getByText("6M0J chain A residue 145")).toBeInTheDocument();
	});
});
