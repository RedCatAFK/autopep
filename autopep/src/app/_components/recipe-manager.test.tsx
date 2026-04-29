// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecipeManager } from "./recipe-manager";

describe("RecipeManager", () => {
	it("creates a new recipe from the form", () => {
		const onCreate = vi.fn();
		render(
			<RecipeManager
				onArchive={vi.fn()}
				onCreate={onCreate}
				onUpdate={vi.fn()}
				recipes={[]}
			/>,
		);

		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "Literature-first generation" },
		});
		fireEvent.change(screen.getByLabelText("Instructions"), {
			target: { value: "Search PDB and bioRxiv before generation." },
		});
		fireEvent.click(screen.getByText("Create recipe"));

		expect(onCreate).toHaveBeenCalledWith(
			expect.objectContaining({
				bodyMarkdown: "Search PDB and bioRxiv before generation.",
				enabledByDefault: true,
				name: "Literature-first generation",
			}),
		);
	});

	it("edits and archives an existing recipe", () => {
		const onArchive = vi.fn();
		const onUpdate = vi.fn();
		render(
			<RecipeManager
				onArchive={onArchive}
				onCreate={vi.fn()}
				onUpdate={onUpdate}
				recipes={[
					{
						bodyMarkdown: "Keep RCSB artifacts.",
						description: null,
						enabledByDefault: true,
						id: "recipe-1",
						name: "RCSB prep",
					},
				]}
			/>,
		);

		fireEvent.change(screen.getByLabelText("Instructions"), {
			target: { value: "Keep RCSB and scoring artifacts." },
		});
		fireEvent.click(screen.getByText("Save recipe"));
		fireEvent.click(screen.getByLabelText("Archive RCSB prep"));

		expect(onUpdate).toHaveBeenCalledWith(
			expect.objectContaining({
				bodyMarkdown: "Keep RCSB and scoring artifacts.",
				recipeId: "recipe-1",
			}),
		);
		expect(onArchive).toHaveBeenCalledWith("recipe-1");
	});

	it("disables recipe writes when no workspace is active", () => {
		const onCreate = vi.fn();
		render(
			<RecipeManager
				isDisabled
				onArchive={vi.fn()}
				onCreate={onCreate}
				onUpdate={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(screen.getByLabelText("Create recipe")).toBeDisabled();
		expect(screen.getByLabelText("Name")).toBeDisabled();
		expect(screen.getByText("Create recipe")).toBeDisabled();

		const form = screen.getByText("Create recipe").closest("form");
		if (!form) {
			throw new Error("Recipe form was not rendered.");
		}
		fireEvent.submit(form);
		expect(onCreate).not.toHaveBeenCalled();
	});
});
