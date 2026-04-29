"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

import { api } from "@/trpc/react";
import {
	type WorkspaceArtifact,
	type WorkspaceCandidate,
	type WorkspaceChatMessage,
	type WorkspaceEvent,
	WorkspaceShell,
} from "./workspace-shell";

const MolstarViewer = dynamic(
	() => import("./molstar-viewer").then((mod) => mod.MolstarViewer),
	{ ssr: false },
);

const spikeGoal = "Design a protein binder for SARS-CoV-2 spike RBD";

export function AutopepWorkspace() {
	const utils = api.useUtils();
	const [chatMessages, setChatMessages] = useState<WorkspaceChatMessage[]>([
		{
			id: "welcome",
			role: "assistant",
			text: "Ask about run status, ranked PDB structures, bioRxiv/PubMed evidence, or CIF readiness.",
		},
	]);
	const workspace = api.workspace.getLatestWorkspace.useQuery(undefined, {
		refetchInterval: (query) => {
			const status = query.state.data?.activeRun?.status;
			return status === "queued" || status === "running" ? 2000 : false;
		},
	});

	const createRun = api.workspace.createProjectRun.useMutation({
		onSuccess: async () => {
			await utils.workspace.getLatestWorkspace.invalidate();
		},
	});
	const answerQuestion = api.workspace.answerQuestion.useMutation();

	const candidates = useMemo<WorkspaceCandidate[]>(
		() =>
			(workspace.data?.candidates ?? []).map((candidate) => ({
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
		[workspace.data?.candidates],
	);

	const events = useMemo<WorkspaceEvent[]>(
		() =>
			(workspace.data?.events ?? []).map((event) => ({
				detail: event.detail,
				id: event.id,
				payloadJson: event.payloadJson,
				sequence: event.sequence,
				title: event.title,
				type: event.type,
			})),
		[workspace.data?.events],
	);

	const artifacts = useMemo<WorkspaceArtifact[]>(
		() =>
			(workspace.data?.artifacts ?? []).map((artifact) => ({
				byteSize: artifact.byteSize,
				candidateId: artifact.candidateId,
				fileName: artifact.fileName,
				id: artifact.id,
				signedUrl: artifact.signedUrl,
				sourceUrl: artifact.sourceUrl,
				type: artifact.type,
			})),
		[workspace.data?.artifacts],
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
				artifact.type === "source_cif",
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
	const targetName =
		workspace.data?.targetEntities[0]?.name ??
		inferTargetName(workspace.data?.activeRun?.prompt) ??
		"SARS-CoV-2 spike RBD";
	const projectGoal = workspace.data?.project.goal ?? spikeGoal;

	return (
		<WorkspaceShell
			artifactLabel={selectedArtifact?.fileName ?? "No CIF artifact yet"}
			artifacts={artifacts}
			candidates={candidates}
			chatMessages={chatMessages}
			events={events}
			isAnsweringQuestion={answerQuestion.isPending}
			isCreatingRun={createRun.isPending}
			isLoadingWorkspace={workspace.isLoading || workspace.isFetching}
			onAskQuestion={(question) => {
				const userMessage: WorkspaceChatMessage = {
					id: `user-${Date.now()}`,
					role: "user",
					text: question,
				};
				setChatMessages((messages) => [...messages, userMessage]);
				answerQuestion.mutate(
					{
						projectId: workspace.data?.project.id,
						question,
					},
					{
						onError: (error) => {
							setChatMessages((messages) => [
								...messages,
								{
									id: `assistant-error-${Date.now()}`,
									role: "assistant",
									text: error.message,
								},
							]);
						},
						onSuccess: (result) => {
							setChatMessages((messages) => [
								...messages,
								{
									id: `assistant-${Date.now()}`,
									role: "assistant",
									text: result.answer,
								},
							]);
						},
					},
				);
			}}
			onRefresh={() => {
				void workspace.refetch();
			}}
			onStartGoal={(goal, options) => {
				createRun.mutate({
					goal,
					name: inferProjectName(goal),
					topK: options?.topK ?? 5,
				});
			}}
			projectGoal={projectGoal}
			runStatus={workspace.data?.activeRun?.status ?? null}
			selectedArtifact={selectedArtifact ?? null}
			selectedCandidate={selectedCandidate}
			targetName={targetName}
		>
			<MolstarViewer
				label={selectedArtifact?.fileName ?? "Awaiting CIF"}
				url={selectedArtifact?.sourceUrl ?? selectedArtifact?.signedUrl ?? null}
			/>
		</WorkspaceShell>
	);
}

function inferTargetName(prompt?: string | null) {
	if (!prompt) {
		return null;
	}

	const normalized = prompt.toLowerCase();
	if (normalized.includes("3cl")) {
		return "3CL-protease";
	}
	if (normalized.includes("spike") || normalized.includes("rbd")) {
		return "SARS-CoV-2 spike RBD";
	}

	return prompt.length > 46 ? `${prompt.slice(0, 43)}...` : prompt;
}

function inferProjectName(goal: string) {
	const normalized = goal.toLowerCase();
	if (normalized.includes("3cl") || normalized.includes("protease")) {
		return "3CL-protease binder";
	}
	if (normalized.includes("spike") || normalized.includes("rbd")) {
		return "Spike RBD binder";
	}

	return goal.length > 80 ? `${goal.slice(0, 77)}...` : goal;
}
