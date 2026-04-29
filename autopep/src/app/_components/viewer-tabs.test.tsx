// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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
});
