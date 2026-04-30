// @vitest-environment jsdom

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreview } from "./file-preview";

describe("FilePreview", () => {
	beforeEach(() => {
		vi.stubGlobal(
			"fetch",
			vi.fn(async () => ({
				ok: true,
				text: async () => "line one\nline two\nline three",
			})),
		);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("renders a download skeleton for unknown extensions", () => {
		render(
			<FilePreview
				artifactId="a1"
				fileName="mystery.bin"
				signedUrl="https://example.com/mystery.bin"
			/>,
		);
		expect(screen.getByText(/no preview available/i)).toBeInTheDocument();
		const link = screen.getByRole("link", { name: /download/i });
		expect(link).toHaveAttribute("href", "https://example.com/mystery.bin");
	});

	it("renders an image preview for image extensions", () => {
		render(
			<FilePreview
				artifactId="a1"
				fileName="figure.png"
				signedUrl="https://example.com/figure.png"
			/>,
		);
		const img = screen.getByRole("img", { name: /figure\.png/i });
		expect(img).toHaveAttribute("src", "https://example.com/figure.png");
	});

	it("fetches and renders text content for text-like files", async () => {
		render(
			<FilePreview
				artifactId="a1"
				fileName="seq.fasta"
				signedUrl="https://example.com/seq.fasta"
			/>,
		);
		await waitFor(() => {
			expect(screen.getByText(/line one/)).toBeInTheDocument();
		});
		expect(screen.getByText(/line two/)).toBeInTheDocument();
		expect(screen.getByText(/line three/)).toBeInTheDocument();
	});

	it("renders an empty-url placeholder when no signedUrl is provided", () => {
		render(
			<FilePreview artifactId="a1" fileName="seq.fasta" signedUrl={null} />,
		);
		expect(screen.getByText(/no signed url available/i)).toBeInTheDocument();
	});

	it("passes protein selections from structure viewers", () => {
		const onProteinSelection = vi.fn();
		const FakeViewer = ({
			artifactId,
			candidateId,
			onProteinSelection: onSelection,
		}: {
			artifactId?: string | null;
			candidateId?: string | null;
			onProteinSelection?: (selection: {
				artifactId: string;
				candidateId: string | null;
				label: string;
				selector: Record<string, unknown>;
			}) => void;
		}) => (
			<button
				onClick={() =>
					onSelection?.({
						artifactId: artifactId ?? "",
						candidateId: candidateId ?? null,
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
			<FilePreview
				artifactId="artifact-1"
				candidateId="candidate-1"
				fileName="6m0j.cif"
				onProteinSelection={onProteinSelection}
				signedUrl="https://example.com/6m0j.cif"
				viewerComponent={FakeViewer}
			/>,
		);

		screen.getByRole("button", { name: "Select residue" }).click();

		expect(onProteinSelection).toHaveBeenCalledWith({
			artifactId: "artifact-1",
			candidateId: "candidate-1",
			label: "6M0J chain A residue 145",
			selector: {
				authAsymId: "A",
				residueRanges: [{ end: 145, start: 145 }],
			},
		});
	});
});
