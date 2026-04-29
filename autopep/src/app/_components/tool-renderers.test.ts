import { describe, expect, it } from "vitest";

import { renderToolDisplay } from "./tool-renderers";

describe("renderToolDisplay", () => {
  it("formats rcsb_structure_search args", () => {
    const result = renderToolDisplay("rcsb_structure_search", {
      query: "spike RBD",
      maxResults: 5,
    });
    expect(result.summary).toContain("spike RBD");
    expect(result.fields).toContainEqual(["query", "spike RBD"]);
  });

  it("falls back to JSON for unknown tools", () => {
    const result = renderToolDisplay("mystery_tool", { a: 1, b: "two" });
    expect(result.summary).toBe("mystery_tool");
    expect(result.fields.length).toBeGreaterThan(0);
  });
});
