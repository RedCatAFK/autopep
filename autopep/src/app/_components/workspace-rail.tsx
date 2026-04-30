"use client";

import {
	BookOpen,
	DotsThreeVertical,
	Flask,
	Plus,
	SignOut,
} from "@phosphor-icons/react";
import {
	type FormEvent,
	type KeyboardEvent,
	useEffect,
	useRef,
	useState,
} from "react";

import { HoverTooltip } from "./hover-tooltip";
import { initial, WorkspaceAvatar } from "./workspace-avatar";

export type RailWorkspace = {
	description?: string | null;
	id: string;
	isDraft?: boolean;
	name: string;
};

export type RailAccount = {
	email?: string | null;
	name?: string | null;
};

type WorkspaceRailProps = {
	account?: RailAccount;
	activeWorkspaceId: string | null;
	onArchiveWorkspace: (workspaceId: string) => void;
	onCreateWorkspace: () => void;
	onOpenRecipes?: () => void;
	onRename?: (workspaceId: string, name: string) => void;
	onSelectWorkspace: (workspaceId: string) => void;
	onSignOut?: () => void;
	signingOut?: boolean;
	signOutError?: string | null;
	workspaces: RailWorkspace[];
};

export function WorkspaceRail({
	account,
	activeWorkspaceId,
	onArchiveWorkspace,
	onCreateWorkspace,
	onOpenRecipes,
	onRename,
	onSelectWorkspace,
	onSignOut,
	signingOut = false,
	signOutError,
	workspaces,
}: WorkspaceRailProps) {
	const [openMenuId, setOpenMenuId] = useState<string | null>(null);
	const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
	const [renamingId, setRenamingId] = useState<string | null>(null);

	useEffect(() => {
		if (!openMenuId && !isAccountMenuOpen) {
			return;
		}
		const handler = (event: MouseEvent) => {
			const target = event.target as HTMLElement | null;
			if (!target?.closest("[data-rail-menu]")) {
				setOpenMenuId(null);
			}
			if (!target?.closest("[data-account-menu]")) {
				setIsAccountMenuOpen(false);
			}
		};
		window.addEventListener("mousedown", handler);
		return () => window.removeEventListener("mousedown", handler);
	}, [isAccountMenuOpen, openMenuId]);

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
						if (workspace.isDraft) {
							return (
								<div className="group relative shrink-0" key={workspace.id}>
									<HoverTooltip label="New workspace (draft)">
										<button
											aria-current={active ? "true" : undefined}
											aria-label="Open draft workspace"
											className={`flex size-10 items-center justify-center rounded-md border border-[#d7d4c9] border-dashed text-[#7a817a] transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px ${active ? "ring-2 ring-[#cbd736] ring-offset-1 ring-offset-[#fbfaf6]" : ""}`}
											onClick={() => onSelectWorkspace(workspace.id)}
											type="button"
										>
											<span
												aria-hidden="true"
												className="font-semibold text-[15px]"
											>
												…
											</span>
										</button>
									</HoverTooltip>
								</div>
							);
						}
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
											aria-expanded={isMenuOpen}
											aria-haspopup="menu"
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
											<div
												className="absolute top-full left-0 z-30 mt-1 min-w-[120px] rounded-md border border-[#e5e2d9] bg-[#fffef9] py-1 shadow-lg"
												role="menu"
											>
												<div>
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
												</div>
												<div>
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
												</div>
											</div>
										) : null}
									</div>
								) : null}
							</div>
						);
					})
				)}
			</nav>
			<div className="ml-auto flex shrink-0 items-center gap-2 lg:mt-auto lg:ml-0 lg:flex-col">
				{onOpenRecipes ? (
					<button
						aria-label="Open recipes"
						className="flex size-10 shrink-0 items-center justify-center rounded-md text-[#5a6360] transition-colors duration-200 hover:bg-[#f0efe8] hover:text-[#26332e] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
						onClick={onOpenRecipes}
						type="button"
					>
						<BookOpen aria-hidden="true" size={18} />
					</button>
				) : null}
				{account && onSignOut ? (
					<AccountMenu
						account={account}
						isOpen={isAccountMenuOpen}
						onOpenChange={setIsAccountMenuOpen}
						onSignOut={onSignOut}
						signingOut={signingOut}
						signOutError={signOutError}
					/>
				) : null}
			</div>
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

function AccountMenu({
	account,
	isOpen,
	onOpenChange,
	onSignOut,
	signingOut,
	signOutError,
}: {
	account: RailAccount;
	isOpen: boolean;
	onOpenChange: (isOpen: boolean) => void;
	onSignOut: () => void;
	signingOut: boolean;
	signOutError?: string | null;
}) {
	const label = account.email ?? account.name ?? "Account";
	const displayName =
		account.name?.trim() || account.email || "Autopep account";
	const displayEmail =
		account.email && account.email !== displayName ? account.email : null;

	return (
		<div className="relative" data-account-menu>
			<HoverTooltip label={label}>
				<button
					aria-expanded={isOpen}
					aria-haspopup="menu"
					aria-label={`Open account menu for ${label}`}
					className="flex size-10 shrink-0 items-center justify-center rounded-md border border-[#ddd9ce] bg-[#fffef9] text-[#1d342e] transition-colors duration-200 hover:border-[#cbd736] hover:bg-[#f2f1e9] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
					onClick={() => onOpenChange(!isOpen)}
					type="button"
				>
					<span
						aria-hidden="true"
						className="flex size-7 items-center justify-center rounded-[6px] bg-[#17211e] font-semibold text-[#eef1e6] text-[13px]"
					>
						{initial(displayName)}
					</span>
				</button>
			</HoverTooltip>
			{isOpen ? (
				<div
					className="absolute top-full right-0 z-30 mt-2 min-w-[220px] rounded-md border border-[#e5e2d9] bg-[#fffef9] p-2 shadow-[0_18px_50px_-26px_rgba(25,39,33,0.75)] lg:top-auto lg:right-auto lg:bottom-0 lg:left-full lg:mt-0 lg:ml-2"
					role="menu"
				>
					<div className="border-[#ebe7dc] border-b px-2 pt-1 pb-2">
						<p className="font-semibold text-[#17211e] text-sm">
							{displayName}
						</p>
						{displayEmail ? (
							<p className="mt-0.5 text-[#6b746d] text-xs">{displayEmail}</p>
						) : null}
					</div>
					<button
						className="mt-1 flex w-full items-center gap-2 rounded-[6px] px-2 py-2 text-left font-medium text-[#33413c] text-sm transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-60"
						disabled={signingOut}
						onClick={onSignOut}
						role="menuitem"
						type="button"
					>
						<SignOut aria-hidden="true" size={16} />
						{signingOut ? "Signing out..." : "Sign out"}
					</button>
					{signOutError ? (
						<p className="mt-2 rounded-[6px] border border-[#d88b7a]/30 bg-[#fff1ee] px-2 py-1.5 text-[#8e3c30] text-xs">
							{signOutError}
						</p>
					) : null}
				</div>
			) : null}
		</div>
	);
}
