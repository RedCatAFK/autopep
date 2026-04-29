// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilesPanel } from "./files-panel";

describe("FilesPanel", () => {
	it("calls onOpenFile when a file row is clicked", async () => {
		const user = userEvent.setup();
		const onOpenFile = vi.fn();
		render(
			<FilesPanel
				activeArtifactId={null}
				artifacts={[
					{
						id: "a1",
						fileName: "ref.pdb",
						kind: "attachment",
						candidateId: null,
						runId: null,
						signedUrl: "https://example.com/ref.pdb",
						byteSize: 2048,
					},
				]}
				candidates={[]}
				onOpenFile={onOpenFile}
				runs={[]}
			/>,
		);
		await user.click(screen.getByText("ref.pdb"));
		expect(onOpenFile).toHaveBeenCalledWith(
			expect.objectContaining({ id: "a1", fileName: "ref.pdb" }),
		);
	});

	it("filters files by the search input", async () => {
		const user = userEvent.setup();
		render(
			<FilesPanel
				activeArtifactId={null}
				artifacts={[
					{
						id: "a1",
						fileName: "alpha.pdb",
						kind: "attachment",
						candidateId: null,
						runId: null,
						signedUrl: null,
						byteSize: 0,
					},
					{
						id: "a2",
						fileName: "beta.pdb",
						kind: "attachment",
						candidateId: null,
						runId: null,
						signedUrl: null,
						byteSize: 0,
					},
				]}
				candidates={[]}
				onOpenFile={() => {}}
				runs={[]}
			/>,
		);
		await user.type(screen.getByPlaceholderText(/filter files/i), "alpha");
		expect(screen.getByText("alpha.pdb")).toBeInTheDocument();
		expect(screen.queryByText("beta.pdb")).not.toBeInTheDocument();
	});
});
