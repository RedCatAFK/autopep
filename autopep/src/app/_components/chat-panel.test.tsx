// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./chat-panel";

describe("ChatPanel", () => {
	it("shows example goals when there are no messages", () => {
		render(
			<ChatPanel
				contextReferences={[]}
				events={[]}
				isSending={false}
				messages={[]}
				onSend={vi.fn()}
				recipes={[]}
			/>,
		);

		expect(
			screen.getByText("Generate a protein that binds to 3CL-protease"),
		).toBeInTheDocument();
	});

	it("sends the prompt with selected context references", () => {
		const onSend = vi.fn();
		render(
			<ChatPanel
				contextReferences={[
					{ id: "ctx-1", label: "6M0J chain A residues 333-527" },
				]}
				events={[]}
				isSending={false}
				messages={[]}
				onSend={onSend}
				recipes={[{ enabledByDefault: true, id: "recipe-1", name: "3CL prep" }]}
			/>,
		);

		fireEvent.change(screen.getByLabelText("Message Autopep"), {
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
				events={[]}
				isDisabled
				isSending={false}
				messages={[]}
				onSend={onSend}
				recipes={[]}
			/>,
		);

		expect(screen.getByLabelText("Message Autopep")).toBeDisabled();
		expect(screen.getByLabelText("Send message")).toBeDisabled();
		fireEvent.click(
			screen.getByText("Generate a protein that binds to 3CL-protease"),
		);

		expect(onSend).not.toHaveBeenCalled();
	});
});
