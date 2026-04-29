// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceRail } from "./workspace-rail";

describe("WorkspaceRail", () => {
	it("switches and creates workspaces", () => {
		const onCreateWorkspace = vi.fn();
		const onSelectWorkspace = vi.fn();
		render(
			<WorkspaceRail
				activeWorkspaceId="workspace-1"
				onArchiveWorkspace={vi.fn()}
				onCreateWorkspace={onCreateWorkspace}
				onSelectWorkspace={onSelectWorkspace}
				workspaces={[{ id: "workspace-1", name: "3CL protease" }]}
			/>,
		);

		fireEvent.click(screen.getByLabelText("Create workspace"));
		fireEvent.click(screen.getByLabelText("Open 3CL protease"));

		expect(onCreateWorkspace).toHaveBeenCalledOnce();
		expect(onSelectWorkspace).toHaveBeenCalledWith("workspace-1");
	});
});
