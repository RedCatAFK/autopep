// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecipesDialog } from "./recipes-dialog";

const recipes = [
	{
		bodyMarkdown: "Always preserve source artifacts.",
		description: null,
		enabledByDefault: true,
		id: "r1",
		name: "3CL Protease Prep",
	},
];

describe("RecipesDialog", () => {
	it("renders recipe list and editor", async () => {
		render(
			<RecipesDialog
				isSaving={false}
				onArchive={() => {}}
				onClose={() => {}}
				onCreate={() => {}}
				onUpdate={() => {}}
				open
				recipes={recipes}
			/>,
		);
		expect(screen.getByText("3CL Protease Prep")).toBeInTheDocument();
		expect(
			screen.getByDisplayValue(/preserve source artifacts/i),
		).toBeInTheDocument();
	});

	it("creates a new recipe via the + New button", async () => {
		const user = userEvent.setup();
		const onCreate = vi.fn();
		render(
			<RecipesDialog
				isSaving={false}
				onArchive={() => {}}
				onClose={() => {}}
				onCreate={onCreate}
				onUpdate={() => {}}
				open
				recipes={recipes}
			/>,
		);
		await user.click(screen.getByRole("button", { name: /new recipe/i }));
		await user.type(screen.getByLabelText(/name/i), "New flow");
		await user.type(screen.getByLabelText(/instructions/i), "Do thing.");
		await user.click(screen.getByRole("button", { name: /create recipe/i }));
		expect(onCreate).toHaveBeenCalledWith(
			expect.objectContaining({ name: "New flow", bodyMarkdown: "Do thing." }),
		);
	});
});
