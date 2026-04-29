"use client";

import {
	Archive,
	FloppyDisk,
	Plus,
	ToggleLeft,
	ToggleRight,
	X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

export type RecipeRow = {
	bodyMarkdown: string;
	description: string | null;
	enabledByDefault: boolean;
	id: string;
	name: string;
};

export type RecipeInput = {
	bodyMarkdown: string;
	description: string | null;
	enabledByDefault: boolean;
	name: string;
};

type RecipesDialogProps = {
	isSaving: boolean;
	onArchive: (recipeId: string) => void;
	onClose: () => void;
	onCreate: (input: RecipeInput) => void;
	onUpdate: (input: RecipeInput & { recipeId: string }) => void;
	open: boolean;
	recipes: RecipeRow[];
};

const emptyDraft: RecipeInput = {
	bodyMarkdown: "",
	description: null,
	enabledByDefault: true,
	name: "",
};

export function RecipesDialog({
	isSaving,
	onArchive,
	onClose,
	onCreate,
	onUpdate,
	open,
	recipes,
}: RecipesDialogProps) {
	const [selectedId, setSelectedId] = useState<string | null>(
		recipes[0]?.id ?? null,
	);
	const [isCreating, setIsCreating] = useState(false);
	const [filter, setFilter] = useState("");
	const [draft, setDraft] = useState<RecipeInput>(emptyDraft);

	const filteredRecipes = useMemo(
		() =>
			recipes.filter((recipe) =>
				recipe.name.toLowerCase().includes(filter.trim().toLowerCase()),
			),
		[recipes, filter],
	);

	const selectedRecipe = useMemo(
		() => recipes.find((recipe) => recipe.id === selectedId) ?? null,
		[recipes, selectedId],
	);

	useEffect(() => {
		if (isCreating) {
			setDraft(emptyDraft);
			return;
		}
		if (selectedRecipe) {
			setDraft({
				bodyMarkdown: selectedRecipe.bodyMarkdown,
				description: selectedRecipe.description,
				enabledByDefault: selectedRecipe.enabledByDefault,
				name: selectedRecipe.name,
			});
		}
	}, [selectedRecipe, isCreating]);

	useEffect(() => {
		if (!open) return;
		const handler = (event: KeyboardEvent) => {
			if (event.key === "Escape") onClose();
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [open, onClose]);

	if (!open) return null;

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (
			isSaving ||
			draft.name.trim().length === 0 ||
			draft.bodyMarkdown.trim().length === 0
		) {
			return;
		}
		if (isCreating || !selectedRecipe) {
			onCreate(draft);
			setIsCreating(false);
			return;
		}
		onUpdate({ ...draft, recipeId: selectedRecipe.id });
	};

	const startNew = () => {
		setIsCreating(true);
		setSelectedId(null);
		setDraft(emptyDraft);
	};

	return (
		<div
			aria-labelledby="recipes-dialog-title"
			aria-modal="true"
			className="fixed inset-0 z-50 flex items-center justify-center bg-[#17211e]/40 p-6"
			role="dialog"
		>
			<div className="grid h-[620px] w-[860px] max-w-full grid-cols-[240px_1fr] overflow-hidden rounded-lg bg-[#fbfaf6] shadow-2xl">
				<aside className="flex min-h-0 flex-col border-[#e5e2d9] border-r">
					<div className="flex items-center gap-2 border-[#e5e2d9] border-b p-3">
						<h2
							className="font-semibold text-[#17211e] text-sm"
							id="recipes-dialog-title"
						>
							Recipes
						</h2>
						<button
							aria-label="Close"
							className="ml-auto rounded p-1 text-[#5a6360] hover:bg-[#f0efe8]"
							onClick={onClose}
							type="button"
						>
							<X aria-hidden="true" size={14} />
						</button>
					</div>
					<div className="border-[#e5e2d9] border-b p-3">
						<input
							className="mb-2 w-full rounded-md border border-[#ddd9cf] bg-[#fffef9] px-2 py-1.5 text-xs outline-none focus:border-[#cbd736]"
							onChange={(event) => setFilter(event.target.value)}
							placeholder="Search recipes…"
							type="search"
							value={filter}
						/>
						<button
							className="flex w-full items-center justify-center gap-1.5 rounded-md bg-[#dfe94c] px-2 py-1.5 font-medium text-[#1d342e] text-xs hover:bg-[#d4e337]"
							onClick={startNew}
							type="button"
						>
							<Plus aria-hidden="true" size={12} weight="bold" />
							New recipe
						</button>
					</div>
					<ul className="min-h-0 flex-1 overflow-y-auto p-2">
						{filteredRecipes.length === 0 ? (
							<li className="px-2 py-4 text-[#7a817a] text-sm">
								No recipes match.
							</li>
						) : (
							filteredRecipes.map((recipe) => {
								const active = recipe.id === selectedId && !isCreating;
								return (
									<li key={recipe.id}>
										<button
											className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm ${
												active
													? "bg-[#dfe94c] text-[#1d342e]"
													: "text-[#26332e] hover:bg-[#f0efe8]"
											}`}
											onClick={() => {
												setIsCreating(false);
												setSelectedId(recipe.id);
											}}
											type="button"
										>
											<span className="truncate">{recipe.name}</span>
											{recipe.enabledByDefault ? (
												<span
													aria-hidden="true"
													className="size-1.5 shrink-0 rounded-full bg-[#2d8c5a]"
												/>
											) : null}
										</button>
									</li>
								);
							})
						)}
					</ul>
				</aside>
				<form className="flex min-h-0 flex-col p-4" onSubmit={submit}>
					{isCreating || selectedRecipe ? (
						<>
							<label
								className="block font-medium text-[#49524d] text-xs"
								htmlFor="recipe-name"
							>
								Name
							</label>
							<input
								className="mt-1 mb-3 rounded-md border border-[#ddd9cf] bg-[#fffef9] px-2 py-1.5 text-sm outline-none focus:border-[#cbd736]"
								id="recipe-name"
								onChange={(event) =>
									setDraft((prev) => ({ ...prev, name: event.target.value }))
								}
								value={draft.name}
							/>
							<label
								className="block font-medium text-[#49524d] text-xs"
								htmlFor="recipe-body"
							>
								Instructions
							</label>
							<textarea
								className="mt-1 mb-3 min-h-0 flex-1 resize-none rounded-md border border-[#ddd9cf] bg-[#fffef9] px-2 py-1.5 text-sm leading-6 outline-none focus:border-[#cbd736]"
								id="recipe-body"
								onChange={(event) =>
									setDraft((prev) => ({
										...prev,
										bodyMarkdown: event.target.value,
									}))
								}
								value={draft.bodyMarkdown}
							/>
							<button
								aria-pressed={draft.enabledByDefault}
								className="mb-3 flex items-center gap-2 self-start text-[#40504a] text-sm"
								onClick={() =>
									setDraft((prev) => ({
										...prev,
										enabledByDefault: !prev.enabledByDefault,
									}))
								}
								type="button"
							>
								{draft.enabledByDefault ? (
									<ToggleRight
										aria-hidden="true"
										className="text-[#2d8c5a]"
										size={22}
									/>
								) : (
									<ToggleLeft aria-hidden="true" size={22} />
								)}
								Enabled by default
							</button>
							<div className="flex items-center gap-2">
								<button
									className="inline-flex items-center gap-1.5 rounded-md bg-[#dfe94c] px-3 py-1.5 font-medium text-[#1d342e] text-sm hover:bg-[#d4e337] disabled:opacity-50"
									disabled={
										isSaving || !draft.name.trim() || !draft.bodyMarkdown.trim()
									}
									type="submit"
								>
									<FloppyDisk aria-hidden="true" size={14} />
									{isCreating || !selectedRecipe
										? "Create recipe"
										: "Save recipe"}
								</button>
								{selectedRecipe && !isCreating ? (
									<button
										aria-label={`Archive ${selectedRecipe.name}`}
										className="inline-flex items-center gap-1.5 rounded-md border border-[#d7d4c9] px-3 py-1.5 text-[#5a6360] text-sm hover:border-[#cbd736]"
										onClick={() => onArchive(selectedRecipe.id)}
										type="button"
									>
										<Archive aria-hidden="true" size={14} />
										Archive
									</button>
								) : null}
							</div>
						</>
					) : (
						<p className="text-[#7a817a] text-sm">
							Select a recipe on the left, or create a new one. Recipes are
							reusable instruction sets the agent applies to runs.
						</p>
					)}
				</form>
			</div>
		</div>
	);
}
