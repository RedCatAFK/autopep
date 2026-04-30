import { describe, expect, it } from "vitest";

import { clampPanelWidth, resizePanelWidth } from "./workspace-shell";

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
});
