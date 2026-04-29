// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";

import { HoverTooltip } from "./hover-tooltip";

describe("HoverTooltip", () => {
	it("shows the label when the trigger is hovered", async () => {
		const user = userEvent.setup();
		render(
			<HoverTooltip label="Full workspace name">
				<button type="button">trigger</button>
			</HoverTooltip>,
		);

		await user.hover(screen.getByRole("button", { name: "trigger" }));
		expect(await screen.findByText("Full workspace name")).toBeInTheDocument();
	});
});
