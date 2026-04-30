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

		expect(screen.getByRole("status")).toHaveTextContent("launch run");
		expect(screen.getByRole("status")).toHaveTextContent(
			"waiting for event stream",
		);
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

		expect(screen.getByRole("status")).toHaveTextContent("fold_candidate");
		expect(screen.getByRole("status")).toHaveTextContent("running tool call");
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
