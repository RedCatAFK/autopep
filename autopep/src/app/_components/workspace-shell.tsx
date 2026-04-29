"use client";

import { ArrowClockwise } from "@phosphor-icons/react";

import {
	type ChatContextReference,
	type ChatMessage,
	ChatPanel,
	type ChatPanelSendInput,
	type ChatRecipe,
} from "./chat-panel";
import { JourneyPanel } from "./journey-panel";
import {
	MolstarStage,
	type ProteinSelection,
	type StageArtifact,
	type StageCandidate,
} from "./molstar-stage";
import { type Recipe, type RecipeInput, RecipeManager } from "./recipe-manager";
import type { TraceEvent } from "./trace-event-card";
import { type RailWorkspace, WorkspaceRail } from "./workspace-rail";

export type WorkspaceCandidate = {
	citationJson?: Record<string, unknown>;
	id: string;
	method?: string | null;
	organism?: string | null;
	proteinaReady?: boolean;
	rank: number;
	rcsbId?: string;
	relevanceScore?: number;
	resolutionAngstrom?: number | null;
	selectionRationale?: string;
	title: string;
};

export type WorkspaceEvent = {
	detail?: string | null;
	displayJson?: Record<string, unknown>;
	id: string;
	payloadJson?: Record<string, unknown>;
	rawJson?: Record<string, unknown>;
	sequence: number;
	summary?: string | null;
	title: string;
	type: string;
};

export type WorkspaceArtifact = {
	byteSize?: number;
	candidateId: string | null;
	fileName: string;
	id: string;
	kind?: string;
	name?: string;
	signedUrl: string | null;
	sourceUrl: string | null;
	type: string;
};

export type WorkspaceChatMessage = {
	content?: string;
	id: string;
	role: "assistant" | "system" | "user";
	text?: string;
};

export type WorkspaceCandidateScore = {
	candidateId: string;
	label: string | null;
	scorer: string;
	unit: string | null;
	value: number | null;
};

type WorkspaceShellProps = {
	activeRunStatus: string | null;
	activeWorkspaceId: string | null;
	artifacts: WorkspaceArtifact[];
	candidateScores: WorkspaceCandidateScore[];
	candidates: WorkspaceCandidate[];
	chatMessages: WorkspaceChatMessage[];
	contextReferences: ChatContextReference[];
	events: WorkspaceEvent[];
	isChatDisabled?: boolean;
	isLoadingWorkspace: boolean;
	isRecipeDisabled?: boolean;
	isSavingRecipe?: boolean;
	isSendingMessage: boolean;
	onArchiveRecipe: (recipeId: string) => void;
	onArchiveWorkspace: (workspaceId: string) => void;
	onCreateRecipe: (input: RecipeInput) => void;
	onCreateWorkspace: () => void;
	onProteinSelection: (selection: ProteinSelection) => void;
	onRefresh: () => void;
	onSelectWorkspace: (workspaceId: string) => void;
	onSendMessage: (input: ChatPanelSendInput) => void;
	onUpdateRecipe: (input: RecipeInput & { recipeId: string }) => void;
	projectGoal: string;
	recipes: Recipe[];
	selectedArtifact: WorkspaceArtifact | null;
	selectedCandidate: WorkspaceCandidate | null;
	workspaces: RailWorkspace[];
};

export function WorkspaceShell({
	activeRunStatus,
	activeWorkspaceId,
	artifacts,
	candidateScores,
	candidates,
	chatMessages,
	contextReferences,
	events,
	isChatDisabled = false,
	isLoadingWorkspace,
	isRecipeDisabled = false,
	isSavingRecipe = false,
	isSendingMessage,
	onArchiveRecipe,
	onArchiveWorkspace,
	onCreateRecipe,
	onCreateWorkspace,
	onProteinSelection,
	onRefresh,
	onSelectWorkspace,
	onSendMessage,
	onUpdateRecipe,
	projectGoal,
	recipes,
	selectedArtifact,
	selectedCandidate,
	workspaces,
}: WorkspaceShellProps) {
	const traceEvents = events.map(toTraceEvent);
	const stageArtifact = toStageArtifact(selectedArtifact);
	const stageCandidate = toStageCandidate(selectedCandidate);
	const normalizedMessages = chatMessages.map(toChatMessage);
	const chatRecipes: ChatRecipe[] = recipes.map((recipe) => ({
		enabledByDefault: recipe.enabledByDefault,
		id: recipe.id,
		name: recipe.name,
	}));

	return (
		<main className="grid min-h-[100dvh] grid-cols-1 bg-[#f8f7f2] text-[#17211e] lg:fixed lg:inset-0 lg:min-h-0 lg:grid-cols-[64px_minmax(320px,390px)_minmax(0,1fr)_minmax(300px,360px)] lg:overflow-hidden">
			<WorkspaceRail
				activeWorkspaceId={activeWorkspaceId}
				onArchiveWorkspace={onArchiveWorkspace}
				onCreateWorkspace={onCreateWorkspace}
				onSelectWorkspace={onSelectWorkspace}
				workspaces={workspaces}
			/>
			<ChatPanel
				contextReferences={contextReferences}
				events={traceEvents}
				isDisabled={isChatDisabled}
				isSending={isSendingMessage}
				messages={normalizedMessages}
				onSend={onSendMessage}
				recipes={chatRecipes}
			/>
			<section className="relative min-w-0 lg:min-h-0 lg:overflow-hidden lg:border-[#e5e2d9] lg:border-r">
				<div className="absolute top-3 right-3 z-[1]">
					<button
						aria-label="Refresh workspace"
						className="flex size-8 items-center justify-center rounded-md border border-[#d7d4c9] bg-[#fffef9] text-[#394541] shadow-[0_10px_28px_-24px_rgba(25,39,33,0.75)] transition-colors duration-200 hover:border-[#cbd736] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
						onClick={onRefresh}
						type="button"
					>
						<ArrowClockwise aria-hidden="true" size={17} />
					</button>
				</div>
				<MolstarStage
					artifact={stageArtifact}
					candidate={stageCandidate}
					onProteinSelection={onProteinSelection}
				/>
				{isLoadingWorkspace ? (
					<div className="pointer-events-none absolute inset-x-6 bottom-6 overflow-hidden rounded-md border border-[#dfe4d7] bg-[#fffef9]/90 p-3 text-[#52605a] text-xs shadow-[0_16px_44px_-30px_rgba(20,43,35,0.7)] backdrop-blur">
						<div className="h-1.5 overflow-hidden rounded-full bg-[#e5eadc]">
							<div className="molstar-loading-bar h-full w-1/2 rounded-full bg-[#dce846]" />
						</div>
						<p className="mt-2">Syncing workspace ledger…</p>
					</div>
				) : null}
			</section>
			<aside className="min-h-0 overflow-y-auto border-[#e5e2d9] border-t bg-[#fbfaf6] lg:border-t-0 lg:border-l">
				<JourneyPanel
					activeRunStatus={activeRunStatus}
					artifacts={artifacts.map((artifact) => ({
						id: artifact.id,
						kind: artifact.kind ?? artifact.type,
						name: artifact.name ?? artifact.fileName,
					}))}
					candidateScores={candidateScores}
					candidates={candidates.map((candidate) => ({
						id: candidate.id,
						rank: candidate.rank,
						title: candidate.title,
					}))}
					objective={projectGoal}
				/>
				<RecipeManager
					isDisabled={isRecipeDisabled}
					isSaving={isSavingRecipe}
					onArchive={onArchiveRecipe}
					onCreate={onCreateRecipe}
					onUpdate={onUpdateRecipe}
					recipes={recipes}
				/>
			</aside>
		</main>
	);
}

function toTraceEvent(event: WorkspaceEvent): TraceEvent {
	return {
		displayJson: event.displayJson ?? event.payloadJson ?? {},
		id: event.id,
		rawJson: event.rawJson ?? {},
		sequence: event.sequence,
		summary: event.summary ?? event.detail ?? null,
		title: event.title,
		type: event.type,
	};
}

function toChatMessage(message: WorkspaceChatMessage): ChatMessage {
	return {
		content: message.content ?? message.text ?? "",
		id: message.id,
		role: message.role,
	};
}

function toStageArtifact(
	artifact: WorkspaceArtifact | null,
): StageArtifact | null {
	if (!artifact) {
		return null;
	}

	return {
		id: artifact.id,
		label: artifact.fileName,
		name: artifact.name ?? artifact.fileName,
		url: artifact.sourceUrl ?? artifact.signedUrl,
	};
}

function toStageCandidate(
	candidate: WorkspaceCandidate | null,
): StageCandidate | null {
	if (!candidate) {
		return null;
	}

	return {
		id: candidate.id,
		title: candidate.title,
	};
}
