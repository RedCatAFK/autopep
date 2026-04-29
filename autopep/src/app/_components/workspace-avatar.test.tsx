// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceAvatar, hashColor, initial } from "./workspace-avatar";

describe("initial", () => {
	it("returns the first uppercase letter", () => {
		expect(initial("design protein binder")).toBe("D");
	});

	it("returns ? for empty", () => {
		expect(initial("")).toBe("?");
	});

	it("skips leading whitespace", () => {
		expect(initial("   alpha")).toBe("A");
	});
});

describe("hashColor", () => {
	it("is deterministic for the same input", () => {
		expect(hashColor("abc")).toBe(hashColor("abc"));
	});

	it("returns one of the palette entries", () => {
		const palette = [
			"#cbd736",
			"#9bb24a",
			"#3f7967",
			"#758236",
			"#a87b3b",
			"#5c8c79",
			"#7e6f37",
			"#4a6b59",
		];
		expect(palette).toContain(hashColor("workspace-1"));
	});
});

describe("WorkspaceAvatar", () => {
	it("renders the first letter and the workspace name", () => {
		render(<WorkspaceAvatar id="ws-1" name="Design protein binder" />);
		expect(screen.getByText("D")).toBeInTheDocument();
	});
});
