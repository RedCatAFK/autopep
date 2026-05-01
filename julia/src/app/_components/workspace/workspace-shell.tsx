"use client";

import { LogOut, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import { authClient } from "@/server/better-auth/client";
import { api } from "@/trpc/react";
import { ChatPanel, type WorkspaceMessage } from "./chat-panel";
import type { WorkspaceContextReference } from "./context-pills";
import { FilePanel, type WorkspaceArtifact } from "./file-panel";
import { MolstarViewer } from "./molstar-viewer";
import type { RunEventSource } from "./use-run-events";

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
};


const LAYOUT_STORAGE_KEY = "julia.layout.v1";
const CHAT_MIN = 280;
const CHAT_MAX = 640;
const FILES_MIN = 240;
const FILES_MAX = 520;

function clamp(value: number, min: number, max: number): number {
	return Math.min(max, Math.max(min, value));
}

export function WorkspaceShell({ user }: { user?: WorkspaceUser }) {
	const router = useRouter();
	const utils = api.useUtils();
	const [chatWidth, setChatWidth] = useState(360);
	const [filesWidth, setFilesWidth] = useState(300);

	useEffect(() => {
		try {
			const stored = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
			if (!stored) return;
			const parsed = JSON.parse(stored) as {
				chat?: number;
				files?: number;
			};
			if (typeof parsed.chat === "number") {
				setChatWidth(clamp(parsed.chat, CHAT_MIN, CHAT_MAX));
			}
			if (typeof parsed.files === "number") {
				setFilesWidth(clamp(parsed.files, FILES_MIN, FILES_MAX));
			}
		} catch {
			// ignore corrupt storage
		}
	}, []);

	useEffect(() => {
		try {
			window.localStorage.setItem(
				LAYOUT_STORAGE_KEY,
				JSON.stringify({ chat: chatWidth, files: filesWidth }),
			);
		} catch {
			// storage may be unavailable (private mode); not fatal
		}
	}, [chatWidth, filesWidth]);

	const handleResize = (
		event: ReactPointerEvent<HTMLDivElement>,
		side: "left" | "right",
	) => {
		event.preventDefault();
		const handle = event.currentTarget;
		const startX = event.clientX;
		const startWidth = side === "left" ? chatWidth : filesWidth;
		const min = side === "left" ? CHAT_MIN : FILES_MIN;
		const max = side === "left" ? CHAT_MAX : FILES_MAX;
		handle.setPointerCapture(event.pointerId);
		handle.classList.add("dragging");
		document.body.classList.add("resizing-cols");

		const onMove = (moveEvent: globalThis.PointerEvent) => {
			const dx = moveEvent.clientX - startX;
			const next = clamp(
				side === "left" ? startWidth + dx : startWidth - dx,
				min,
				max,
			);
			if (side === "left") {
				setChatWidth(next);
			} else {
				setFilesWidth(next);
			}
		};

		const onUp = () => {
			handle.classList.remove("dragging");
			document.body.classList.remove("resizing-cols");
			handle.removeEventListener("pointermove", onMove);
			handle.removeEventListener("pointerup", onUp);
			handle.removeEventListener("pointercancel", onUp);
		};

		handle.addEventListener("pointermove", onMove);
		handle.addEventListener("pointerup", onUp);
		handle.addEventListener("pointercancel", onUp);
	};
	const latestWorkspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: 5000,
	});
	const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
		null,
	);
	const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
	const [runSource, setRunSource] = useState<RunEventSource | null>(null);
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
			setRunSource(null);
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
				<div className="rail-brand" aria-label="Julia">
					{/* eslint-disable-next-line @next/next/no-img-element */}
					<img src="/icon.svg" alt="Julia" width={36} height={36} />
				</div>
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
					<Plus aria-hidden="true" size={16} strokeWidth={1.6} />
				</button>
				<div className="rail-thread-list" role="list">
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
									setRunSource(null);
									setSelectedArtifactId(null);
								}}
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
			<div
				className="workspace-grid"
				style={
					{
						"--chat-w": `${chatWidth}px`,
						"--files-w": `${filesWidth}px`,
					} as CSSProperties
				}
			>
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
							contextReferences={contextReferences}
							messages={payload.messages ?? []}
							onRemoveContext={(referenceId) =>
								removeContext.mutate({ referenceId, projectId })
							}
							onRunCreated={setRunSource}
							projectId={projectId}
							runSource={runSource}
							threadId={payload.thread?.id}
						/>
						<div
							aria-label="Resize chat panel"
							aria-orientation="vertical"
							className="column-resizer left"
							onPointerDown={(event) => handleResize(event, "left")}
							role="separator"
						/>
						<MolstarViewer artifact={selectedArtifact} />
						<div
							aria-label="Resize files panel"
							aria-orientation="vertical"
							className="column-resizer right"
							onPointerDown={(event) => handleResize(event, "right")}
							role="separator"
						/>
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

function initialFromLabel(label: string): string {
	return label.trim().charAt(0).toUpperCase() || "N";
}

function userInitial(user?: WorkspaceUser): string {
	return initialFromLabel(user?.name ?? user?.email ?? "U");
}
