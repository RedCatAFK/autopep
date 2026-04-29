"use client";

import { Archive, Flask, Plus } from "@phosphor-icons/react";

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
	onSelectWorkspace: (workspaceId: string) => void;
	workspaces: RailWorkspace[];
};

export function WorkspaceRail({
	activeWorkspaceId,
	onArchiveWorkspace,
	onCreateWorkspace,
	onSelectWorkspace,
	workspaces,
}: WorkspaceRailProps) {
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
						return (
							<div className="group relative shrink-0" key={workspace.id}>
								<button
									aria-label={`Open ${workspace.name}`}
									className="flex size-10 items-center justify-center rounded-md transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
									onClick={() => onSelectWorkspace(workspace.id)}
									title={workspace.name}
									type="button"
								>
									<WorkspaceAvatar
										active={active}
										id={workspace.id}
										name={workspace.name}
									/>
								</button>
								{active ? (
									<button
										aria-label={`Archive ${workspace.name}`}
										className="absolute -right-1 -bottom-1 hidden size-5 items-center justify-center rounded bg-[#fffef9] text-[#69716b] shadow-[0_8px_24px_-16px_rgba(25,39,33,0.65)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 group-focus-within:flex group-hover:flex"
										onClick={() => onArchiveWorkspace(workspace.id)}
										type="button"
									>
										<Archive aria-hidden="true" size={12} />
									</button>
								) : null}
							</div>
						);
					})
				)}
			</nav>
		</aside>
	);
}
