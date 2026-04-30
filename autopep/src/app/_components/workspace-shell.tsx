"use client";

import {
	type CSSProperties,
	type KeyboardEvent,
	type PointerEvent,
	useEffect,
	useRef,
	useState,
} from "react";

import {
	type ChatContextReference,
	ChatPanel,
	type ChatPanelSendInput,
	type ChatRecipe,
} from "./chat-panel";
import type { StreamItem } from "./chat-stream-item";
import { FilesPanel } from "./files-panel";
import type { ProteinSelection } from "./molstar-viewer";
import {
	type RecipeInput,
	type RecipeRow,
	RecipesDialog,
} from "./recipes-dialog";
import type { AttachmentChip } from "./use-attachment-upload";
import { type ViewerTab, ViewerTabs } from "./viewer-tabs";
import {
	type RailAccount,
	type RailWorkspace,
	WorkspaceRail,
} from "./workspace-rail";

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
	type?: string;
};

export type WorkspaceRunSummary = {
	id: string;
	startedAt: string;
	status: string;
};

type WorkspaceShellProps = {
	account?: RailAccount;
	activeArtifactId: string | null;
	activeRunStatus?: string | null;
	activeTabId: string | null;
	activeWorkspaceId: string | null;
	chatAttachments?: AttachmentChip[];
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
	onClearChatAttachments?: () => void;
	onCloseRecipes: () => void;
	onCreateRecipe: (input: RecipeInput) => void;
	onCreateWorkspace: () => void;
	onDeleteAttachment?: (artifactId: string) => void;
	onOpenRecipes: () => void;
	onProteinSelection?: (selection: ProteinSelection) => void;
	onRemoveChatAttachment?: (chipId: string) => void;
	onRemoveContextReference?: (referenceId: string) => void;
	onRenameWorkspace?: (workspaceId: string, name: string) => void;
	onSelectWorkspace: (workspaceId: string) => void;
	onSendMessage: (input: ChatPanelSendInput) => void;
	onSignOut?: () => void;
	onUpdateRecipe: (input: RecipeInput & { recipeId: string }) => void;
	onUploadChatAttachments?: (files: File[]) => void;
	openArtifactInTab: (artifactId: string) => void;
	openCandidateInTab: (candidateId: string) => void;
	openFileInTab: (artifact: WorkspaceFileArtifact) => void;
	recipes: RecipeRow[];
	runs: WorkspaceRunSummary[];
	setActiveTabId: (tabId: string | null) => void;
	signingOut?: boolean;
	signOutError?: string | null;
	streamItems: StreamItem[];
	tabs: ViewerTab[];
	workspaces: RailWorkspace[];
};

type ResizablePanel = "chat" | "files";

type PanelWidthConfig = {
	default: number;
	max: number;
	min: number;
};

const PANEL_WIDTHS = {
	chat: { default: 420, max: 640, min: 320 },
	files: { default: 300, max: 560, min: 240 },
} as const satisfies Record<ResizablePanel, PanelWidthConfig>;

export function clampPanelWidth(panel: ResizablePanel, width: number) {
	const config = PANEL_WIDTHS[panel];
	return Math.min(config.max, Math.max(config.min, Math.round(width)));
}

export function resizePanelWidth({
	currentX,
	panel,
	startWidth,
	startX,
}: {
	currentX: number;
	panel: ResizablePanel;
	startWidth: number;
	startX: number;
}) {
	const delta = currentX - startX;
	return clampPanelWidth(
		panel,
		panel === "chat" ? startWidth + delta : startWidth - delta,
	);
}

export function WorkspaceShell({
	account,
	activeArtifactId,
	activeRunStatus = null,
	activeTabId,
	activeWorkspaceId,
	chatAttachments,
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
	onClearChatAttachments,
	onCloseRecipes,
	onCreateRecipe,
	onCreateWorkspace,
	onDeleteAttachment,
	onOpenRecipes,
	onProteinSelection,
	onRemoveChatAttachment,
	onRemoveContextReference,
	onRenameWorkspace,
	onSelectWorkspace,
	onSendMessage,
	onSignOut,
	onUpdateRecipe,
	onUploadChatAttachments,
	openArtifactInTab,
	openCandidateInTab,
	openFileInTab,
	recipes,
	runs,
	setActiveTabId,
	signingOut = false,
	signOutError,
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

	const [chatPanelWidth, setChatPanelWidth] = useState<number>(
		PANEL_WIDTHS.chat.default,
	);
	const [filesPanelWidth, setFilesPanelWidth] = useState<number>(
		PANEL_WIDTHS.files.default,
	);
	const [activeResizePanel, setActiveResizePanel] =
		useState<ResizablePanel | null>(null);
	const resizeState = useRef<{
		panel: ResizablePanel;
		startWidth: number;
		startX: number;
	} | null>(null);

	useEffect(() => {
		if (!activeResizePanel) {
			return;
		}

		const previousCursor = document.body.style.cursor;
		const previousUserSelect = document.body.style.userSelect;
		document.body.style.cursor = "col-resize";
		document.body.style.userSelect = "none";

		return () => {
			document.body.style.cursor = previousCursor;
			document.body.style.userSelect = previousUserSelect;
		};
	}, [activeResizePanel]);

	const updatePanelWidth = (panel: ResizablePanel, width: number) => {
		const nextWidth = clampPanelWidth(panel, width);
		if (panel === "chat") {
			setChatPanelWidth(nextWidth);
			return;
		}
		setFilesPanelWidth(nextWidth);
	};

	const beginPanelResize = (
		panel: ResizablePanel,
		event: PointerEvent<HTMLHRElement>,
	) => {
		if (event.button !== 0) {
			return;
		}
		event.preventDefault();
		event.currentTarget.setPointerCapture(event.pointerId);
		resizeState.current = {
			panel,
			startWidth: panel === "chat" ? chatPanelWidth : filesPanelWidth,
			startX: event.clientX,
		};
		setActiveResizePanel(panel);
	};

	const continuePanelResize = (event: PointerEvent<HTMLHRElement>) => {
		const state = resizeState.current;
		if (!state) {
			return;
		}
		updatePanelWidth(
			state.panel,
			resizePanelWidth({ ...state, currentX: event.clientX }),
		);
	};

	const endPanelResize = (event: PointerEvent<HTMLHRElement>) => {
		if (!resizeState.current) {
			return;
		}
		resizeState.current = null;
		setActiveResizePanel(null);
		if (event.currentTarget.hasPointerCapture(event.pointerId)) {
			event.currentTarget.releasePointerCapture(event.pointerId);
		}
	};

	const handlePanelResizeKey = (
		panel: ResizablePanel,
		event: KeyboardEvent<HTMLHRElement>,
	) => {
		const currentWidth = panel === "chat" ? chatPanelWidth : filesPanelWidth;
		const step = event.shiftKey ? 40 : 16;

		if (event.key === "Home") {
			event.preventDefault();
			updatePanelWidth(panel, PANEL_WIDTHS[panel].min);
			return;
		}
		if (event.key === "End") {
			event.preventDefault();
			updatePanelWidth(panel, PANEL_WIDTHS[panel].max);
			return;
		}
		if (event.key === "ArrowLeft") {
			event.preventDefault();
			updatePanelWidth(
				panel,
				panel === "chat" ? currentWidth - step : currentWidth + step,
			);
			return;
		}
		if (event.key === "ArrowRight") {
			event.preventDefault();
			updatePanelWidth(
				panel,
				panel === "chat" ? currentWidth + step : currentWidth - step,
			);
		}
	};

	const shellStyle = {
		"--chat-panel-width": `${chatPanelWidth}px`,
		"--files-panel-width": `${filesPanelWidth}px`,
	} as CSSProperties;

	return (
		<main
			className="grid min-h-[100dvh] grid-cols-1 bg-[#f8f7f2] text-[#17211e] lg:fixed lg:inset-0 lg:min-h-0 lg:grid-cols-[56px_var(--chat-panel-width)_minmax(0,1fr)_var(--files-panel-width)] lg:overflow-hidden"
			style={shellStyle}
		>
			<WorkspaceRail
				account={account}
				activeWorkspaceId={activeWorkspaceId}
				onArchiveWorkspace={onArchiveWorkspace}
				onCreateWorkspace={onCreateWorkspace}
				onOpenRecipes={onOpenRecipes}
				onRename={onRenameWorkspace}
				onSelectWorkspace={onSelectWorkspace}
				onSignOut={onSignOut}
				signingOut={signingOut}
				signOutError={signOutError}
				workspaces={workspaces}
			/>
			<div className="relative min-h-0">
				<ChatPanel
					activeRunStatus={activeRunStatus}
					attachments={chatAttachments}
					contextReferences={contextReferences}
					isDisabled={isChatDisabled}
					isSending={isSendingMessage}
					items={streamItems}
					onClearAttachments={onClearChatAttachments}
					onOpenArtifact={openArtifactInTab}
					onOpenCandidate={openCandidateInTab}
					onRemoveAttachment={onRemoveChatAttachment}
					onRemoveContextReference={onRemoveContextReference}
					onSend={onSendMessage}
					onUploadAttachments={onUploadChatAttachments}
					recipes={chatRecipes}
				/>
				<PanelResizeHandle
					active={activeResizePanel === "chat"}
					onKeyDown={handlePanelResizeKey}
					onPointerCancel={endPanelResize}
					onPointerDown={beginPanelResize}
					onPointerMove={continuePanelResize}
					onPointerUp={endPanelResize}
					panel="chat"
					placement="right"
					width={chatPanelWidth}
				/>
			</div>
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
					onProteinSelection={onProteinSelection}
					onSelect={setActiveTabId}
					tabs={tabs}
				/>
			</div>
			<div className="relative min-h-0">
				<PanelResizeHandle
					active={activeResizePanel === "files"}
					onKeyDown={handlePanelResizeKey}
					onPointerCancel={endPanelResize}
					onPointerDown={beginPanelResize}
					onPointerMove={continuePanelResize}
					onPointerUp={endPanelResize}
					panel="files"
					placement="left"
					width={filesPanelWidth}
				/>
				<FilesPanel
					activeArtifactId={activeArtifactId}
					artifacts={fileArtifacts}
					candidates={fileCandidates}
					onDeleteAttachment={onDeleteAttachment}
					onOpenFile={openFileInTab}
					runs={runs}
				/>
			</div>
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

function PanelResizeHandle({
	active,
	onKeyDown,
	onPointerCancel,
	onPointerDown,
	onPointerMove,
	onPointerUp,
	panel,
	placement,
	width,
}: {
	active: boolean;
	onKeyDown: (
		panel: ResizablePanel,
		event: KeyboardEvent<HTMLHRElement>,
	) => void;
	onPointerCancel: (event: PointerEvent<HTMLHRElement>) => void;
	onPointerDown: (
		panel: ResizablePanel,
		event: PointerEvent<HTMLHRElement>,
	) => void;
	onPointerMove: (event: PointerEvent<HTMLHRElement>) => void;
	onPointerUp: (event: PointerEvent<HTMLHRElement>) => void;
	panel: ResizablePanel;
	placement: "left" | "right";
	width: number;
}) {
	const config = PANEL_WIDTHS[panel];
	const placementClass = placement === "left" ? "left-[-6px]" : "right-[-6px]";
	const activeClass = active
		? "before:bg-[#a5b51f]"
		: "before:bg-transparent hover:before:bg-[#cbd736] focus-visible:before:bg-[#a5b51f]";

	return (
		<hr
			aria-label={panel === "chat" ? "Resize chat panel" : "Resize files panel"}
			aria-orientation="vertical"
			aria-valuemax={config.max}
			aria-valuemin={config.min}
			aria-valuenow={width}
			aria-valuetext={`${width}px`}
			className={`absolute inset-y-0 z-20 m-0 hidden h-auto w-3 cursor-col-resize touch-none border-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-px before:-translate-x-1/2 before:content-[''] lg:block ${placementClass} ${activeClass}`}
			onKeyDown={(event) => onKeyDown(panel, event)}
			onPointerCancel={onPointerCancel}
			onPointerDown={(event) => onPointerDown(panel, event)}
			onPointerMove={onPointerMove}
			onPointerUp={onPointerUp}
			tabIndex={0}
		/>
	);
}
