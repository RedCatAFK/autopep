"use client";

import { Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/trpc/react";
import { ChatPanel, type WorkspaceMessage } from "./chat-panel";
import type { WorkspaceContextReference } from "./context-pills";
import { FilePanel, type WorkspaceArtifact } from "./file-panel";
import { MolstarViewer } from "./molstar-viewer";

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
	messages?: WorkspaceMessage[];
	artifacts?: WorkspaceArtifact[];
	contextReferences?: WorkspaceContextReference[];
	activeRunId?: string | null;
};

export function WorkspaceShell() {
	const utils = api.useUtils();
	const workspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: 5000,
	});
	const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
		null,
	);
	const [activeRunId, setActiveRunId] = useState<string | null>(null);
	const createThread = api.workspace.createThread.useMutation({
		onSuccess: () => {
			setActiveRunId(null);
			setSelectedArtifactId(null);
			void utils.workspace.getLatestWorkspace.invalidate();
		},
	});
	const addContext = api.workspace.addContextReference.useMutation({
		onSuccess: () => {
			void utils.workspace.getLatestWorkspace.invalidate();
		},
	});
	const removeContext = api.workspace.deleteContextReference.useMutation({
		onSuccess: () => {
			void utils.workspace.getLatestWorkspace.invalidate();
		},
	});

	const payload = (workspace.data ?? {}) as WorkspacePayload;
	const projectId = payload.project?.id ?? "";
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
			</nav>
			<div className="workspace-grid">
				{workspace.isLoading ? (
					<div className="workspace-loading">Loading workspace...</div>
				) : workspace.error ? (
					<div className="workspace-loading error" role="alert">
						{workspace.error.message}
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
