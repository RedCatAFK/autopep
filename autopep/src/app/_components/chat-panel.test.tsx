// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./chat-panel";
import type { StreamItem } from "./chat-stream-item";

describe("ChatPanel", () => {
	it("shows example goals when there are no stream items", () => {
		render(
			<ChatPanel
				contextReferences={[]}
				isSending={false}
				items={[]}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(
			screen.getByText("Generate a protein that binds to 3CL-protease"),
		).toBeInTheDocument();
	});

	it("renders user, assistant, and tool stream items", () => {
		const items: StreamItem[] = [
			{ kind: "user_message", id: "u1", content: "Hello, autopep" },
			{
				kind: "assistant_message",
				id: "a1",
				content: "Hi! How can I help?",
				streaming: false,
			},
			{
				kind: "tool_call",
				id: "t1",
				tool: "search_pdb",
				status: "completed",
				display: {},
			},
		];

		render(
			<ChatPanel
				contextReferences={[]}
				isSending={false}
				items={items}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(screen.getByText("Hello, autopep")).toBeInTheDocument();
		expect(screen.getByText("Hi! How can I help?")).toBeInTheDocument();
		expect(screen.getByText("search_pdb")).toBeInTheDocument();
		expect(
			screen.queryByText("Generate a protein that binds to 3CL-protease"),
		).not.toBeInTheDocument();
	});

	it("shows the progress statusline while a run is launching", () => {
		render(
			<ChatPanel
				contextReferences={[]}
				isSending
				items={[]}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		const status = screen.getByRole("status");
		expect(status).toHaveTextContent("Starting run");
		expect(status).toHaveAttribute("data-phase", "dispatch");
		expect(screen.queryByTestId("chat-empty-state")).not.toBeInTheDocument();
	});

	it("shows the active tool in the progress statusline", () => {
		const items: StreamItem[] = [
			{ kind: "user_message", id: "u1", content: "Design a binder" },
			{
				kind: "tool_call",
				id: "tool-1",
				tool: "fold_candidate",
				status: "running",
				display: {},
			},
		];

		render(
			<ChatPanel
				contextReferences={[]}
				isSending={false}
				items={items}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		const status = screen.getByRole("status");
		expect(status).toHaveTextContent("fold_candidate");
		expect(status).toHaveTextContent("Calling");
		expect(status).toHaveAttribute("data-phase", "tool");
	});

	it("shows a thinking fallback when the run is active without a running tool", () => {
		const items: StreamItem[] = [
			{ kind: "user_message", id: "u1", content: "Design a binder" },
			{
				kind: "tool_call",
				id: "tool-1",
				tool: "fold_candidate",
				status: "completed",
				display: {},
			},
		];

		render(
			<ChatPanel
				activeRunStatus="running"
				contextReferences={[]}
				isSending={false}
				items={items}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		const status = screen.getByRole("status");
		expect(status).toHaveTextContent("Thinking");
		expect(status).toHaveAttribute("data-phase", "thinking");
	});

	it("hides the progress statusline once the run is no longer active", () => {
		const items: StreamItem[] = [
			{ kind: "user_message", id: "u1", content: "Design a binder" },
			{
				kind: "assistant_message",
				id: "a1",
				content: "Done.",
				streaming: false,
			},
		];

		render(
			<ChatPanel
				activeRunStatus="completed"
				contextReferences={[]}
				isSending={false}
				items={items}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(
			screen.queryByTestId("chat-progress-status"),
		).not.toBeInTheDocument();
	});

	it("sends the prompt with selected context references", () => {
		const onSend = vi.fn();
		render(
			<ChatPanel
				contextReferences={[
					{ id: "ctx-1", label: "6M0J chain A residues 333-527" },
				]}
				isSending={false}
				items={[]}
				onSend={onSend}
				recipes={[{ enabledByDefault: true, id: "recipe-1", name: "3CL prep" }]}
			/>,
		);

		fireEvent.change(screen.getByLabelText("Message Julia"), {
			target: { value: "Explain this region" },
		});
		fireEvent.click(screen.getByLabelText("Send message"));

		expect(onSend).toHaveBeenCalledWith(
			expect.objectContaining({
				contextRefs: ["ctx-1"],
				prompt: "Explain this region",
				recipeRefs: ["recipe-1"],
			}),
		);
	});

	it("removes a selected context reference", () => {
		const onRemoveContextReference = vi.fn();
		render(
			<ChatPanel
				contextReferences={[
					{ id: "ctx-1", label: "6M0J chain A residues 333-527" },
				]}
				isSending={false}
				items={[]}
				onRemoveContextReference={onRemoveContextReference}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		fireEvent.click(
			screen.getByRole("button", {
				name: "Remove 6M0J chain A residues 333-527",
			}),
		);

		expect(onRemoveContextReference).toHaveBeenCalledWith("ctx-1");
	});

	it("disables sending when no workspace is active", () => {
		const onSend = vi.fn();
		render(
			<ChatPanel
				contextReferences={[]}
				isDisabled
				isSending={false}
				items={[]}
				onSend={onSend}
				recipes={[]}
			/>,
		);

		expect(screen.getByLabelText("Message Julia")).toBeDisabled();
		expect(screen.getByLabelText("Send message")).toBeDisabled();
		fireEvent.click(
			screen.getByText("Generate a protein that binds to 3CL-protease"),
		);

		expect(onSend).not.toHaveBeenCalled();
	});
});
