// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ChatStreamItem, type StreamItem } from "./chat-stream-item";

describe("ChatStreamItem", () => {
	it("renders user message text", () => {
		const item: StreamItem = {
			kind: "user_message",
			id: "1",
			content: "hello agent",
		};
		render(<ChatStreamItem item={item} />);
		expect(screen.getByText("hello agent")).toBeInTheDocument();
	});

	it("renders assistant message text", () => {
		const item: StreamItem = {
			kind: "assistant_message",
			id: "2",
			content: "hi there",
			streaming: false,
		};
		render(<ChatStreamItem item={item} />);
		expect(screen.getByText("hi there")).toBeInTheDocument();
	});

	it("renders assistant message markdown", () => {
		const item: StreamItem = {
			kind: "assistant_message",
			id: "markdown",
			content:
				"## Result\n\n- Folded **candidate A**\n- Score: `-9.2 kcal/mol`\n\n[Open PDB](https://example.com)",
			streaming: false,
		};

		render(<ChatStreamItem item={item} />);

		expect(screen.getByRole("heading", { name: "Result" })).toBeInTheDocument();
		expect(screen.getByText("candidate A").tagName).toBe("STRONG");
		expect(screen.getByText("-9.2 kcal/mol").tagName).toBe("CODE");
		expect(screen.getByRole("link", { name: "Open PDB" })).toHaveAttribute(
			"href",
			"https://example.com",
		);
	});

	it("renders tool call collapsed by default and expands on click", async () => {
		const user = userEvent.setup();
		const item: StreamItem = {
			kind: "tool_call",
			id: "3",
			tool: "rcsb_structure_search",
			status: "completed",
			durationMs: 120,
			display: { query: "spike RBD" },
		};
		render(<ChatStreamItem item={item} />);
		expect(screen.getByText(/rcsb_structure_search/i)).toBeInTheDocument();
		expect(screen.queryByText("spike RBD")).not.toBeInTheDocument();
		await user.click(
			screen.getByRole("button", { name: /rcsb_structure_search/i }),
		);
		expect(screen.getByText("spike RBD")).toBeInTheDocument();
	});
});
