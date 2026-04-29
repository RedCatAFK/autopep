import { describe, expect, it } from "vitest";

import { isMeaningfulTraceEvent } from "./event-filters";

describe("isMeaningfulTraceEvent", () => {
	it("hides assistant token deltas", () => {
		expect(isMeaningfulTraceEvent("assistant_token_delta")).toBe(false);
	});

	it("hides assistant_message_started/completed", () => {
		expect(isMeaningfulTraceEvent("assistant_message_started")).toBe(false);
		expect(isMeaningfulTraceEvent("assistant_message_completed")).toBe(false);
	});

	it("hides agent_changed", () => {
		expect(isMeaningfulTraceEvent("agent_changed")).toBe(false);
	});

	it("keeps tool calls", () => {
		expect(isMeaningfulTraceEvent("tool_call_started")).toBe(true);
		expect(isMeaningfulTraceEvent("tool_call_completed")).toBe(true);
	});

	it("keeps artifact and candidate events", () => {
		expect(isMeaningfulTraceEvent("artifact_created")).toBe(true);
		expect(isMeaningfulTraceEvent("candidate_ranked")).toBe(true);
	});
});
