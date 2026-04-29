"use client";

import {
	type ChatContextReference,
	ChatPanel,
	type ChatPanelSendInput,
	type ChatRecipe,
} from "./chat-panel";
import type { StreamItem } from "./chat-stream-item";
import { FilesPanel } from "./files-panel";
import {
	type RecipeInput,
	type RecipeRow,
	RecipesDialog,
} from "./recipes-dialog";
import { type ViewerTab, ViewerTabs } from "./viewer-tabs";
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
	createdAt: string;
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
	runId?: string | null;
	signedUrl: string | null;
	sourceUrl: string | null;
	type: string;
};

export type WorkspaceChatMessage = {
	content?: string;
	createdAt: string;
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

export type WorkspaceFileArtifact = {
	byteSize: number;
	candidateId: string | null;
	fileName: string;
	id: string;
	kind: string;
	runId: string | null;
	signedUrl: string | null;
};

export type WorkspaceRunSummary = {
	id: string;
	startedAt: string;
	status: string;
};

type WorkspaceShellProps = {
	activeArtifactId: string | null;
	activeTabId: string | null;
	activeWorkspaceId: string | null;
	candidateScores: WorkspaceCandidateScore[];
	candidates: WorkspaceCandidate[];
	closeTab: (tabId: string) => void;
	contextReferences: ChatContextReference[];
	fileArtifacts: WorkspaceFileArtifact[];
	isChatDisabled?: boolean;
	isLoadingWorkspace: boolean;
	isRecipesOpen: boolean;
	isSavingRecipe?: boolean;
	isSendingMessage: boolean;
	onArchiveRecipe: (recipeId: string) => void;
	onArchiveWorkspace: (workspaceId: string) => void;
	onCloseRecipes: () => void;
	onCreateRecipe: (input: RecipeInput) => void;
	onCreateWorkspace: () => void;
	onDeleteAttachment?: (artifactId: string) => void;
	onOpenRecipes: () => void;
	onRenameWorkspace?: (workspaceId: string, name: string) => void;
	onSelectWorkspace: (workspaceId: string) => void;
	onSendMessage: (input: ChatPanelSendInput) => void;
	onUpdateRecipe: (input: RecipeInput & { recipeId: string }) => void;
	openArtifactInTab: (artifactId: string) => void;
	openCandidateInTab: (candidateId: string) => void;
	openFileInTab: (artifact: WorkspaceFileArtifact) => void;
	recipes: RecipeRow[];
	runs: WorkspaceRunSummary[];
	setActiveTabId: (tabId: string | null) => void;
	streamItems: StreamItem[];
	tabs: ViewerTab[];
	workspaces: RailWorkspace[];
};

export function WorkspaceShell({
	activeArtifactId,
	activeTabId,
	activeWorkspaceId,
	candidateScores,
	candidates,
	closeTab,
	contextReferences,
	fileArtifacts,
	isChatDisabled = false,
	isLoadingWorkspace,
	isRecipesOpen,
	isSavingRecipe = false,
	isSendingMessage,
	onArchiveRecipe,
	onArchiveWorkspace,
	onCloseRecipes,
	onCreateRecipe,
	onCreateWorkspace,
	onDeleteAttachment,
	onOpenRecipes,
	onRenameWorkspace,
	onSelectWorkspace,
	onSendMessage,
	onUpdateRecipe,
	openArtifactInTab,
	openCandidateInTab,
	openFileInTab,
	recipes,
	runs,
	setActiveTabId,
	streamItems,
	tabs,
	workspaces,
}: WorkspaceShellProps) {
	const chatRecipes: ChatRecipe[] = recipes.map((recipe) => ({
		enabledByDefault: recipe.enabledByDefault,
		id: recipe.id,
		name: recipe.name,
	}));

	const tabCandidates = candidates.map((candidate) => ({
		id: candidate.id,
		method: candidate.method,
		organism: candidate.organism,
		rank: candidate.rank,
		resolutionAngstrom: candidate.resolutionAngstrom,
		title: candidate.title,
	}));

	const fileCandidates = candidates.map((candidate) => ({
		id: candidate.id,
		rank: candidate.rank,
		title: candidate.title,
	}));

	return (
		<main className="grid min-h-[100dvh] grid-cols-1 bg-[#f8f7f2] text-[#17211e] lg:fixed lg:inset-0 lg:min-h-0 lg:grid-cols-[56px_minmax(360px,420px)_minmax(0,1fr)_minmax(260px,300px)] lg:overflow-hidden">
			<WorkspaceRail
				activeWorkspaceId={activeWorkspaceId}
				onArchiveWorkspace={onArchiveWorkspace}
				onCreateWorkspace={onCreateWorkspace}
				onOpenRecipes={onOpenRecipes}
				onRename={onRenameWorkspace}
				onSelectWorkspace={onSelectWorkspace}
				workspaces={workspaces}
			/>
			<ChatPanel
				contextReferences={contextReferences}
				isDisabled={isChatDisabled}
				isSending={isSendingMessage}
				items={streamItems}
				onOpenArtifact={openArtifactInTab}
				onOpenCandidate={openCandidateInTab}
				onSend={onSendMessage}
				recipes={chatRecipes}
			/>
			<div className="relative min-h-0 lg:min-h-0 lg:overflow-hidden">
				{isLoadingWorkspace ? (
					<div className="pointer-events-none absolute inset-x-0 top-0 z-[2] h-0.5 overflow-hidden bg-[#e5eadc]">
						<div className="molstar-loading-bar h-full w-1/3 bg-[#dce846]" />
					</div>
				) : null}
				<ViewerTabs
					activeTabId={activeTabId}
					candidateScores={candidateScores}
					candidates={tabCandidates}
					onClose={closeTab}
					onOpenCandidate={openCandidateInTab}
					onSelect={setActiveTabId}
					tabs={tabs}
				/>
			</div>
			<FilesPanel
				activeArtifactId={activeArtifactId}
				artifacts={fileArtifacts}
				candidates={fileCandidates}
				onDeleteAttachment={onDeleteAttachment}
				onOpenFile={openFileInTab}
				runs={runs}
			/>
			{isRecipesOpen ? (
				<RecipesDialog
					isSaving={isSavingRecipe}
					onArchive={onArchiveRecipe}
					onClose={onCloseRecipes}
					onCreate={onCreateRecipe}
					onUpdate={onUpdateRecipe}
					open
					recipes={recipes}
				/>
			) : null}
		</main>
	);
}
