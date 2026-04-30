import { describe, expect, it } from "vitest";
import { eventDisplayLabel, eventTone } from "./run-events";

describe("run event display helpers", () => {
	it("uses a stable tool label", () => {
		expect(eventDisplayLabel("tool_started")).toBe("Tool started");
		expect(eventTone("tool_started")).toBe("info");
	});

	it("marks run errors with an error tone", () => {
		expect(eventDisplayLabel("run_error")).toBe("Run error");
		expect(eventTone("run_error")).toBe("error");
	});

	it("keeps queued, running, and completed labels and tones stable", () => {
		expect(eventDisplayLabel("queued")).toBe("Queued");
		expect(eventTone("queued")).toBe("muted");
		expect(eventDisplayLabel("running")).toBe("Running");
		expect(eventTone("running")).toBe("info");
		expect(eventDisplayLabel("completed")).toBe("Completed");
		expect(eventTone("completed")).toBe("success");
	});
});
