// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
				onRename={vi.fn()}
				onSelectWorkspace={onSelectWorkspace}
				workspaces={[{ id: "workspace-1", name: "3CL protease" }]}
			/>,
		);

		fireEvent.click(screen.getByLabelText("Create workspace"));
		fireEvent.click(screen.getByLabelText("Open 3CL protease"));

		expect(onCreateWorkspace).toHaveBeenCalledOnce();
		expect(onSelectWorkspace).toHaveBeenCalledWith("workspace-1");
	});

	it("renames a workspace via the kebab menu", async () => {
		const user = userEvent.setup();
		const onRename = vi.fn();
		render(
			<WorkspaceRail
				activeWorkspaceId="ws-1"
				onArchiveWorkspace={vi.fn()}
				onCreateWorkspace={vi.fn()}
				onRename={onRename}
				onSelectWorkspace={vi.fn()}
				workspaces={[{ id: "ws-1", name: "Spike RBD design" }]}
			/>,
		);

		await user.click(
			screen.getByRole("button", {
				name: /more options for spike rbd design/i,
			}),
		);
		await user.click(screen.getByRole("menuitem", { name: /rename/i }));
		const input = screen.getByDisplayValue("Spike RBD design");
		await user.clear(input);
		await user.type(input, "Updated name{Enter}");

		expect(onRename).toHaveBeenCalledWith("ws-1", "Updated name");
	});

	it("archives a workspace via the kebab menu", async () => {
		const user = userEvent.setup();
		const onArchiveWorkspace = vi.fn();
		render(
			<WorkspaceRail
				activeWorkspaceId="ws-1"
				onArchiveWorkspace={onArchiveWorkspace}
				onCreateWorkspace={vi.fn()}
				onRename={vi.fn()}
				onSelectWorkspace={vi.fn()}
				workspaces={[{ id: "ws-1", name: "Spike RBD design" }]}
			/>,
		);

		await user.click(
			screen.getByRole("button", {
				name: /more options for spike rbd design/i,
			}),
		);
		await user.click(screen.getByRole("menuitem", { name: /archive/i }));

		expect(onArchiveWorkspace).toHaveBeenCalledWith("ws-1");
	});

	it("cancels rename when Escape is pressed", async () => {
		const user = userEvent.setup();
		const onRename = vi.fn();
		render(
			<WorkspaceRail
				activeWorkspaceId="ws-1"
				onArchiveWorkspace={vi.fn()}
				onCreateWorkspace={vi.fn()}
				onRename={onRename}
				onSelectWorkspace={vi.fn()}
				workspaces={[{ id: "ws-1", name: "Spike RBD design" }]}
			/>,
		);

		await user.click(
			screen.getByRole("button", {
				name: /more options for spike rbd design/i,
			}),
		);
		await user.click(screen.getByRole("menuitem", { name: /rename/i }));
		const input = screen.getByDisplayValue("Spike RBD design");
		await user.type(input, "{Escape}");

		expect(onRename).not.toHaveBeenCalled();
	});
});
