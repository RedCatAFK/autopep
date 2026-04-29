"use client";

import {
	BookOpen,
	DotsThreeVertical,
	Flask,
	Plus,
} from "@phosphor-icons/react";
import {
	type FormEvent,
	type KeyboardEvent,
	useEffect,
	useRef,
	useState,
} from "react";

import { HoverTooltip } from "./hover-tooltip";
import { WorkspaceAvatar } from "./workspace-avatar";

export type RailWorkspace = {
	description?: string | null;
	id: string;
	name: string;
};

type WorkspaceRailProps = {
	activeWorkspaceId: string | null;
	onArchiveWorkspace: (workspaceId: string) => void;
	onCreateWorkspace: () => void;
	onOpenRecipes?: () => void;
	onRename?: (workspaceId: string, name: string) => void;
	onSelectWorkspace: (workspaceId: string) => void;
	workspaces: RailWorkspace[];
};

export function WorkspaceRail({
	activeWorkspaceId,
	onArchiveWorkspace,
	onCreateWorkspace,
	onOpenRecipes,
	onRename,
	onSelectWorkspace,
	workspaces,
}: WorkspaceRailProps) {
	const [openMenuId, setOpenMenuId] = useState<string | null>(null);
	const [renamingId, setRenamingId] = useState<string | null>(null);

	useEffect(() => {
		if (!openMenuId) {
			return;
		}
		const handler = (event: MouseEvent) => {
			const target = event.target as HTMLElement | null;
			if (!target?.closest("[data-rail-menu]")) {
				setOpenMenuId(null);
			}
		};
		window.addEventListener("mousedown", handler);
		return () => window.removeEventListener("mousedown", handler);
	}, [openMenuId]);

	return (
		<aside className="flex items-center gap-2 overflow-x-auto border-[#e5e2d9] border-b bg-[#fbfaf6] px-3 py-3 lg:flex-col lg:overflow-x-visible lg:border-r lg:border-b-0 lg:px-2 lg:py-4">
			<button
				aria-label="Create workspace"
				className="flex size-10 shrink-0 items-center justify-center rounded-md bg-[#dfe94c] text-[#1d342e] transition-colors duration-200 hover:bg-[#d4e337] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#a5b51f] focus-visible:outline-offset-2 active:translate-y-px"
				onClick={onCreateWorkspace}
				type="button"
			>
				<Plus aria-hidden="true" size={20} weight="bold" />
			</button>
			<nav
				aria-label="Workspaces"
				className="flex min-w-0 items-center gap-2 lg:mt-4 lg:flex-col"
			>
				{workspaces.length === 0 ? (
					<div className="flex size-10 shrink-0 items-center justify-center rounded-md border border-[#d7d4c9] border-dashed text-[#7a817a]">
						<Flask aria-hidden="true" size={19} />
					</div>
				) : (
					workspaces.map((workspace) => {
						const active = workspace.id === activeWorkspaceId;
						const isRenaming = workspace.id === renamingId;
						const isMenuOpen = workspace.id === openMenuId;
						return (
							<div className="group relative shrink-0" key={workspace.id}>
								{isRenaming ? (
									<RenameInput
										initialName={workspace.name}
										onCancel={() => setRenamingId(null)}
										onSubmit={(name) => {
											setRenamingId(null);
											onRename?.(workspace.id, name);
										}}
									/>
								) : (
									<HoverTooltip label={workspace.name}>
										<button
											aria-label={`Open ${workspace.name}`}
											className="flex size-10 items-center justify-center rounded-md transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
											onClick={() => onSelectWorkspace(workspace.id)}
											type="button"
										>
											<WorkspaceAvatar
												active={active}
												id={workspace.id}
												name={workspace.name}
											/>
										</button>
									</HoverTooltip>
								)}
								{!isRenaming ? (
									<div className="absolute -top-1 -right-1" data-rail-menu>
										<button
											aria-haspopup="menu"
											aria-expanded={isMenuOpen}
											aria-label={`More options for ${workspace.name}`}
											className="hidden size-5 items-center justify-center rounded bg-[#fffef9] text-[#69716b] shadow-[0_8px_24px_-16px_rgba(25,39,33,0.65)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 group-focus-within:flex group-hover:flex"
											onClick={() =>
												setOpenMenuId(isMenuOpen ? null : workspace.id)
											}
											type="button"
										>
											<DotsThreeVertical aria-hidden="true" size={12} />
										</button>
										{isMenuOpen ? (
											<ul
												className="absolute top-full left-0 z-30 mt-1 min-w-[120px] rounded-md border border-[#e5e2d9] bg-[#fffef9] py-1 shadow-lg"
												role="menu"
											>
												<li>
													<button
														className="block w-full px-3 py-1.5 text-left text-[#26332e] text-sm hover:bg-[#f0efe8]"
														onClick={() => {
															setOpenMenuId(null);
															setRenamingId(workspace.id);
														}}
														role="menuitem"
														type="button"
													>
														Rename
													</button>
												</li>
												<li>
													<button
														className="block w-full px-3 py-1.5 text-left text-[#26332e] text-sm hover:bg-[#f0efe8]"
														onClick={() => {
															setOpenMenuId(null);
															onArchiveWorkspace(workspace.id);
														}}
														role="menuitem"
														type="button"
													>
														Archive
													</button>
												</li>
											</ul>
										) : null}
									</div>
								) : null}
							</div>
						);
					})
				)}
			</nav>
			{onOpenRecipes ? (
				<button
					aria-label="Open recipes"
					className="mt-auto flex size-10 shrink-0 items-center justify-center rounded-md text-[#5a6360] transition-colors duration-200 hover:bg-[#f0efe8] hover:text-[#26332e] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
					onClick={onOpenRecipes}
					type="button"
				>
					<BookOpen aria-hidden="true" size={18} />
				</button>
			) : null}
		</aside>
	);
}

function RenameInput({
	initialName,
	onCancel,
	onSubmit,
}: {
	initialName: string;
	onCancel: () => void;
	onSubmit: (name: string) => void;
}) {
	const [value, setValue] = useState(initialName);
	const ref = useRef<HTMLInputElement | null>(null);

	useEffect(() => {
		ref.current?.focus();
		ref.current?.select();
	}, []);

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		const trimmed = value.trim();
		if (!trimmed) {
			onCancel();
			return;
		}
		onSubmit(trimmed);
	};

	const handleKey = (event: KeyboardEvent<HTMLInputElement>) => {
		if (event.key === "Escape") {
			event.preventDefault();
			onCancel();
		}
	};

	return (
		<form className="flex size-10 items-center" onSubmit={submit}>
			<input
				aria-label="Rename workspace"
				className="size-10 rounded-md border border-[#cbd736] bg-[#fffef9] px-2 text-center text-[#27322f] text-xs outline-none"
				defaultValue={initialName}
				onBlur={onCancel}
				onChange={(event) => setValue(event.target.value)}
				onKeyDown={handleKey}
				ref={ref}
			/>
		</form>
	);
}
