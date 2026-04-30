// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import {
	clampPanelWidth,
	resizePanelWidth,
	WorkspaceShell,
} from "./workspace-shell";

describe("workspace shell panel resizing", () => {
	it("clamps chat and files panel widths", () => {
		expect(clampPanelWidth("chat", 200)).toBe(320);
		expect(clampPanelWidth("chat", 700)).toBe(640);
		expect(clampPanelWidth("files", 180)).toBe(240);
		expect(clampPanelWidth("files", 620)).toBe(560);
	});

	it("expands the chat panel when its right edge moves right", () => {
		expect(
			resizePanelWidth({
				currentX: 150,
				panel: "chat",
				startWidth: 420,
				startX: 100,
			}),
		).toBe(470);
	});

	it("expands the files panel when its left edge moves left", () => {
		expect(
			resizePanelWidth({
				currentX: 540,
				panel: "files",
				startWidth: 300,
				startX: 600,
			}),
		).toBe(360);
	});

	it("keeps semantic resize handles full-height despite hr preflight", () => {
		render(
			createElement(WorkspaceShell, {
				activeArtifactId: null,
				activeTabId: null,
				activeWorkspaceId: null,
				candidateScores: [],
				candidates: [],
				closeTab: vi.fn(),
				contextReferences: [],
				fileArtifacts: [],
				isLoadingWorkspace: false,
				isRecipesOpen: false,
				isSendingMessage: false,
				onArchiveRecipe: vi.fn(),
				onArchiveWorkspace: vi.fn(),
				onCloseRecipes: vi.fn(),
				onCreateRecipe: vi.fn(),
				onCreateWorkspace: vi.fn(),
				onOpenRecipes: vi.fn(),
				onSelectWorkspace: vi.fn(),
				onSendMessage: vi.fn(),
				onUpdateRecipe: vi.fn(),
				openArtifactInTab: vi.fn(),
				openCandidateInTab: vi.fn(),
				openFileInTab: vi.fn(),
				recipes: [],
				runs: [],
				setActiveTabId: vi.fn(),
				streamItems: [],
				tabs: [],
				workspaces: [],
			}),
		);

		expect(screen.getByLabelText("Resize chat panel")).toHaveClass("h-auto");
		expect(screen.getByLabelText("Resize files panel")).toHaveClass("h-auto");
	});
});
