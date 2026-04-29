// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceEventCard } from "./trace-event-card";

describe("TraceEventCard", () => {
	it("collapses raw details until requested", () => {
		render(
			<TraceEventCard
				event={{
					displayJson: { artifact: "candidate-1.pdb" },
					id: "event-1",
					rawJson: { storageKey: "runs/one/candidate-1.pdb" },
					sequence: 7,
					summary: "Saved folded candidate artifact",
					title: "Artifact Created",
					type: "artifact_created",
				}}
			/>,
		);

		expect(screen.getByText("#07")).toBeInTheDocument();
		expect(screen.queryByText("storageKey")).not.toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /Artifact Created/u }));

		expect(
			screen.getByText(/runs\/one\/candidate-1\.pdb/u),
		).toBeInTheDocument();
	});
});
