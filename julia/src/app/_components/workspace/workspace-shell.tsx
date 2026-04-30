"use client";

import { LogOut, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";

import { authClient } from "@/server/better-auth/client";
import { api } from "@/trpc/react";
import { ChatPanel, type WorkspaceMessage } from "./chat-panel";
import type { WorkspaceContextReference } from "./context-pills";
import { FilePanel, type WorkspaceArtifact } from "./file-panel";
import { MolstarViewer } from "./molstar-viewer";

type WorkspaceUser = {
	name?: string | null;
	email?: string | null;
	image?: string | null;
};

type WorkspaceThread = {
	id: string;
	title?: string | null;
	displayTitle?: string | null;
	initial?: string | null;
};

type WorkspacePayload = {
	project?: {
		id: string;
		name?: string | null;
		description?: string | null;
	};
	thread?: {
		id: string;
		title?: string | null;
	} | null;
	threads?: WorkspaceThread[];
	messages?: WorkspaceMessage[];
	artifacts?: WorkspaceArtifact[];
	contextReferences?: WorkspaceContextReference[];
	activeRunId?: string | null;
};

const THREAD_COLORS = [
	"#f97316",
	"#22c55e",
	"#06b6d4",
	"#a855f7",
	"#ef4444",
	"#eab308",
	"#14b8a6",
	"#f43f5e",
	"#6366f1",
	"#84cc16",
];

export function WorkspaceShell({ user }: { user?: WorkspaceUser }) {
	const router = useRouter();
	const utils = api.useUtils();
	const latestWorkspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: 5000,
	});
	const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
		null,
	);
	const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
	const [activeRunId, setActiveRunId] = useState<string | null>(null);
	const [profileOpen, setProfileOpen] = useState(false);
	const [signOutError, setSignOutError] = useState<string | null>(null);
	const [isSigningOut, setIsSigningOut] = useState(false);
	const latestPayload = (latestWorkspace.data ?? {}) as WorkspacePayload;
	const baseProjectId = latestPayload.project?.id ?? "";
	const selectedWorkspace = api.workspace.getProjectState.useQuery(
		{
			projectId: baseProjectId,
			threadId: selectedThreadId ?? undefined,
		},
		{
			enabled: Boolean(baseProjectId && selectedThreadId),
			refetchInterval: 5000,
		},
	);
	const createThread = api.workspace.createThread.useMutation({
		onSuccess: (thread) => {
			setActiveRunId(null);
			setSelectedArtifactId(null);
			setSelectedThreadId(thread.id);
			void utils.workspace.getLatestWorkspace.invalidate();
			void utils.workspace.getProjectState.invalidate();
		},
	});
	const addContext = api.workspace.addContextReference.useMutation({
		onSuccess: () => {
			void utils.workspace.getLatestWorkspace.invalidate();
			void utils.workspace.getProjectState.invalidate();
		},
	});
	const removeContext = api.workspace.deleteContextReference.useMutation({
		onSuccess: () => {
			void utils.workspace.getLatestWorkspace.invalidate();
			void utils.workspace.getProjectState.invalidate();
		},
	});

	const payload = (
		selectedThreadId
			? (selectedWorkspace.data ?? latestWorkspace.data ?? {})
			: (latestWorkspace.data ?? {})
	) as WorkspacePayload;
	const projectId = payload.project?.id ?? "";
	const currentThreadId = payload.thread?.id ?? null;
	const threads = payload.threads ?? [];
	const artifacts = payload.artifacts ?? [];
	const contextReferences = payload.contextReferences ?? [];
	const selectedArtifact = useMemo(
		() =>
			artifacts.find((artifact) => artifact.id === selectedArtifactId) ??
			artifacts.find((artifact) =>
				/\.(cif|mmcif|pdb|bcif)$/i.test(artifact.filename),
			) ??
			null,
		[artifacts, selectedArtifactId],
	);
	const profileInitial = userInitial(user);

	const handleSignOut = async () => {
		setSignOutError(null);
		setIsSigningOut(true);
		try {
			const { error } = await authClient.signOut();
			if (error) {
				setSignOutError(error.message ?? "Unable to sign out.");
				return;
			}
			router.refresh();
		} finally {
			setIsSigningOut(false);
		}
	};

	const handleAddContext = (artifact: WorkspaceArtifact) => {
		if (!projectId) return;
		addContext.mutate({
			projectId,
			artifactId: artifact.id,
			label: artifact.filename,
			threadId: payload.thread?.id ?? undefined,
		});
	};

	return (
		<main className="workspace-root">
			<nav aria-label="Workspace navigation" className="left-rail">
				<div className="rail-brand">J</div>
				<button
					aria-label="New chat"
					className="rail-button"
					disabled={!projectId || createThread.isPending}
					onClick={() => {
						if (!projectId) return;
						createThread.mutate({ projectId });
					}}
					title="New chat"
					type="button"
				>
					<Plus aria-hidden="true" size={18} />
				</button>
				<div className="rail-thread-list">
					{threads.map((thread) => {
						const isActive = thread.id === currentThreadId;
						const label = thread.displayTitle ?? thread.title ?? "New chat";

						return (
							<button
								aria-label={`Open chat: ${label}`}
								aria-pressed={isActive}
								className={`rail-thread-block ${isActive ? "active" : ""}`}
								key={thread.id}
								onClick={() => {
									setSelectedThreadId(thread.id);
									setActiveRunId(null);
									setSelectedArtifactId(null);
								}}
								style={
									{
										"--thread-color": threadColor(thread.id),
									} as CSSProperties
								}
								title={label}
								type="button"
							>
								<span>{thread.initial ?? initialFromLabel(label)}</span>
							</button>
						);
					})}
				</div>
				<div className="rail-profile">
					<button
						aria-expanded={profileOpen}
						aria-label="Profile"
						className="rail-avatar"
						onClick={() => setProfileOpen((open) => !open)}
						title={user?.email ?? user?.name ?? "Profile"}
						type="button"
					>
						<span>{profileInitial}</span>
					</button>
					{profileOpen ? (
						<div className="profile-popover">
							<p className="profile-name">{user?.name ?? "Julia user"}</p>
							{user?.email ? (
								<p className="profile-email">{user.email}</p>
							) : null}
							<button
								className="profile-sign-out"
								disabled={isSigningOut}
								onClick={handleSignOut}
								type="button"
							>
								<LogOut aria-hidden="true" size={15} />
								<span>{isSigningOut ? "Signing out..." : "Sign out"}</span>
							</button>
							{signOutError ? (
								<p className="profile-error">{signOutError}</p>
							) : null}
						</div>
					) : null}
				</div>
			</nav>
			<div className="workspace-grid">
				{latestWorkspace.isLoading ||
				(selectedThreadId &&
					selectedWorkspace.isLoading &&
					!payload.project) ? (
					<div className="workspace-loading">Loading workspace...</div>
				) : latestWorkspace.error || selectedWorkspace.error ? (
					<div className="workspace-loading error" role="alert">
						{latestWorkspace.error?.message ?? selectedWorkspace.error?.message}
					</div>
				) : projectId ? (
					<>
						<ChatPanel
							activeRunId={activeRunId ?? payload.activeRunId ?? null}
							contextReferences={contextReferences}
							messages={payload.messages ?? []}
							onRemoveContext={(referenceId) =>
								removeContext.mutate({ referenceId, projectId })
							}
							onRunCreated={setActiveRunId}
							projectId={projectId}
							threadId={payload.thread?.id}
						/>
						<MolstarViewer artifact={selectedArtifact} />
						<FilePanel
							artifacts={artifacts}
							disabled={addContext.isPending}
							onAddContext={handleAddContext}
							onSelectArtifact={(artifact) =>
								setSelectedArtifactId(artifact.id)
							}
							selectedArtifactId={selectedArtifact?.id}
						/>
					</>
				) : (
					<div className="workspace-loading">
						No workspace is available for this account yet.
					</div>
				)}
			</div>
		</main>
	);
}

function threadColor(threadId: string): string {
	let hash = 0;
	for (let index = 0; index < threadId.length; index += 1) {
		hash = (hash * 31 + threadId.charCodeAt(index)) >>> 0;
	}
	return THREAD_COLORS[hash % THREAD_COLORS.length] ?? "#64748b";
}

function initialFromLabel(label: string): string {
	return label.trim().charAt(0).toUpperCase() || "N";
}

function userInitial(user?: WorkspaceUser): string {
	return initialFromLabel(user?.name ?? user?.email ?? "U");
}
