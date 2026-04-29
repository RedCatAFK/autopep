"use client";

import { useEffect, useMemo, useState } from "react";

import type { ChatPanelSendInput } from "@/app/_components/chat-panel";
import type { ProteinSelection } from "@/app/_components/molstar-stage";
import type { RecipeInput } from "@/app/_components/recipe-manager";
import { api } from "@/trpc/react";
import {
	type WorkspaceArtifact,
	type WorkspaceCandidate,
	type WorkspaceCandidateScore,
	type WorkspaceChatMessage,
	type WorkspaceEvent,
	WorkspaceShell,
} from "./workspace-shell";

const spikeGoal = "Design a protein binder for SARS-CoV-2 spike RBD";

export function AutopepWorkspace() {
	const utils = api.useUtils();
	const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(
		null,
	);

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

	const payload = selectedWorkspace.data ?? latestWorkspace.data;

	useEffect(() => {
		if (!activeWorkspaceId && latestWorkspace.data?.workspace.id) {
			setActiveWorkspaceId(latestWorkspace.data.workspace.id);
		}
	}, [activeWorkspaceId, latestWorkspace.data?.workspace.id]);

	const invalidateWorkspace = async (workspaceId?: string | null) => {
		await Promise.all([
			utils.workspace.listWorkspaces.invalidate(),
			utils.workspace.getLatestWorkspace.invalidate(),
			workspaceId
				? utils.workspace.getWorkspace.invalidate({ workspaceId })
				: Promise.resolve(),
		]);
	};

	const createWorkspace = api.workspace.createWorkspace.useMutation({
		onSuccess: async (result) => {
			setActiveWorkspaceId(result.workspace.id);
			await invalidateWorkspace(result.workspace.id);
		},
	});
	const archiveWorkspace = api.workspace.archiveWorkspace.useMutation({
		onSuccess: async () => {
			setActiveWorkspaceId(null);
			await invalidateWorkspace();
		},
	});
	const sendMessage = api.workspace.sendMessage.useMutation({
		onSuccess: async (result) => {
			setActiveWorkspaceId(result.workspace.id);
			await invalidateWorkspace(result.workspace.id);
		},
	});
	const createContextReference =
		api.workspace.createContextReference.useMutation({
			onSuccess: async (_reference, variables) => {
				await invalidateWorkspace(variables.workspaceId);
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
				signedUrl: artifact.signedUrl,
				sourceUrl: artifact.sourceUrl,
				type: artifact.type,
			})),
		[payload?.artifacts],
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

	const artifactRows = artifacts;
	const findCifArtifact = (candidateId?: string) =>
		artifactRows.find(
			(artifact) =>
				(!candidateId || artifact.candidateId === candidateId) &&
				artifact.type === "prepared_cif",
		) ??
		artifactRows.find(
			(artifact) =>
				(!candidateId || artifact.candidateId === candidateId) &&
				(artifact.type === "source_cif" || artifact.kind === "mmcif"),
		) ??
		null;
	const selectedCandidate =
		candidates.find(
			(candidate) =>
				candidate.proteinaReady && Boolean(findCifArtifact(candidate.id)),
		) ??
		candidates[0] ??
		null;
	const selectedArtifact =
		findCifArtifact(selectedCandidate?.id) ?? findCifArtifact();
	const projectGoal = payload?.project.goal || spikeGoal;
	const currentWorkspaceId = activeWorkspaceId ?? payload?.workspace.id ?? null;

	const sendWorkspaceMessage = (input: ChatPanelSendInput) => {
		sendMessage.mutate({
			contextRefs: input.contextRefs,
			prompt: input.prompt,
			recipeRefs: input.recipeRefs,
			workspaceId: currentWorkspaceId ?? undefined,
		});
	};

	const createWorkspaceFromRail = () => {
		createWorkspace.mutate({
			description: "New Autopep workspace",
			name: "Untitled workspace",
		});
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

	const createProteinSelectionReference = (selection: ProteinSelection) => {
		if (!currentWorkspaceId) {
			return;
		}
		createContextReference.mutate({
			artifactId: selection.artifactId,
			candidateId: selection.candidateId,
			kind: "protein_selection",
			label: selection.label,
			selector: selection.selector,
			workspaceId: currentWorkspaceId,
		});
	};

	return (
		<WorkspaceShell
			activeRunStatus={payload?.activeRun?.status ?? null}
			activeWorkspaceId={currentWorkspaceId}
			artifacts={artifacts}
			candidateScores={candidateScores}
			candidates={candidates}
			chatMessages={messages}
			contextReferences={contextReferences}
			events={events}
			isChatDisabled={!currentWorkspaceId}
			isLoadingWorkspace={
				latestWorkspace.isLoading ||
				selectedWorkspace.isLoading ||
				latestWorkspace.isFetching ||
				selectedWorkspace.isFetching
			}
			isRecipeDisabled={!currentWorkspaceId}
			isSavingRecipe={
				createRecipe.isPending ||
				updateRecipe.isPending ||
				archiveRecipe.isPending
			}
			isSendingMessage={sendMessage.isPending}
			onArchiveRecipe={archiveRecipeForWorkspace}
			onArchiveWorkspace={(workspaceId) =>
				archiveWorkspace.mutate({ workspaceId })
			}
			onCreateRecipe={createRecipeForWorkspace}
			onCreateWorkspace={createWorkspaceFromRail}
			onProteinSelection={createProteinSelectionReference}
			onRefresh={() => {
				void invalidateWorkspace(currentWorkspaceId);
			}}
			onSelectWorkspace={setActiveWorkspaceId}
			onSendMessage={sendWorkspaceMessage}
			onUpdateRecipe={updateRecipeForWorkspace}
			projectGoal={projectGoal}
			recipes={recipes}
			selectedArtifact={selectedArtifact ?? null}
			selectedCandidate={selectedCandidate}
			workspaces={(workspacesQuery.data ?? []).map((workspace) => ({
				description: workspace.description,
				id: workspace.id,
				name: workspace.name,
			}))}
		/>
	);
}
