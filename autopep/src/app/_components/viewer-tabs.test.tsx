// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./file-preview", () => ({
	FilePreview: (props: {
		artifactId: string;
		candidateId?: string | null;
		fileName: string;
		onProteinSelection?: (selection: {
			artifactId: string;
			candidateId: string | null;
			label: string;
			selector: Record<string, unknown>;
		}) => void;
	}) => (
		<button
			onClick={() =>
				props.onProteinSelection?.({
					artifactId: props.artifactId,
					candidateId: props.candidateId ?? null,
					label: `${props.fileName} residue 145`,
					selector: { residueRanges: [{ end: 145, start: 145 }] },
				})
			}
			type="button"
		>
			Select {props.fileName}
		</button>
	),
}));

import { type ViewerTab, ViewerTabs } from "./viewer-tabs";

describe("ViewerTabs", () => {
	it("renders the empty state", () => {
		render(
			<ViewerTabs
				activeTabId={null}
				candidateScores={[]}
				candidates={[]}
				onClose={() => {}}
				onSelect={() => {}}
				tabs={[]}
			/>,
		);
		expect(
			screen.getByText(/select a file from the right panel/i),
		).toBeInTheDocument();
	});

	it("auto-pins the candidates tab when candidates exist", () => {
		render(
			<ViewerTabs
				activeTabId="candidates"
				candidateScores={[]}
				candidates={[{ id: "c1", rank: 1, title: "spike RBD" }]}
				onClose={() => {}}
				onSelect={() => {}}
				tabs={[]}
			/>,
		);
		expect(
			screen.getByRole("tab", { name: /candidates/i }),
		).toBeInTheDocument();
		expect(screen.getByText(/spike RBD/i)).toBeInTheDocument();
	});

	it("calls onClose when a closable tab's × is clicked", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();
		const tabs: ViewerTab[] = [
			{
				artifactId: "a1",
				fileName: "test.cif",
				id: "f1",
				kind: "file",
				signedUrl: "https://example.com/test.cif",
			},
		];
		render(
			<ViewerTabs
				activeTabId="f1"
				candidateScores={[]}
				candidates={[]}
				onClose={onClose}
				onSelect={() => {}}
				tabs={tabs}
			/>,
		);
		await user.click(screen.getByRole("button", { name: /close test\.cif/i }));
		expect(onClose).toHaveBeenCalledWith("f1");
	});

	it("passes active file selections upward with artifact and candidate ids", async () => {
		const user = userEvent.setup();
		const onProteinSelection = vi.fn();
		const tabs: ViewerTab[] = [
			{
				artifactId: "artifact-1",
				candidateId: "candidate-1",
				fileName: "test.cif",
				id: "f1",
				kind: "file",
				signedUrl: "https://example.com/test.cif",
			},
		];
		render(
			<ViewerTabs
				activeTabId="f1"
				candidateScores={[]}
				candidates={[]}
				onClose={() => {}}
				onProteinSelection={onProteinSelection}
				onSelect={() => {}}
				tabs={tabs}
			/>,
		);

		await user.click(screen.getByRole("button", { name: /select test\.cif/i }));

		expect(onProteinSelection).toHaveBeenCalledWith({
			artifactId: "artifact-1",
			candidateId: "candidate-1",
			label: "test.cif residue 145",
			selector: { residueRanges: [{ end: 145, start: 145 }] },
		});
	});
});
