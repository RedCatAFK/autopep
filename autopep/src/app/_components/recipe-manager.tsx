"use client";

import {
	Archive,
	FloppyDisk,
	Plus,
	ToggleLeft,
	ToggleRight,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

export type Recipe = {
	bodyMarkdown: string;
	description: string | null;
	enabledByDefault: boolean;
	id: string;
	name: string;
};

type RecipeManagerProps = {
	isDisabled?: boolean;
	isSaving?: boolean;
	onArchive: (recipeId: string) => void;
	onCreate: (input: RecipeInput) => void;
	onUpdate: (input: RecipeInput & { recipeId: string }) => void;
	recipes: Recipe[];
};

export type RecipeInput = {
	bodyMarkdown: string;
	description: string | null;
	enabledByDefault: boolean;
	name: string;
};

export function RecipeManager({
	isDisabled = false,
	isSaving = false,
	onArchive,
	onCreate,
	onUpdate,
	recipes,
}: RecipeManagerProps) {
	const [activeRecipeId, setActiveRecipeId] = useState<string | null>(
		recipes[0]?.id ?? null,
	);
	const [isCreating, setIsCreating] = useState(false);
	const activeRecipe = useMemo(
		() => recipes.find((recipe) => recipe.id === activeRecipeId) ?? null,
		[activeRecipeId, recipes],
	);
	const [draft, setDraft] = useState<RecipeInput>(() =>
		activeRecipe
			? toDraft(activeRecipe)
			: {
					bodyMarkdown:
						"When generating a protein, first research comparable structures and preserve source artifacts.",
					description: null,
					enabledByDefault: true,
					name: "3CL Protease Prep",
				},
	);

	useEffect(() => {
		if (isCreating || activeRecipe) {
			return;
		}

		const nextRecipe = recipes[0];
		if (!nextRecipe) {
			setActiveRecipeId(null);
			return;
		}

		setActiveRecipeId(nextRecipe.id);
		setDraft(toDraft(nextRecipe));
	}, [activeRecipe, isCreating, recipes]);

	const selectRecipe = (recipe: Recipe) => {
		setIsCreating(false);
		setActiveRecipeId(recipe.id);
		setDraft(toDraft(recipe));
	};

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		if (
			isDisabled ||
			isSaving ||
			draft.name.trim().length === 0 ||
			draft.bodyMarkdown.trim().length === 0
		) {
			return;
		}

		if (activeRecipe) {
			onUpdate({ ...draft, recipeId: activeRecipe.id });
			return;
		}

		onCreate(draft);
		setIsCreating(false);
	};

	return (
		<section className="px-4 py-4">
			<button
				aria-label="Create recipe"
				className="inline-flex size-7 items-center justify-center rounded-md text-[#40504a] transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45"
				disabled={isDisabled}
				onClick={() => {
					setIsCreating(true);
					setActiveRecipeId(null);
					setDraft({
						bodyMarkdown: "",
						description: null,
						enabledByDefault: true,
						name: "",
					});
				}}
				type="button"
			>
				<Plus aria-hidden="true" size={18} />
			</button>

			<div className="mt-4 flex flex-wrap gap-1.5">
				{recipes.length === 0 ? (
					<p className="text-[#69716b] text-sm leading-6">
						Add a reusable instruction set for this workspace.
					</p>
				) : (
					recipes.map((recipe) => (
						<button
							className={`rounded-md px-2 py-1 text-xs transition-colors duration-200 active:translate-y-px ${
								activeRecipe?.id === recipe.id
									? "bg-[#dfe94c] text-[#20342f]"
									: "bg-[#f0efe8] text-[#52605a] hover:bg-[#e8e6dd]"
							} focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50`}
							disabled={isDisabled}
							key={recipe.id}
							onClick={() => selectRecipe(recipe)}
							type="button"
						>
							{recipe.name}
						</button>
					))
				)}
			</div>

			<form className="mt-4 space-y-3" onSubmit={submit}>
				<div className="grid gap-2">
					<label
						className="font-medium text-[#49524d] text-xs"
						htmlFor="recipe-name"
					>
						Name
					</label>
					<input
						autoComplete="off"
						className="rounded-md border border-[#ddd9cf] bg-[#fffef9] px-3 py-2 text-sm outline-none transition-colors duration-200 focus:border-[#cbd736] focus-visible:ring-2 focus-visible:ring-[#dfe94c]/50 disabled:cursor-not-allowed disabled:bg-[#f0efe8] disabled:text-[#747b74]"
						disabled={isDisabled}
						id="recipe-name"
						name="recipe-name"
						onChange={(event) =>
							setDraft((value) => ({ ...value, name: event.target.value }))
						}
						value={draft.name}
					/>
				</div>
				<div className="grid gap-2">
					<label
						className="font-medium text-[#49524d] text-xs"
						htmlFor="recipe-body"
					>
						Instructions
					</label>
					<textarea
						autoComplete="off"
						className="min-h-28 resize-none rounded-md border border-[#ddd9cf] bg-[#fffef9] px-3 py-2 text-sm leading-6 outline-none transition-colors duration-200 focus:border-[#cbd736] focus-visible:ring-2 focus-visible:ring-[#dfe94c]/50 disabled:cursor-not-allowed disabled:bg-[#f0efe8] disabled:text-[#747b74]"
						disabled={isDisabled}
						id="recipe-body"
						name="recipe-body"
						onChange={(event) =>
							setDraft((value) => ({
								...value,
								bodyMarkdown: event.target.value,
							}))
						}
						value={draft.bodyMarkdown}
					/>
				</div>
				<button
					aria-pressed={draft.enabledByDefault}
					className="flex items-center gap-2 rounded-md text-[#40504a] text-sm transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
					disabled={isDisabled}
					onClick={() =>
						setDraft((value) => ({
							...value,
							enabledByDefault: !value.enabledByDefault,
						}))
					}
					type="button"
				>
					{draft.enabledByDefault ? (
						<ToggleRight
							aria-hidden="true"
							className="text-[#2d8c5a]"
							size={24}
						/>
					) : (
						<ToggleLeft aria-hidden="true" size={24} />
					)}
					Enabled by default
				</button>
				<div className="flex items-center justify-between gap-2">
					<button
						className="inline-flex items-center gap-2 rounded-md bg-[#dfe94c] px-3 py-2 font-medium text-[#1d342e] text-sm transition-colors duration-200 hover:bg-[#d4e337] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#a5b51f] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
						disabled={
							isDisabled ||
							isSaving ||
							!draft.name.trim() ||
							!draft.bodyMarkdown.trim()
						}
						type="submit"
					>
						<FloppyDisk aria-hidden="true" size={16} />
						{activeRecipe ? "Save recipe" : "Create recipe"}
					</button>
					{activeRecipe ? (
						<button
							aria-label={`Archive ${activeRecipe.name}`}
							className="inline-flex items-center gap-2 rounded-md border border-[#d7d4c9] bg-[#fffef9] px-3 py-2 text-[#5f6963] text-sm transition-colors duration-200 hover:border-[#cbd736] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
							disabled={isDisabled}
							onClick={() => onArchive(activeRecipe.id)}
							type="button"
						>
							<Archive aria-hidden="true" size={16} />
							Archive
						</button>
					) : null}
				</div>
			</form>
		</section>
	);
}

function toDraft(recipe: Recipe): RecipeInput {
	return {
		bodyMarkdown: recipe.bodyMarkdown,
		description: recipe.description,
		enabledByDefault: recipe.enabledByDefault,
		name: recipe.name,
	};
}
