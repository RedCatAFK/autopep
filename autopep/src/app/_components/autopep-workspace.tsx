"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ChatPanelSendInput } from "@/app/_components/chat-panel";
import { authClient } from "@/server/better-auth/client";
import { api } from "@/trpc/react";
import { buildStreamItems } from "./build-stream-items";
import type { ProteinSelection } from "./molstar-viewer";
import type { RecipeInput } from "./recipes-dialog";
import { useAttachmentUpload } from "./use-attachment-upload";
import type { ViewerTab } from "./viewer-tabs";
import {
	type WorkspaceArtifact,
	type WorkspaceCandidate,
	type WorkspaceCandidateScore,
	type WorkspaceChatMessage,
	type WorkspaceEvent,
	type WorkspaceFileArtifact,
	type WorkspaceRunSummary,
	WorkspaceShell,
} from "./workspace-shell";

export type AutopepAccount = {
	email?: string | null;
	name?: string | null;
};

export type IsLoadingWorkspaceArgs = {
	latestIsLoading: boolean;
	latestIsFetching: boolean;
	selectedIsLoading: boolean;
	selectedIsFetching: boolean;
};

export const computeIsLoadingWorkspace = ({
	latestIsLoading,
	selectedIsLoading,
}: IsLoadingWorkspaceArgs) => latestIsLoading || selectedIsLoading;

type AutopepWorkspaceProps = {
	account?: AutopepAccount;
};

export function AutopepWorkspace({ account }: AutopepWorkspaceProps) {
	const router = useRouter();
	const utils = api.useUtils();
	const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(
		null,
	);
	const [isDraftWorkspace, setIsDraftWorkspace] = useState(false);
	const [tabs, setTabs] = useState<ViewerTab[]>([]);
	const [activeTabId, setActiveTabId] = useState<string | null>(null);
	const [isRecipesOpen, setIsRecipesOpen] = useState(false);
	const [isSigningOut, setIsSigningOut] = useState(false);
	const [signOutError, setSignOutError] = useState<string | null>(null);
	const previousCandidateCount = useRef(0);

	const workspacesQuery = api.workspace.listWorkspaces.useQuery();
	const latestWorkspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: (query) => {
			const status = query.state.data?.activeRun?.status;
			return status === "queued" || status === "running" ? 2000 : false;
		},
	});
	const selectedWorkspace = api.workspace.getWorkspace.useQuery(
		{
			workspaceId: activeWorkspaceId ?? "00000000-0000-4000-8000-000000000000",
		},
		{
			enabled: Boolean(activeWorkspaceId),
			refetchInterval: (query) => {
				const status = query.state.data?.activeRun?.status;
				return status === "queued" || status === "running" ? 2000 : false;
			},
		},
	);

	// Only fall back to latestWorkspace.data when it actually matches the
	// active id (or no id is selected yet). Otherwise the previous workspace's
	// stale data leaks through during transitions — e.g. just after sending the
	// first message in a fresh workspace, before the new workspace's query
	// has resolved.
	const fallbackLatest =
		activeWorkspaceId === null ||
		latestWorkspace.data?.workspace.id === activeWorkspaceId
			? latestWorkspace.data
			: null;
	const payload = isDraftWorkspace
		? null
		: (selectedWorkspace.data ?? fallbackLatest);
	const currentWorkspaceId = isDraftWorkspace
		? null
		: (activeWorkspaceId ?? payload?.workspace.id ?? null);

	useEffect(() => {
		if (
			!isDraftWorkspace &&
			!activeWorkspaceId &&
			latestWorkspace.data?.workspace.id
		) {
			setActiveWorkspaceId(latestWorkspace.data.workspace.id);
		}
	}, [activeWorkspaceId, isDraftWorkspace, latestWorkspace.data?.workspace.id]);

	const invalidateWorkspace = async (workspaceId?: string | null) => {
		await Promise.all([
			utils.workspace.listWorkspaces.invalidate(),
			utils.workspace.getLatestWorkspace.invalidate(),
			workspaceId
				? utils.workspace.getWorkspace.invalidate({ workspaceId })
				: Promise.resolve(),
		]);
	};

	const archiveWorkspace = api.workspace.archiveWorkspace.useMutation({
		onSuccess: async () => {
			setActiveWorkspaceId(null);
			setIsDraftWorkspace(false);
			await invalidateWorkspace();
		},
	});
	const renameWorkspace = api.workspace.renameWorkspace.useMutation({
		onSuccess: async (_result, variables) => {
			await invalidateWorkspace(variables.workspaceId);
		},
	});
	const sendMessage = api.workspace.sendMessage.useMutation({
		onSuccess: async (result) => {
			setActiveWorkspaceId(result.workspace.id);
			setIsDraftWorkspace(false);
			await invalidateWorkspace(result.workspace.id);
		},
	});
	const createRecipe = api.workspace.createRecipe.useMutation({
		onSuccess: async (_result, variables) => {
			await invalidateWorkspace(variables.workspaceId);
		},
	});
	const updateRecipe = api.workspace.updateRecipe.useMutation({
		onSuccess: async (_result, variables) => {
			await invalidateWorkspace(variables.workspaceId);
		},
	});
	const archiveRecipe = api.workspace.archiveRecipe.useMutation({
		onSuccess: async () => {
			await invalidateWorkspace(activeWorkspaceId);
		},
	});
	const createAttachmentMutation = api.workspace.createAttachment.useMutation();
	const confirmAttachmentMutation =
		api.workspace.confirmAttachment.useMutation();
	const deleteAttachmentMutation = api.workspace.deleteAttachment.useMutation({
		onSuccess: async () => {
			await invalidateWorkspace(currentWorkspaceId);
		},
	});
	const createContextReferenceMutation =
		api.workspace.createContextReference.useMutation({
			onSuccess: async () => {
				await invalidateWorkspace(currentWorkspaceId);
			},
		});
	const deleteContextReferenceMutation =
		api.workspace.deleteContextReference.useMutation({
			onSuccess: async () => {
				await invalidateWorkspace(currentWorkspaceId);
			},
		});

	const candidates = useMemo<WorkspaceCandidate[]>(
		() =>
			(payload?.candidates ?? []).map((candidate) => ({
				citationJson: candidate.citationJson,
				id: candidate.id,
				method: candidate.method,
				organism: candidate.organism,
				proteinaReady: candidate.proteinaReady,
				rank: candidate.rank,
				rcsbId: candidate.rcsbId,
				relevanceScore: candidate.relevanceScore,
				resolutionAngstrom: candidate.resolutionAngstrom,
				selectionRationale: candidate.selectionRationale,
				title: candidate.title,
			})),
		[payload?.candidates],
	);

	const events = useMemo<WorkspaceEvent[]>(
		() =>
			(payload?.events ?? []).map((event) => ({
				createdAt: event.createdAt,
				detail: event.detail,
				displayJson: event.displayJson,
				id: event.id,
				payloadJson: event.payloadJson,
				rawJson: event.rawJson,
				sequence: event.sequence,
				summary: event.summary,
				title: event.title,
				type: event.type,
			})),
		[payload?.events],
	);

	const artifacts = useMemo<WorkspaceArtifact[]>(
		() =>
			(payload?.artifacts ?? []).map((artifact) => ({
				byteSize: artifact.byteSize,
				candidateId: artifact.candidateId,
				fileName: artifact.fileName,
				id: artifact.id,
				kind: artifact.kind,
				name: artifact.name,
				runId: artifact.runId,
				signedUrl: artifact.signedUrl,
				sourceUrl: artifact.sourceUrl,
				type: artifact.type,
			})),
		[payload?.artifacts],
	);

	const fileArtifacts = useMemo<WorkspaceFileArtifact[]>(
		() =>
			artifacts.map((artifact) => ({
				byteSize: artifact.byteSize ?? 0,
				candidateId: artifact.candidateId,
				fileName: artifact.fileName,
				id: artifact.id,
				kind: artifact.kind ?? artifact.type,
				runId: artifact.runId ?? null,
				signedUrl: artifact.signedUrl,
				type: artifact.type,
			})),
		[artifacts],
	);

	const candidateScores = useMemo<WorkspaceCandidateScore[]>(
		() =>
			(payload?.candidateScores ?? []).map((score) => ({
				candidateId: score.candidateId,
				label: score.label,
				scorer: score.scorer,
				unit: score.unit,
				value: score.value,
			})),
		[payload?.candidateScores],
	);

	const messages = useMemo<WorkspaceChatMessage[]>(
		() =>
			(payload?.messages ?? []).map((message) => ({
				content: message.content,
				createdAt: message.createdAt,
				id: message.id,
				role: message.role as "assistant" | "system" | "user",
			})),
		[payload?.messages],
	);

	const recipes = useMemo(
		() =>
			(payload?.recipes ?? [])
				.filter((recipe) => !recipe.archivedAt)
				.map((recipe) => ({
					bodyMarkdown: recipe.bodyMarkdown,
					description: recipe.description,
					enabledByDefault: recipe.enabledByDefault,
					id: recipe.id,
					name: recipe.name,
				})),
		[payload?.recipes],
	);

	const contextReferences = useMemo(
		() =>
			(payload?.contextReferences ?? []).map((reference) => ({
				id: reference.id,
				label: reference.label,
			})),
		[payload?.contextReferences],
	);

	const runs = useMemo<WorkspaceRunSummary[]>(
		() =>
			(payload?.runs ?? []).flatMap((run) =>
				typeof run.startedAt === "string"
					? [
							{
								id: run.id,
								startedAt: run.startedAt,
								status: run.status,
							},
						]
					: [],
			),
		[payload?.runs],
	);

	const streamItems = useMemo(
		() =>
			buildStreamItems({
				events: events.map((event) => ({
					createdAt: event.createdAt,
					displayJson: event.displayJson ?? {},
					id: event.id,
					sequence: event.sequence,
					summary: event.summary,
					title: event.title,
					type: event.type,
				})),
				messages: messages.map((message) => ({
					content: message.content ?? message.text ?? "",
					createdAt: message.createdAt,
					id: message.id,
					role: message.role,
				})),
			}),
		[events, messages],
	);

	const findCifArtifact = (candidateId?: string) =>
		artifacts.find(
			(artifact) =>
				(!candidateId || artifact.candidateId === candidateId) &&
				(artifact.type === "chai_result" || artifact.kind === "chai_result"),
		) ??
		artifacts.find(
			(artifact) =>
				(!candidateId || artifact.candidateId === candidateId) &&
				artifact.type === "prepared_cif",
		) ??
		artifacts.find(
			(artifact) =>
				(!candidateId || artifact.candidateId === candidateId) &&
				(artifact.type === "source_cif" || artifact.kind === "mmcif"),
		) ??
		null;

	const attachmentUpload = useAttachmentUpload({
		confirmAttachment: confirmAttachmentMutation.mutateAsync,
		createAttachment: createAttachmentMutation.mutateAsync,
		workspaceId: currentWorkspaceId,
	});

	// Auto-pin: when the candidates list goes from empty -> non-empty,
	// auto-set the candidates tab as active if no other tab is active.
	useEffect(() => {
		const previous = previousCandidateCount.current;
		const current = candidates.length;
		previousCandidateCount.current = current;
		if (previous === 0 && current > 0 && activeTabId === null) {
			setActiveTabId("candidates");
		}
	}, [candidates.length, activeTabId]);

	// Drop tabs whose underlying artifact no longer exists.
	useEffect(() => {
		setTabs((prev) => {
			const valid = prev.filter(
				(tab) =>
					tab.kind === "candidates" ||
					fileArtifacts.some((artifact) => artifact.id === tab.artifactId),
			);
			if (valid.length === prev.length) return prev;
			return valid;
		});
	}, [fileArtifacts]);

	const openFileInTab = (artifact: WorkspaceFileArtifact) => {
		const tabId = `file:${artifact.id}`;
		setTabs((prev) => {
			if (prev.some((tab) => tab.id === tabId)) {
				return prev;
			}
			return [
				...prev,
				{
					artifactId: artifact.id,
					candidateId: artifact.candidateId,
					fileName: artifact.fileName,
					id: tabId,
					kind: "file",
					signedUrl: artifact.signedUrl,
				},
			];
		});
		setActiveTabId(tabId);
	};

	const closeTab = (tabId: string) => {
		setTabs((prev) => prev.filter((tab) => tab.id !== tabId));
		if (activeTabId === tabId) {
			setActiveTabId(candidates.length > 0 ? "candidates" : null);
		}
	};

	const openArtifactInTab = (artifactId: string) => {
		const artifact = fileArtifacts.find((entry) => entry.id === artifactId);
		if (!artifact) return;
		openFileInTab(artifact);
	};

	const openCandidateInTab = (candidateId: string) => {
		const cif = findCifArtifact(candidateId);
		if (!cif) return;
		const fileArtifact = fileArtifacts.find((entry) => entry.id === cif.id);
		if (!fileArtifact) return;
		openFileInTab(fileArtifact);
	};

	const activeArtifactId = (() => {
		const tab = tabs.find((entry) => entry.id === activeTabId);
		if (tab && tab.kind === "file") return tab.artifactId;
		return null;
	})();

	const sendWorkspaceMessage = (input: ChatPanelSendInput) => {
		sendMessage.mutate({
			attachmentRefs: input.attachmentRefs,
			contextRefs: input.contextRefs,
			prompt: input.prompt,
			recipeRefs: input.recipeRefs,
			workspaceId: currentWorkspaceId ?? undefined,
		});
	};

	const createWorkspaceFromRail = () => {
		setActiveWorkspaceId(null);
		setIsDraftWorkspace(true);
	};

	const selectExistingWorkspace = (workspaceId: string) => {
		setIsDraftWorkspace(false);
		setActiveWorkspaceId(workspaceId);
	};

	const createRecipeForWorkspace = (input: RecipeInput) => {
		if (!currentWorkspaceId) {
			return;
		}
		createRecipe.mutate({ ...input, workspaceId: currentWorkspaceId });
	};

	const updateRecipeForWorkspace = (
		input: RecipeInput & { recipeId: string },
	) => {
		if (!currentWorkspaceId) {
			return;
		}
		updateRecipe.mutate({ ...input, workspaceId: currentWorkspaceId });
	};

	const archiveRecipeForWorkspace = (recipeId: string) => {
		archiveRecipe.mutate({ recipeId });
	};

	const deleteWorkspaceAttachment = (artifactId: string) => {
		deleteAttachmentMutation.mutate({ artifactId });
	};

	const addProteinSelectionToContext = (selection: ProteinSelection) => {
		if (!currentWorkspaceId) {
			return;
		}

		createContextReferenceMutation.mutate({
			artifactId: selection.artifactId,
			candidateId: selection.candidateId,
			kind: "protein_selection",
			label: selection.label,
			selector: selection.selector,
			workspaceId: currentWorkspaceId,
		});
	};

	const removeContextReference = (contextReferenceId: string) => {
		deleteContextReferenceMutation.mutate({ contextReferenceId });
	};

	const signOut = async () => {
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

	const persistedWorkspaces = (workspacesQuery.data ?? []).map((workspace) => ({
		description: workspace.description,
		id: workspace.id,
		name: workspace.name,
	}));
	const railWorkspaces = isDraftWorkspace
		? [
				{
					description: null,
					id: DRAFT_WORKSPACE_ID,
					isDraft: true as const,
					name: "Untitled workspace",
				},
				...persistedWorkspaces,
			]
		: persistedWorkspaces;
	const railActiveWorkspaceId = isDraftWorkspace
		? DRAFT_WORKSPACE_ID
		: currentWorkspaceId;

	return (
		<WorkspaceShell
			account={account}
			activeArtifactId={activeArtifactId}
			activeRunStatus={payload?.activeRun?.status ?? null}
			activeTabId={activeTabId}
			activeWorkspaceId={railActiveWorkspaceId}
			candidateScores={candidateScores}
			candidates={candidates}
			chatAttachments={attachmentUpload.attachments}
			closeTab={closeTab}
			contextReferences={contextReferences}
			fileArtifacts={fileArtifacts}
			isChatDisabled={!isDraftWorkspace && !currentWorkspaceId}
			isLoadingWorkspace={computeIsLoadingWorkspace({
				latestIsLoading: latestWorkspace.isLoading,
				latestIsFetching: latestWorkspace.isFetching,
				selectedIsLoading: selectedWorkspace.isLoading,
				selectedIsFetching: selectedWorkspace.isFetching,
			})}
			isRecipesOpen={isRecipesOpen}
			isSavingRecipe={
				createRecipe.isPending ||
				updateRecipe.isPending ||
				archiveRecipe.isPending
			}
			isSendingMessage={sendMessage.isPending}
			onArchiveRecipe={archiveRecipeForWorkspace}
			onArchiveWorkspace={(workspaceId) => {
				if (workspaceId === DRAFT_WORKSPACE_ID) {
					setIsDraftWorkspace(false);
					return;
				}
				archiveWorkspace.mutate({ workspaceId });
			}}
			onClearChatAttachments={attachmentUpload.clear}
			onCloseRecipes={() => setIsRecipesOpen(false)}
			onCreateRecipe={createRecipeForWorkspace}
			onCreateWorkspace={createWorkspaceFromRail}
			onDeleteAttachment={deleteWorkspaceAttachment}
			onOpenRecipes={() => setIsRecipesOpen(true)}
			onProteinSelection={addProteinSelectionToContext}
			onRemoveChatAttachment={attachmentUpload.remove}
			onRemoveContextReference={removeContextReference}
			onRenameWorkspace={(workspaceId, name) => {
				if (workspaceId === DRAFT_WORKSPACE_ID) {
					return;
				}
				renameWorkspace.mutate({ name, workspaceId });
			}}
			onSelectWorkspace={(workspaceId) => {
				if (workspaceId === DRAFT_WORKSPACE_ID) {
					setIsDraftWorkspace(true);
					setActiveWorkspaceId(null);
					return;
				}
				selectExistingWorkspace(workspaceId);
			}}
			onSendMessage={sendWorkspaceMessage}
			onSignOut={signOut}
			onUpdateRecipe={updateRecipeForWorkspace}
			onUploadChatAttachments={attachmentUpload.upload}
			openArtifactInTab={openArtifactInTab}
			openCandidateInTab={openCandidateInTab}
			openFileInTab={openFileInTab}
			recipes={recipes}
			runs={runs}
			setActiveTabId={setActiveTabId}
			signingOut={isSigningOut}
			signOutError={signOutError}
			streamItems={streamItems}
			tabs={tabs}
			workspaces={railWorkspaces}
		/>
	);
}

export const DRAFT_WORKSPACE_ID = "__draft__";
