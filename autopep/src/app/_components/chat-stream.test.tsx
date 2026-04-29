// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatStream } from "./chat-stream";

describe("ChatStream", () => {
	it("renders user, assistant, and tool items", () => {
		render(
			<ChatStream
				emptyHint="Send a message to get started."
				items={[
					{ kind: "user_message", id: "1", content: "hi" },
					{
						kind: "assistant_message",
						id: "2",
						content: "hello",
						streaming: false,
					},
					{
						kind: "tool_call",
						id: "3",
						tool: "rcsb_structure_search",
						status: "completed",
						display: { query: "spike" },
						durationMs: 50,
					},
				]}
			/>,
		);
		expect(screen.getByText("hi")).toBeInTheDocument();
		expect(screen.getByText("hello")).toBeInTheDocument();
		expect(screen.getByText(/rcsb_structure_search/)).toBeInTheDocument();
	});

	it("renders empty hint when there are no items", () => {
		render(<ChatStream emptyHint="Nothing yet." items={[]} />);
		expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
	});
});
