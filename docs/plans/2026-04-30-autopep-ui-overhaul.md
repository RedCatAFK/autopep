# Autopep UI Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current 4-column workspace shell with a phylo.bio-style 3-column layout, fold the run-trace into an inline streaming chat (Cursor/Codex/Claude Code style), promote artifacts into a right-rail file explorer with a tabbed middle viewer, move recipes into a dialog, fix the flashing "Syncing workspace ledger" loader, wire up the paperclip for real PDB/CIF attachments, and auto-name workspaces from the first prompt via a small AI call. End with a full end-to-end validation against prod.

**Architecture:**

- Frontend: 3-column shell — left workspace rail (56px) / chat (~400px) / tabbed viewer (flex) / files (~280px). Chat fuses messages and tool/sandbox/artifact cards into one inline stream. Middle viewer auto-pins a `Candidates` tab when ranked candidates exist, plus user-opened file tabs (molstar for `.cif`/`.pdb`, text preview for textual files, skeleton for unsupported types). Right rail is a hybrid file tree (`Attachments/`, `Candidates/`, `Runs/`).
- Streaming pipeline: assistant token deltas no longer hit Postgres. The Modal worker exposes a per-run SSE endpoint that pushes deltas straight to the browser; on `response.completed` the runner writes a single `messages` row for replay. The persisted ledger keeps only meaningful events (tool calls, sandbox commands, artifacts, candidates, run lifecycle). Frontend uses cursor-based incremental polling (`since_sequence`) for the ledger and EventSource for live tokens.
- Attachments: client → presigned R2 PUT → confirm mutation → artifact row with `kind: 'attachment'` → context_reference auto-created. Modal runner copies attachments into the workspace volume before invoking the agent.
- Workspace naming: `+` button defers DB writes; the first user message creates the workspace + thread + run, then a non-blocking gpt-5.4-mini call generates a 3–6 word title.

**Tech Stack:** Next.js 16 App Router, tRPC v11, Drizzle (Postgres on Neon), Better Auth, Modal (Python agent worker + FastAPI endpoints), Cloudflare R2, Vitest, Biome, oxlint, Tailwind v4, Mol* viewer, Phosphor icons. AI calls via the existing `OPENAI_API_KEY` (model `gpt-5.4-mini` for naming).

**Working directory rules:**

- All `bun`/`pnpm`/`npm`/`vitest`/`drizzle-kit` commands run from `autopep/` (the Next.js app).
- All `modal` commands run from the repo root (`/Users/pentest-duck/Desktop/autopep`).
- All `git` commands run from the repo root.
- The codebase prefers `bun` (per `package.json` scripts); use `bun run <script>` if `bun` is installed, otherwise `pnpm run <script>`.

**Test conventions:**

- Component tests live next to the component (`*.test.tsx`).
- Server tests live next to the module (`*.test.ts`).
- Use `@testing-library/react` for component tests.
- Vitest config already exists; just add new test files. Run a single file with `bun run test src/path/to/file.test.tsx` (vitest auto-resolves the path).

**Commit cadence:** one commit per task. Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`). Co-author each commit with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

**Prod policy (per the user):** zero users so far, so push schema migrations directly to prod and redeploy Modal/Vercel as needed. Do not skip migrations — generate them with `drizzle-kit generate` and apply with `drizzle-kit migrate`.

---

## Phase 0 — Quick wins (no architecture changes)

### Task 0.1: Stop "Syncing workspace ledger" from flashing every 2s

**Files:**

- Modify: `autopep/src/app/_components/autopep-workspace.tsx:285-290`
- Test: `autopep/src/app/_components/autopep-workspace.test.tsx` (new — only if absent)

**Root cause:** `isLoadingWorkspace` includes `isFetching`, which flips true on every 2s `refetchInterval` poll while a run is active.

**Step 1: Write the failing test**

Add to `autopep/src/app/_components/autopep-workspace.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";

import { computeIsLoadingWorkspace } from "./autopep-workspace";

describe("computeIsLoadingWorkspace", () => {
  it("returns true on the very first mount", () => {
    expect(
      computeIsLoadingWorkspace({
        latestIsLoading: true,
        latestIsFetching: true,
        selectedIsLoading: false,
        selectedIsFetching: false,
      }),
    ).toBe(true);
  });

  it("returns false during background polling", () => {
    expect(
      computeIsLoadingWorkspace({
        latestIsLoading: false,
        latestIsFetching: true,
        selectedIsLoading: false,
        selectedIsFetching: true,
      }),
    ).toBe(false);
  });
});
```

**Step 2: Run test (should fail)**

```
cd autopep && bun run test src/app/_components/autopep-workspace.test.tsx
```

Expected: FAIL — `computeIsLoadingWorkspace is not a function`.

**Step 3: Implement**

In `autopep/src/app/_components/autopep-workspace.tsx`, add and export the helper above the component:

```tsx
export type IsLoadingWorkspaceArgs = {
  latestIsLoading: boolean;
  latestIsFetching: boolean;
  selectedIsLoading: boolean;
  selectedIsFetching: boolean;
};

export const computeIsLoadingWorkspace = ({
  latestIsLoading,
  selectedIsLoading,
}: IsLoadingWorkspaceArgs) => latestIsLoading || selectedIsLoading;
```

Then change line 285-290 to:

```tsx
isLoadingWorkspace={computeIsLoadingWorkspace({
  latestIsLoading: latestWorkspace.isLoading,
  latestIsFetching: latestWorkspace.isFetching,
  selectedIsLoading: selectedWorkspace.isLoading,
  selectedIsFetching: selectedWorkspace.isFetching,
})}
```

**Step 4: Verify pass**

```
cd autopep && bun run test src/app/_components/autopep-workspace.test.tsx
```

Expected: PASS.

**Step 5: Commit**

```
git add autopep/src/app/_components/autopep-workspace.tsx autopep/src/app/_components/autopep-workspace.test.tsx
git commit -m "fix: stop ledger loader from flashing during background polling"
```

---

### Task 0.2: Strip panel headings + descriptions

**Files:**

- Modify: `autopep/src/app/_components/chat-panel.tsx:90-99` (drop `<header>` block)
- Modify: `autopep/src/app/_components/chat-panel.tsx:139` (drop "Run Trace · 115 events" subheader)
- Modify: `autopep/src/app/_components/journey-panel.tsx:54-62` (drop "DESIGN JOURNEY / One-loop screen / objective" header — replaced wholesale in Phase 1)
- Modify: `autopep/src/app/_components/recipe-manager.tsx:108-113` (drop "RECIPES / Run instructions" header)
- Modify: `autopep/src/app/_components/workspace-shell.tsx` (remove the molstar floating placeholder header text — see Task 0.3)

For Phase 0, the goal is to trim. We keep tests minimal here because Phase 1 rewrites these components.

**Step 1: Edit `chat-panel.tsx`**

Replace lines 90–99:

```tsx
{!hasMessages ? null : null}
```

with: delete the entire `<header>` block. The panel renders without a heading.

Replace lines 137–143 (the "Run Trace · N events" sub-heading):

```tsx
<div className="mb-2 flex items-center justify-between gap-3">
  <p className="font-medium text-[#3c4741] text-sm">Run Trace</p>
  <p className="font-mono text-[#747b74] text-xs tabular-nums">
    {events.length} event{events.length === 1 ? "" : "s"}
  </p>
</div>
```

with: nothing (delete). The trace still renders below; just no heading.

**Step 2: Edit `recipe-manager.tsx`**

Delete lines 108–113 (the `<div className="flex items-start justify-between gap-3">…</div>` block containing "RECIPES" + "Run instructions"). Keep the `<button aria-label="Create recipe">` but move it above the chip list as a flat button.

**Step 3: Edit `journey-panel.tsx`**

Delete lines 54–66 (the eyebrow + h2 + objective + tree-structure icon). The panel keeps the milestones list and per-candidate cards. (Phase 1 deletes the panel entirely, but trimming first keeps the diff legible.)

**Step 4: Verify build + screenshot**

```
cd autopep && bun run typecheck && bun run check
```

Expected: pass with no new errors.

Manually skim localhost:3000 to confirm panels still render.

**Step 5: Commit**

```
git add autopep/src/app/_components/chat-panel.tsx autopep/src/app/_components/recipe-manager.tsx autopep/src/app/_components/journey-panel.tsx
git commit -m "refactor: drop panel eyebrow and description copy"
```

---

### Task 0.3: Remove molstar placeholder eyebrow + orbiting dots

**Files:**

- Modify: `autopep/src/app/_components/molstar-stage.tsx`

**What to remove:**

- The "MOLECULAR STAGE" eyebrow.
- The "Start with a prepared structure" h2.
- The "Autopep will place the selected CIF here…" description.
- The decorative orbiting-dot SVG/element when no structure is loaded.

The empty-state collapses to a compact placeholder ("Select a candidate or open a `.cif` file."). Phase 1 later replaces this with the tabbed viewer empty state.

**Step 1: Identify the markup**

Open `autopep/src/app/_components/molstar-stage.tsx`. Find the empty/placeholder branch and the static header copy.

**Step 2: Edit**

Replace the empty-state block with:

```tsx
<div className="flex h-full items-center justify-center text-sm text-[#7a817a]">
  Select a candidate or open a structure file.
</div>
```

Delete the orbiting-dot element entirely (likely a `<div>` with `animate-` classes or an inline SVG — search for `orbit` / `animate-spin` / `dashed` in the file).

**Step 3: Verify**

```
cd autopep && bun run typecheck
```

Expected: pass.

**Step 4: Commit**

```
git add autopep/src/app/_components/molstar-stage.tsx
git commit -m "refactor: simplify molstar empty state"
```

---

### Task 0.4: Better workspace tile (single-letter avatar + tooltip + hash color)

**Files:**

- Create: `autopep/src/app/_components/workspace-avatar.tsx`
- Create: `autopep/src/app/_components/workspace-avatar.test.tsx`
- Modify: `autopep/src/app/_components/workspace-rail.tsx:60` (replace the `slice(0, 2).toUpperCase()` initials)

**Step 1: Write failing tests** (`workspace-avatar.test.tsx`):

```tsx
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
```

**Step 2: Run tests (fail)**

```
cd autopep && bun run test src/app/_components/workspace-avatar.test.tsx
```

Expected: FAIL — module not found.

**Step 3: Implement** (`workspace-avatar.tsx`):

```tsx
"use client";

const PALETTE = [
  "#cbd736",
  "#9bb24a",
  "#3f7967",
  "#758236",
  "#a87b3b",
  "#5c8c79",
  "#7e6f37",
  "#4a6b59",
] as const;

export const initial = (name: string) => {
  const trimmed = name.trim();
  if (!trimmed) {
    return "?";
  }
  return trimmed.charAt(0).toUpperCase();
};

export const hashColor = (id: string) => {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length] ?? PALETTE[0];
};

type WorkspaceAvatarProps = {
  active?: boolean;
  id: string;
  name: string;
};

export function WorkspaceAvatar({ active = false, id, name }: WorkspaceAvatarProps) {
  return (
    <span
      aria-hidden="true"
      className={`flex size-9 items-center justify-center rounded-md font-semibold text-[15px] text-[#1d342e] ${
        active ? "ring-2 ring-[#cbd736] ring-offset-1 ring-offset-[#fbfaf6]" : ""
      }`}
      style={{ backgroundColor: hashColor(id) }}
    >
      {initial(name)}
    </span>
  );
}
```

**Step 4: Wire into the rail.** In `workspace-rail.tsx:60`, replace:

```tsx
{workspace.name.slice(0, 2).toUpperCase()}
```

with:

```tsx
<WorkspaceAvatar id={workspace.id} name={workspace.name} active={active} />
```

Add the import. Wrap the button in a relative container that already exists; on hover, render a custom tooltip (built into the rail in Task 0.5).

**Step 5: Verify**

```
cd autopep && bun run test src/app/_components/workspace-avatar.test.tsx && bun run typecheck
```

Expected: pass.

**Step 6: Commit**

```
git add autopep/src/app/_components/workspace-avatar.tsx autopep/src/app/_components/workspace-avatar.test.tsx autopep/src/app/_components/workspace-rail.tsx
git commit -m "feat: single-letter workspace avatar with hashed color"
```

---

### Task 0.5: Custom hover tooltip on workspace tiles

**Files:**

- Create: `autopep/src/app/_components/hover-tooltip.tsx`
- Create: `autopep/src/app/_components/hover-tooltip.test.tsx`
- Modify: `autopep/src/app/_components/workspace-rail.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";

import { HoverTooltip } from "./hover-tooltip";

describe("HoverTooltip", () => {
  it("shows the label when the trigger is hovered", async () => {
    const user = userEvent.setup();
    render(
      <HoverTooltip label="Full workspace name">
        <button type="button">trigger</button>
      </HoverTooltip>,
    );

    await user.hover(screen.getByRole("button", { name: "trigger" }));
    expect(await screen.findByText("Full workspace name")).toBeInTheDocument();
  });
});
```

**Step 2: Run (fail)**

```
cd autopep && bun run test src/app/_components/hover-tooltip.test.tsx
```

**Step 3: Implement** (`hover-tooltip.tsx`):

```tsx
"use client";

import { useState, type ReactNode } from "react";

type HoverTooltipProps = {
  children: ReactNode;
  label: string;
  side?: "right" | "top" | "bottom";
};

export function HoverTooltip({ children, label, side = "right" }: HoverTooltipProps) {
  const [open, setOpen] = useState(false);

  return (
    <span
      className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open ? (
        <span
          className={`pointer-events-none absolute z-20 whitespace-nowrap rounded-md bg-[#17211e] px-2 py-1 text-[#fffef9] text-xs shadow-lg ${
            side === "right" ? "left-full top-1/2 ml-2 -translate-y-1/2" : ""
          } ${side === "top" ? "left-1/2 bottom-full mb-2 -translate-x-1/2" : ""} ${
            side === "bottom" ? "left-1/2 top-full mt-2 -translate-x-1/2" : ""
          }`}
          role="tooltip"
        >
          {label}
        </span>
      ) : null}
    </span>
  );
}
```

**Step 4: Wire in the rail.** Wrap each workspace tile button with `<HoverTooltip label={workspace.name}>…</HoverTooltip>`.

**Step 5: Verify**

```
cd autopep && bun run test src/app/_components/hover-tooltip.test.tsx
```

**Step 6: Commit**

```
git add autopep/src/app/_components/hover-tooltip.tsx autopep/src/app/_components/hover-tooltip.test.tsx autopep/src/app/_components/workspace-rail.tsx
git commit -m "feat: custom tooltip on workspace rail tiles"
```

---

### Task 0.6: Hide diagnostic events from the existing trace list

Stopgap until Phase 1 builds the proper inline stream — at minimum the user shouldn't see 115 trace cards on a normal run.

**Files:**

- Modify: `autopep/src/app/_components/chat-panel.tsx` (filter `events` before mapping at line 144)
- Create: `autopep/src/app/_components/event-filters.ts`
- Create: `autopep/src/app/_components/event-filters.test.ts`

**Step 1: Failing test**

```ts
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
```

**Step 2: Run (fail)**

```
cd autopep && bun run test src/app/_components/event-filters.test.ts
```

**Step 3: Implement** (`event-filters.ts`):

```ts
const HIDDEN = new Set([
  "assistant_message_started",
  "assistant_message_completed",
  "assistant_token_delta",
  "agent_changed",
  "reasoning_step",
]);

export const isMeaningfulTraceEvent = (type: string) => !HIDDEN.has(type);
```

**Step 4: Wire** in `chat-panel.tsx:144`:

```tsx
{events.filter((event) => isMeaningfulTraceEvent(event.type)).map(...)}
```

**Step 5: Verify**

```
cd autopep && bun run test src/app/_components/event-filters.test.ts && bun run typecheck
```

**Step 6: Commit**

```
git add autopep/src/app/_components/event-filters.ts autopep/src/app/_components/event-filters.test.ts autopep/src/app/_components/chat-panel.tsx
git commit -m "fix: hide diagnostic stream events from run trace"
```

---

### Task 0.7: Phase 0 smoke check via /agent-browser

**Step 1:** Start the dev server.

```
cd autopep && bun run dev &
```

Wait for "Ready in" log (≈3–5s).

**Step 2:** Use the Playwright MCP (or `/agent-browser`) to:

- Navigate to `http://localhost:3000`.
- Confirm there is no "Syncing workspace ledger" floating bar after the first 5 seconds.
- Hover a workspace tile, confirm the tooltip shows the full workspace name.
- Confirm panel headings are gone (no "AGENT WORKSPACE / Ask Autopep / Use the chat as the control surface" copy).
- Send a short prompt and confirm the trace no longer shows 100+ `assistant_token_delta` rows (should be empty or just the meaningful tool/artifact events).

**Step 3:** Stop the dev server (`fg` then Ctrl-C, or `kill %1`).

No commit; this is a verification gate. Phase 0 ships.

---

## Phase 1 — Layout refactor (3-column shell, ChatStream, ViewerTabs, FilesPanel, RecipesDialog)

This phase is large; split into atomic tasks. **Do not delete `journey-panel.tsx` or `recipe-manager.tsx` yet** — keep them until the new shell renders end-to-end, then delete in Task 1.18.

### Task 1.1: Create `<HoverTooltip>` reuse helper for files (already done in 0.5)

Skip — done. Move on.

### Task 1.2: Tool renderer registry (parsed display for tool calls)

**Files:**

- Create: `autopep/src/app/_components/tool-renderers.ts`
- Create: `autopep/src/app/_components/tool-renderers.test.ts`

**Goal:** map a tool name + `display_json` into a compact summary string and a parsed key/value list. Default fallback prints first 40 lines of the raw JSON.

**Step 1: Failing test**

```ts
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
```

**Step 2: Run (fail)**

```
cd autopep && bun run test src/app/_components/tool-renderers.test.ts
```

**Step 3: Implement**

```ts
type Field = readonly [string, string];

export type ToolRender = {
  fields: Field[];
  summary: string;
};

const KNOWN: Record<string, (display: Record<string, unknown>) => ToolRender> = {
  rcsb_structure_search: (display) => {
    const query = String(display.query ?? "");
    const maxResults = display.maxResults ?? display.max_results ?? "?";
    return {
      summary: query || "rcsb structure search",
      fields: [
        ["query", query],
        ["maxResults", String(maxResults)],
      ],
    };
  },
  pubmed_search: (display) => ({
    summary: String(display.query ?? "pubmed"),
    fields: [["query", String(display.query ?? "")]],
  }),
  biorxiv_search: (display) => ({
    summary: String(display.query ?? "biorxiv"),
    fields: [["query", String(display.query ?? "")]],
  }),
  prepare_structure: (display) => ({
    summary: String(display.candidateId ?? "prepare structure"),
    fields: [["candidateId", String(display.candidateId ?? "")]],
  }),
  fold_structure: (display) => ({
    summary: String(display.method ?? "fold"),
    fields: [["method", String(display.method ?? "")]],
  }),
  score_interaction: (display) => ({
    summary: String(display.scorer ?? "score"),
    fields: [["scorer", String(display.scorer ?? "")]],
  }),
};

const truncate = (value: string, max = 80) =>
  value.length > max ? `${value.slice(0, max - 1)}…` : value;

const fallbackFields = (display: Record<string, unknown>): Field[] =>
  Object.entries(display)
    .slice(0, 8)
    .map(([key, value]) => [key, truncate(JSON.stringify(value))] as const);

export const renderToolDisplay = (
  toolName: string,
  display: Record<string, unknown>,
): ToolRender => {
  const known = KNOWN[toolName];
  if (known) {
    return known(display ?? {});
  }
  return {
    summary: toolName,
    fields: fallbackFields(display ?? {}),
  };
};
```

**Step 4: Verify**

```
cd autopep && bun run test src/app/_components/tool-renderers.test.ts
```

**Step 5: Commit**

```
git add autopep/src/app/_components/tool-renderers.ts autopep/src/app/_components/tool-renderers.test.ts
git commit -m "feat: tool display renderer registry"
```

---

### Task 1.3: `<ChatStreamItem>` — interleaved card component

**Files:**

- Create: `autopep/src/app/_components/chat-stream-item.tsx`
- Create: `autopep/src/app/_components/chat-stream-item.test.tsx`

**Goal:** one component renders any item type (`user_message`, `assistant_message`, `tool_call`, `sandbox_command`, `artifact`, `candidate`) as the right shape. Tool/sandbox/artifact items are collapsible.

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";

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
    await user.click(screen.getByRole("button", { name: /rcsb_structure_search/i }));
    expect(screen.getByText("spike RBD")).toBeInTheDocument();
  });
});
```

**Step 2: Run (fail)**

```
cd autopep && bun run test src/app/_components/chat-stream-item.test.tsx
```

**Step 3: Implement** — see types and JSX in the test. The component switches on `item.kind`. For `tool_call` and `sandbox_command`, use `useState(false)` to toggle expansion and render the tool renderer from Task 1.2. For `artifact`, render filename + size + an `Open in viewer` button (`onOpenArtifact?: (artifactId) => void` prop). For `candidate`, render `#<rank> <title>` chip and an `Open candidate` button.

```tsx
"use client";

import { CaretRight, FileText, Flask } from "@phosphor-icons/react";
import { useState } from "react";

import { renderToolDisplay } from "./tool-renderers";

export type StreamItem =
  | { kind: "user_message"; id: string; content: string }
  | {
      kind: "assistant_message";
      id: string;
      content: string;
      streaming: boolean;
    }
  | {
      kind: "tool_call";
      id: string;
      tool: string;
      status: "running" | "completed" | "failed";
      durationMs?: number;
      display: Record<string, unknown>;
      output?: string;
      error?: string;
    }
  | {
      kind: "sandbox_command";
      id: string;
      command: string;
      status: "running" | "completed" | "failed";
      stdout?: string;
      stderr?: string;
      durationMs?: number;
    }
  | {
      kind: "artifact";
      id: string;
      artifactId: string;
      fileName: string;
      byteSize?: number;
    }
  | {
      kind: "candidate";
      id: string;
      candidateId: string;
      rank: number;
      title: string;
    };

type ChatStreamItemProps = {
  item: StreamItem;
  onOpenArtifact?: (artifactId: string) => void;
  onOpenCandidate?: (candidateId: string) => void;
};

export function ChatStreamItem({
  item,
  onOpenArtifact,
  onOpenCandidate,
}: ChatStreamItemProps) {
  if (item.kind === "user_message") {
    return (
      <div className="ml-8 break-words rounded-md bg-[#edf4ed] px-3 py-2 text-[#24302b] text-sm leading-6">
        {item.content}
      </div>
    );
  }

  if (item.kind === "assistant_message") {
    return (
      <div className="break-words text-[#24302b] text-sm leading-6">
        {item.content}
        {item.streaming ? <span className="ml-0.5 animate-pulse">▍</span> : null}
      </div>
    );
  }

  if (item.kind === "tool_call" || item.kind === "sandbox_command") {
    return <CollapsibleCard item={item} />;
  }

  if (item.kind === "artifact") {
    return (
      <button
        className="flex w-full items-center gap-2 rounded-md border border-[#dedbd2] bg-[#fffef9] px-3 py-2 text-left text-sm transition-colors hover:border-[#cbd736]"
        onClick={() => onOpenArtifact?.(item.artifactId)}
        type="button"
      >
        <FileText aria-hidden="true" size={16} />
        <span className="truncate">{item.fileName}</span>
        {item.byteSize ? (
          <span className="ml-auto text-[#7a817a] text-xs tabular-nums">
            {formatBytes(item.byteSize)}
          </span>
        ) : null}
      </button>
    );
  }

  if (item.kind === "candidate") {
    return (
      <button
        className="flex w-full items-center gap-2 rounded-md border border-[#dedbd2] bg-[#fffef9] px-3 py-2 text-left text-sm transition-colors hover:border-[#cbd736]"
        onClick={() => onOpenCandidate?.(item.candidateId)}
        type="button"
      >
        <Flask aria-hidden="true" size={16} />
        <span className="truncate">
          #{item.rank} {item.title}
        </span>
      </button>
    );
  }

  return null;
}

function CollapsibleCard({
  item,
}: {
  item: Extract<StreamItem, { kind: "tool_call" | "sandbox_command" }>;
}) {
  const [open, setOpen] = useState(false);
  const isFailure = item.status === "failed";
  const summary =
    item.kind === "tool_call"
      ? renderToolDisplay(item.tool, item.display).summary
      : item.command;

  return (
    <article
      className={`overflow-hidden rounded-md border ${
        isFailure ? "border-[#e3b6a8]" : "border-[#dedbd2]"
      } bg-[#fffef9]`}
    >
      <button
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <CaretRight
          aria-hidden="true"
          className={`transition-transform ${open ? "rotate-90" : ""}`}
          size={14}
          weight="bold"
        />
        <span className="font-mono text-[#3c4741] text-xs">
          {item.kind === "tool_call" ? item.tool : "$"}
        </span>
        <span className="min-w-0 flex-1 truncate text-[#26332e] text-sm">
          {summary}
        </span>
        {item.durationMs ? (
          <span className="font-mono text-[#7a817a] text-xs tabular-nums">
            {item.durationMs}ms
          </span>
        ) : null}
        <span
          className={`rounded-md px-1.5 py-0.5 text-[10px] uppercase ${
            isFailure
              ? "bg-[#f5d8cd] text-[#7c2f1c]"
              : item.status === "running"
                ? "bg-[#eaf4cf] text-[#315419]"
                : "bg-[#e8f0e3] text-[#36573b]"
          }`}
        >
          {item.status}
        </span>
      </button>
      {open ? (
        <div className="border-[#dedbd2] border-t bg-[#f7f5ee] p-3 text-xs">
          {item.kind === "tool_call" ? (
            <ToolCallBody item={item} />
          ) : (
            <SandboxBody item={item} />
          )}
        </div>
      ) : null}
    </article>
  );
}

function ToolCallBody({
  item,
}: {
  item: Extract<StreamItem, { kind: "tool_call" }>;
}) {
  const render = renderToolDisplay(item.tool, item.display);
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1">
        {render.fields.map(([key, value]) => (
          <div className="contents" key={key}>
            <dt className="font-mono text-[#7a817a]">{key}</dt>
            <dd className="break-words font-mono text-[#27322f]">{value}</dd>
          </div>
        ))}
      </dl>
      {item.output ? (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fffef9] p-2 font-mono text-[11px] text-[#27322f]">
          {item.output}
        </pre>
      ) : null}
      {item.error ? (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fbe9e1] p-2 font-mono text-[11px] text-[#7c2f1c]">
          {item.error}
        </pre>
      ) : null}
    </div>
  );
}

function SandboxBody({
  item,
}: {
  item: Extract<StreamItem, { kind: "sandbox_command" }>;
}) {
  return (
    <div className="space-y-2">
      <pre className="overflow-x-auto rounded bg-[#fffef9] p-2 font-mono text-[11px] text-[#27322f]">
        $ {item.command}
      </pre>
      {item.stdout ? (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-[#fffef9] p-2 font-mono text-[11px] text-[#27322f]">
          {item.stdout}
        </pre>
      ) : null}
      {item.stderr ? (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fbe9e1] p-2 font-mono text-[11px] text-[#7c2f1c]">
          {item.stderr}
        </pre>
      ) : null}
    </div>
  );
}

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};
```

**Step 4: Verify pass**

```
cd autopep && bun run test src/app/_components/chat-stream-item.test.tsx
```

**Step 5: Commit**

```
git add autopep/src/app/_components/chat-stream-item.tsx autopep/src/app/_components/chat-stream-item.test.tsx
git commit -m "feat: chat stream item component"
```

---

### Task 1.4: `buildStreamItems` — interleaver from messages + events

**Files:**

- Create: `autopep/src/app/_components/build-stream-items.ts`
- Create: `autopep/src/app/_components/build-stream-items.test.ts`

**Goal:** given persisted `messages` (with timestamps) and ledger `events` (with `sequence` + timestamp), return a chronologically-ordered list of `StreamItem`s. Hide diagnostic event types. Pair `tool_call_started` + `tool_call_completed`/`tool_call_failed` into a single item by `display.callId`. Same for sandbox commands.

**Step 1: Failing test**

```ts
import { describe, expect, it } from "vitest";

import { buildStreamItems } from "./build-stream-items";

describe("buildStreamItems", () => {
  it("interleaves messages and tool calls in order", () => {
    const items = buildStreamItems({
      messages: [
        { id: "m1", role: "user", content: "go", createdAt: "2026-04-30T10:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "ok",
          createdAt: "2026-04-30T10:00:05Z",
        },
      ],
      events: [
        {
          id: "e1",
          sequence: 1,
          type: "tool_call_started",
          createdAt: "2026-04-30T10:00:01Z",
          displayJson: { callId: "c1", name: "rcsb_structure_search", args: {} },
        },
        {
          id: "e2",
          sequence: 2,
          type: "tool_call_completed",
          createdAt: "2026-04-30T10:00:02Z",
          displayJson: { callId: "c1", output: "ok" },
        },
      ],
    });

    expect(items.map((item) => item.kind)).toEqual([
      "user_message",
      "tool_call",
      "assistant_message",
    ]);
    const toolCall = items[1];
    if (toolCall.kind !== "tool_call") {
      throw new Error("expected tool_call");
    }
    expect(toolCall.status).toBe("completed");
  });

  it("hides diagnostic events", () => {
    const items = buildStreamItems({
      messages: [],
      events: [
        {
          id: "e1",
          sequence: 1,
          type: "assistant_message_started",
          createdAt: "2026-04-30T10:00:01Z",
          displayJson: {},
        },
      ],
    });
    expect(items).toEqual([]);
  });
});
```

**Step 2: Run (fail)**

```
cd autopep && bun run test src/app/_components/build-stream-items.test.ts
```

**Step 3: Implement** — see `StreamItem` from Task 1.3. Match call-id pairs in a `Map`, fold sandbox stdout/stderr deltas into the parent command, drop unmatched starts at the end if the run is still running (status `running`).

```ts
import type { StreamItem } from "./chat-stream-item";
import { isMeaningfulTraceEvent } from "./event-filters";

type Message = {
  id: string;
  role: string;
  content: string;
  createdAt: string;
};

type Event = {
  id: string;
  sequence: number;
  type: string;
  createdAt: string;
  displayJson: Record<string, unknown>;
};

type BuildArgs = { messages: Message[]; events: Event[] };

const getString = (value: unknown) =>
  typeof value === "string" ? value : undefined;

export const buildStreamItems = ({ messages, events }: BuildArgs): StreamItem[] => {
  const ordered: { ts: number; render: () => StreamItem | null }[] = [];

  for (const message of messages) {
    const ts = Date.parse(message.createdAt);
    ordered.push({
      ts,
      render: () => {
        if (message.role === "user") {
          return {
            kind: "user_message",
            id: message.id,
            content: message.content,
          };
        }
        if (message.role === "assistant") {
          return {
            kind: "assistant_message",
            id: message.id,
            content: message.content,
            streaming: false,
          };
        }
        return null;
      },
    });
  }

  const toolCallStarts = new Map<string, Event>();
  const sandboxStarts = new Map<string, Event>();

  for (const event of events) {
    if (!isMeaningfulTraceEvent(event.type)) continue;

    if (event.type === "tool_call_started") {
      const callId = getString(event.displayJson.callId);
      if (callId) toolCallStarts.set(callId, event);
      continue;
    }

    if (event.type === "tool_call_completed" || event.type === "tool_call_failed") {
      const callId = getString(event.displayJson.callId);
      const start = callId ? toolCallStarts.get(callId) : undefined;
      const ts = Date.parse(start?.createdAt ?? event.createdAt);
      const startedMs = start ? Date.parse(start.createdAt) : ts;
      const endedMs = Date.parse(event.createdAt);
      ordered.push({
        ts,
        render: () => ({
          kind: "tool_call",
          id: event.id,
          tool: String(start?.displayJson.name ?? event.displayJson.name ?? "tool"),
          status: event.type === "tool_call_failed" ? "failed" : "completed",
          durationMs: endedMs - startedMs,
          display: {
            ...(start?.displayJson ?? {}),
            ...(event.displayJson ?? {}),
          },
          output: getString(event.displayJson.output),
          error: getString(event.displayJson.error),
        }),
      });
      if (callId) toolCallStarts.delete(callId);
      continue;
    }

    if (event.type === "sandbox_command_started") {
      const id = getString(event.displayJson.commandId);
      if (id) sandboxStarts.set(id, event);
      continue;
    }

    if (event.type === "sandbox_command_completed") {
      const id = getString(event.displayJson.commandId);
      const start = id ? sandboxStarts.get(id) : undefined;
      const ts = Date.parse(start?.createdAt ?? event.createdAt);
      const startedMs = start ? Date.parse(start.createdAt) : ts;
      const endedMs = Date.parse(event.createdAt);
      ordered.push({
        ts,
        render: () => ({
          kind: "sandbox_command",
          id: event.id,
          command: String(start?.displayJson.command ?? event.displayJson.command ?? ""),
          status:
            getString(event.displayJson.status) === "failed" ? "failed" : "completed",
          stdout: getString(event.displayJson.stdout),
          stderr: getString(event.displayJson.stderr),
          durationMs: endedMs - startedMs,
        }),
      });
      if (id) sandboxStarts.delete(id);
      continue;
    }

    if (event.type === "artifact_created") {
      ordered.push({
        ts: Date.parse(event.createdAt),
        render: () => ({
          kind: "artifact",
          id: event.id,
          artifactId: String(event.displayJson.artifactId ?? ""),
          fileName: String(event.displayJson.fileName ?? "artifact"),
          byteSize:
            typeof event.displayJson.byteSize === "number"
              ? (event.displayJson.byteSize as number)
              : undefined,
        }),
      });
      continue;
    }

    if (event.type === "candidate_ranked") {
      ordered.push({
        ts: Date.parse(event.createdAt),
        render: () => ({
          kind: "candidate",
          id: event.id,
          candidateId: String(event.displayJson.candidateId ?? ""),
          rank: Number(event.displayJson.rank ?? 0),
          title: String(event.displayJson.title ?? "candidate"),
        }),
      });
    }
  }

  // Surface still-running tool calls at their start time.
  for (const start of toolCallStarts.values()) {
    ordered.push({
      ts: Date.parse(start.createdAt),
      render: () => ({
        kind: "tool_call",
        id: start.id,
        tool: String(start.displayJson.name ?? "tool"),
        status: "running",
        display: start.displayJson,
      }),
    });
  }

  return ordered
    .sort((a, b) => a.ts - b.ts)
    .map((entry) => entry.render())
    .filter((value): value is StreamItem => value !== null);
};
```

**Step 4: Verify**

```
cd autopep && bun run test src/app/_components/build-stream-items.test.ts
```

**Step 5: Commit**

```
git add autopep/src/app/_components/build-stream-items.ts autopep/src/app/_components/build-stream-items.test.ts
git commit -m "feat: interleave messages and ledger events into stream items"
```

---

### Task 1.5: Server payload — include `createdAt` on messages and events

The frontend interleaver needs timestamps. Check `src/server/api/routers/workspace.ts`'s `getWorkspace` to ensure `messages` and `events` carry `createdAt`. Also include `runs` (id, startedAt, status) on the payload for the file tree.

**Files:**

- Modify: `autopep/src/server/api/routers/workspace.ts`
- Modify: `autopep/src/server/api/routers/workspace.test.ts`

**Step 1:** Read the current `getWorkspace` shape; add `createdAt: row.createdAt.toISOString()` to messages and events. Add a `runs` field to the result, populated with `agentRuns` rows scoped to the workspace.

**Step 2:** Update test fixture to assert `result.messages[0].createdAt` is a string and `result.runs.length >= 1`.

**Step 3:** Run

```
cd autopep && bun run test src/server/api/routers/workspace.test.ts
```

**Step 4:** Commit

```
git commit -am "feat: include createdAt and runs in workspace payload"
```

---

### Task 1.6: `<ChatStream>` component (replaces inline trace)

**Files:**

- Create: `autopep/src/app/_components/chat-stream.tsx`
- Create: `autopep/src/app/_components/chat-stream.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatStream } from "./chat-stream";

describe("ChatStream", () => {
  it("renders user, assistant, and tool items", () => {
    render(
      <ChatStream
        items={[
          { kind: "user_message", id: "1", content: "hi" },
          { kind: "assistant_message", id: "2", content: "hello", streaming: false },
          {
            kind: "tool_call",
            id: "3",
            tool: "rcsb_structure_search",
            status: "completed",
            display: { query: "spike" },
            durationMs: 50,
          },
        ]}
        emptyHint="Send a message to get started."
      />,
    );
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText(/rcsb_structure_search/)).toBeInTheDocument();
  });

  it("renders empty hint when there are no items", () => {
    render(<ChatStream items={[]} emptyHint="Nothing yet." />);
    expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
  });
});
```

**Step 2: Run (fail)**

**Step 3: Implement**

```tsx
"use client";

import { ChatStreamItem, type StreamItem } from "./chat-stream-item";

type ChatStreamProps = {
  emptyHint?: string;
  items: StreamItem[];
  onOpenArtifact?: (artifactId: string) => void;
  onOpenCandidate?: (candidateId: string) => void;
};

export function ChatStream({
  emptyHint = "No messages yet.",
  items,
  onOpenArtifact,
  onOpenCandidate,
}: ChatStreamProps) {
  if (items.length === 0) {
    return <p className="text-[#7a817a] text-sm">{emptyHint}</p>;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ChatStreamItem
          item={item}
          key={item.id}
          onOpenArtifact={onOpenArtifact}
          onOpenCandidate={onOpenCandidate}
        />
      ))}
    </div>
  );
}
```

**Step 4: Verify**

**Step 5: Commit**

```
git commit -am "feat: chat stream component"
```

---

### Task 1.7: `<ViewerTabs>` — tabbed middle viewer

**Files:**

- Create: `autopep/src/app/_components/viewer-tabs.tsx`
- Create: `autopep/src/app/_components/viewer-tabs.test.tsx`
- Create: `autopep/src/app/_components/file-preview.tsx` (text/image/skeleton renderers)
- Create: `autopep/src/app/_components/candidates-table.tsx`

**Goal:** controlled tab state at the parent level. Tabs:

- `{ kind: 'candidates' }` (auto-pinned, not closable, only present when `candidates.length > 0`)
- `{ kind: 'file', artifactId, fileName, signedUrl }` (closable)

Empty state: "Select a file from the right panel, or wait for the agent to produce candidates."

**Step 1: Failing test (`viewer-tabs.test.tsx`):**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";

import { ViewerTabs, type ViewerTab } from "./viewer-tabs";

describe("ViewerTabs", () => {
  it("renders the empty state", () => {
    render(
      <ViewerTabs
        tabs={[]}
        activeTabId={null}
        onSelect={() => {}}
        onClose={() => {}}
        candidates={[]}
        candidateScores={[]}
      />,
    );
    expect(
      screen.getByText(/select a file from the right panel/i),
    ).toBeInTheDocument();
  });

  it("auto-pins the candidates tab when candidates exist", () => {
    render(
      <ViewerTabs
        tabs={[]}
        activeTabId="candidates"
        onSelect={() => {}}
        onClose={() => {}}
        candidates={[{ id: "c1", rank: 1, title: "spike RBD" }]}
        candidateScores={[]}
      />,
    );
    expect(screen.getByRole("tab", { name: /candidates/i })).toBeInTheDocument();
    expect(screen.getByText(/spike RBD/i)).toBeInTheDocument();
  });

  it("calls onClose when a closable tab's × is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const tabs: ViewerTab[] = [
      {
        kind: "file",
        id: "f1",
        artifactId: "a1",
        fileName: "test.cif",
        signedUrl: "https://example.com/test.cif",
      },
    ];
    render(
      <ViewerTabs
        tabs={tabs}
        activeTabId="f1"
        onSelect={() => {}}
        onClose={onClose}
        candidates={[]}
        candidateScores={[]}
      />,
    );
    await user.click(screen.getByRole("button", { name: /close test\.cif/i }));
    expect(onClose).toHaveBeenCalledWith("f1");
  });
});
```

**Step 2: Run (fail)**

**Step 3: Implement** — controlled component. Renderers (file-preview.tsx) inspect filename extension:

- `.cif | .mmcif | .pdb` → dynamic-import existing `MolstarStage` to keep bundle small.
- text-like → `<pre>` with line numbers.
- image-like → `<img>`.
- else → "No preview available" + Download button (use signedUrl).

`<CandidatesTable>` renders the `candidates` + `candidateScores` props as a sortable table; clicking a row calls `onOpenCandidate(candidateId)` (passed from parent). Use the existing scoring logic from `journey-panel.tsx` (D-SCRIPT, PRODIGY, aggregate, label) lifted into the table.

**Step 4: Verify**

```
cd autopep && bun run test src/app/_components/viewer-tabs.test.tsx
```

**Step 5: Commit**

```
git commit -am "feat: tabbed middle viewer with candidates and file previews"
```

---

### Task 1.8: `<FilesPanel>` — hybrid file tree

**Files:**

- Create: `autopep/src/app/_components/files-panel.tsx`
- Create: `autopep/src/app/_components/files-panel.test.tsx`
- Create: `autopep/src/app/_components/file-tree.ts` (pure grouping logic)
- Create: `autopep/src/app/_components/file-tree.test.ts`

**Step 1: Failing test for grouping** (`file-tree.test.ts`):

```ts
import { describe, expect, it } from "vitest";

import { groupArtifacts } from "./file-tree";

describe("groupArtifacts", () => {
  it("places attachments under Attachments/", () => {
    const groups = groupArtifacts({
      artifacts: [
        {
          id: "a1",
          fileName: "ref.pdb",
          kind: "attachment",
          candidateId: null,
          runId: "r1",
          signedUrl: null,
          byteSize: 1024,
        },
      ],
      candidates: [],
      runs: [],
    });
    expect(groups).toContainEqual(
      expect.objectContaining({
        label: "Attachments",
        files: expect.arrayContaining([
          expect.objectContaining({ fileName: "ref.pdb" }),
        ]),
      }),
    );
  });

  it("groups candidate artifacts under Candidates/<rank> <title>/", () => {
    const groups = groupArtifacts({
      artifacts: [
        {
          id: "a1",
          fileName: "prepared.cif",
          kind: "cif",
          candidateId: "c1",
          runId: "r1",
          signedUrl: null,
          byteSize: 0,
        },
      ],
      candidates: [{ id: "c1", rank: 1, title: "spike RBD" }],
      runs: [],
    });
    const cand = groups.find((group) => group.kind === "candidate");
    expect(cand?.label).toBe("#1 spike RBD");
  });
});
```

**Step 2: Run (fail)**

**Step 3: Implement** — pure function grouping.

```ts
type ArtifactInput = {
  id: string;
  fileName: string;
  kind: string;
  candidateId: string | null;
  runId: string | null;
  signedUrl: string | null;
  byteSize: number;
};

export type FileGroup =
  | { kind: "attachments"; label: "Attachments"; files: ArtifactInput[] }
  | {
      kind: "candidate";
      label: string;
      candidateId: string;
      files: ArtifactInput[];
    }
  | {
      kind: "run";
      label: string;
      runId: string;
      startedAt: string;
      status: string;
      files: ArtifactInput[];
    };

type GroupArgs = {
  artifacts: ArtifactInput[];
  candidates: { id: string; rank: number; title: string }[];
  runs: { id: string; startedAt: string; status: string }[];
};

export const groupArtifacts = ({
  artifacts,
  candidates,
  runs,
}: GroupArgs): FileGroup[] => {
  const attachments = artifacts.filter((a) => a.kind === "attachment");
  const groups: FileGroup[] = [];

  groups.push({ kind: "attachments", label: "Attachments", files: attachments });

  const candidateById = new Map(candidates.map((c) => [c.id, c]));
  const byCandidate = new Map<string, ArtifactInput[]>();
  for (const artifact of artifacts) {
    if (artifact.kind === "attachment" || !artifact.candidateId) continue;
    const list = byCandidate.get(artifact.candidateId) ?? [];
    list.push(artifact);
    byCandidate.set(artifact.candidateId, list);
  }
  for (const candidate of candidates) {
    const files = byCandidate.get(candidate.id) ?? [];
    if (files.length === 0) continue;
    groups.push({
      kind: "candidate",
      label: `#${candidate.rank} ${candidate.title}`,
      candidateId: candidate.id,
      files,
    });
  }

  const byRun = new Map<string, ArtifactInput[]>();
  for (const artifact of artifacts) {
    if (artifact.kind === "attachment" || artifact.candidateId) continue;
    if (!artifact.runId) continue;
    const list = byRun.get(artifact.runId) ?? [];
    list.push(artifact);
    byRun.set(artifact.runId, list);
  }
  for (const run of runs) {
    const files = byRun.get(run.id) ?? [];
    if (files.length === 0) continue;
    groups.push({
      kind: "run",
      label: `run · ${new Date(run.startedAt).toLocaleString()}`,
      runId: run.id,
      startedAt: run.startedAt,
      status: run.status,
      files,
    });
  }

  return groups;
};
```

**Step 4: `<FilesPanel>` component** — renders groups, search input filters by filename, click row → `onOpenFile(artifact)`. Default-expanded for attachments and candidates; default-collapsed for runs. Use `<HoverTooltip>` on long filenames.

**Step 5: Verify**

```
cd autopep && bun run test src/app/_components/file-tree.test.ts src/app/_components/files-panel.test.tsx
```

**Step 6: Commit**

```
git commit -am "feat: hybrid file tree panel"
```

---

### Task 1.9: `<RecipesDialog>` — modal CRUD UI

**Files:**

- Create: `autopep/src/app/_components/recipes-dialog.tsx`
- Create: `autopep/src/app/_components/recipes-dialog.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { RecipesDialog } from "./recipes-dialog";

const recipes = [
  {
    id: "r1",
    name: "3CL Protease Prep",
    description: null,
    bodyMarkdown: "Always preserve source artifacts.",
    enabledByDefault: true,
  },
];

describe("RecipesDialog", () => {
  it("renders recipe list and editor", async () => {
    render(
      <RecipesDialog
        open
        recipes={recipes}
        onClose={() => {}}
        onCreate={() => {}}
        onUpdate={() => {}}
        onArchive={() => {}}
        isSaving={false}
      />,
    );
    expect(screen.getByText("3CL Protease Prep")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/preserve source artifacts/i)).toBeInTheDocument();
  });

  it("creates a new recipe via the + New button", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(
      <RecipesDialog
        open
        recipes={recipes}
        onClose={() => {}}
        onCreate={onCreate}
        onUpdate={() => {}}
        onArchive={() => {}}
        isSaving={false}
      />,
    );
    await user.click(screen.getByRole("button", { name: /new recipe/i }));
    await user.type(screen.getByLabelText(/name/i), "New flow");
    await user.type(screen.getByLabelText(/instructions/i), "Do thing.");
    await user.click(screen.getByRole("button", { name: /create recipe/i }));
    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "New flow", bodyMarkdown: "Do thing." }),
    );
  });
});
```

**Step 2: Run (fail)**

**Step 3: Implement** — two-pane layout: left list + search + `+ New`; right form (name, description, body, enabled-by-default toggle, Save/Archive). Esc closes. Lift the validation/save logic from existing `recipe-manager.tsx`.

**Step 4: Verify**

**Step 5: Commit**

```
git commit -am "feat: recipes dialog with full CRUD"
```

---

### Task 1.10: New `<WorkspaceShell>` 3-column grid

**Files:**

- Modify: `autopep/src/app/_components/workspace-shell.tsx` (rewrite layout)
- Modify: `autopep/src/app/_components/autopep-workspace.tsx` (pass new props, manage tab state, manage recipes-dialog state)

**Step 1: Backup the current layout** by reading the file. Then replace the JSX in the `WorkspaceShell` return with:

```tsx
<main className="grid min-h-[100dvh] grid-cols-1 bg-[#f8f7f2] text-[#17211e] lg:fixed lg:inset-0 lg:min-h-0 lg:grid-cols-[56px_minmax(360px,420px)_minmax(0,1fr)_minmax(260px,300px)] lg:overflow-hidden">
  <WorkspaceRail
    activeWorkspaceId={activeWorkspaceId}
    onArchiveWorkspace={onArchiveWorkspace}
    onCreateWorkspace={onCreateWorkspace}
    onOpenRecipes={onOpenRecipes}
    onSelectWorkspace={onSelectWorkspace}
    workspaces={workspaces}
  />
  <ChatPanel
    contextReferences={contextReferences}
    isDisabled={isChatDisabled}
    isSending={isSendingMessage}
    items={streamItems}
    onSend={onSendMessage}
    onOpenArtifact={openArtifactInTab}
    onOpenCandidate={openCandidateInTab}
    recipes={chatRecipes}
  />
  <ViewerTabs
    tabs={tabs}
    activeTabId={activeTabId}
    candidates={candidates}
    candidateScores={candidateScores}
    onSelect={setActiveTabId}
    onClose={closeTab}
  />
  <FilesPanel
    groups={fileGroups}
    activeArtifactId={activeArtifactId}
    onOpenFile={openFileInTab}
    onDeleteAttachment={onDeleteAttachment}
  />
  {isRecipesOpen ? (
    <RecipesDialog
      open
      recipes={recipes}
      onClose={() => setIsRecipesOpen(false)}
      onCreate={onCreateRecipe}
      onUpdate={onUpdateRecipe}
      onArchive={onArchiveRecipe}
      isSaving={isSavingRecipe}
    />
  ) : null}
</main>
```

`autopep-workspace.tsx` becomes the orchestrator: derive `streamItems` from `messages + events` via `buildStreamItems`, derive `fileGroups` via `groupArtifacts`, manage `tabs`/`activeTabId`/`isRecipesOpen` state.

**Step 2:** Update `WorkspaceShell` props type and component body. Drop `JourneyPanel` and the inline `RecipeManager` usage.

**Step 3: Verify build**

```
cd autopep && bun run typecheck && bun run check
```

**Step 4: Commit**

```
git commit -am "refactor: 3-column workspace shell with tabbed viewer and files panel"
```

---

### Task 1.11: Refit `<ChatPanel>` to use `<ChatStream>` and accept stream items

**Files:**

- Modify: `autopep/src/app/_components/chat-panel.tsx`
- Modify: `autopep/src/app/_components/chat-panel.test.tsx`

**Step 1:** Change `ChatPanelProps` — replace `events: TraceEvent[]` and `messages: ChatMessage[]` with `items: StreamItem[]`. Drop the "Run Trace" subsection entirely. Render `<ChatStream items={items} />` above the composer. Keep the existing composer (textarea, attach, send) but feed it stream item callbacks from props.

**Step 2:** Update existing tests to pass `items` and assert that user/assistant/tool items render.

**Step 3:** Verify

```
cd autopep && bun run test src/app/_components/chat-panel.test.tsx
```

**Step 4:** Commit

```
git commit -am "refactor: chat panel renders inline stream items"
```

---

### Task 1.12: Workspace rail kebab menu (Rename / Archive)

**Files:**

- Modify: `autopep/src/app/_components/workspace-rail.tsx`
- Modify: `autopep/src/app/_components/workspace-rail.test.tsx`
- Modify: `autopep/src/server/api/routers/workspace.ts` — add `renameWorkspace({ workspaceId, name })` mutation
- Modify: `autopep/src/server/api/routers/workspace.test.ts`

**Step 1: Failing server test** — assert `renameWorkspace` updates `workspaces.name`.

**Step 2: Implement** mutation in router. Authorize: workspace must belong to caller.

**Step 3:** Failing UI test — kebab on hover, click → `Rename` opens an inline input over the tile, submit calls `onRename`. Implement.

**Step 4: Wire** mutation into `autopep-workspace.tsx`.

**Step 5: Verify + commit**

```
git commit -am "feat: rename and archive workspaces from rail kebab menu"
```

---

### Task 1.13: Recipe-book button at rail bottom

**Files:**

- Modify: `autopep/src/app/_components/workspace-rail.tsx`

**Step 1:** Add a separator + a `BookOpen` icon button at the rail's bottom (after the `nav` element). Calls `onOpenRecipes`.

**Step 2:** Verify visually + add a small unit test that the button calls the prop.

**Step 3:** Commit

```
git commit -am "feat: open recipes dialog from rail bottom"
```

---

### Task 1.14: Top progress strip on initial load (replaces floating bar)

**Files:**

- Modify: `autopep/src/app/_components/workspace-shell.tsx`

**Step 1:** Replace the floating bottom-corner "Syncing workspace ledger" bar with a 1px-thin gradient strip across the top of the middle column, only visible when `isLoadingWorkspace` is true (initial mount only — already filtered by Task 0.1).

```tsx
{isLoadingWorkspace ? (
  <div className="absolute inset-x-0 top-0 z-[2] h-0.5 overflow-hidden bg-[#e5eadc]">
    <div className="molstar-loading-bar h-full w-1/3 bg-[#dce846]" />
  </div>
) : null}
```

**Step 2:** Commit

```
git commit -am "refactor: replace ledger loader with thin top progress strip"
```

---

### Task 1.15: Delete `JourneyPanel` and the old `RecipeManager`

**Files:**

- Delete: `autopep/src/app/_components/journey-panel.tsx`
- Delete: `autopep/src/app/_components/journey-panel.test.tsx`
- Delete: `autopep/src/app/_components/recipe-manager.tsx`
- Delete: `autopep/src/app/_components/recipe-manager.test.tsx`

**Step 1:** Confirm no remaining imports.

```
cd autopep && rg "JourneyPanel|RecipeManager" src/
```

Should match nothing outside the test files about to be deleted.

**Step 2:** Delete files.

**Step 3:** Verify build

```
cd autopep && bun run typecheck && bun run test
```

**Step 4:** Commit

```
git commit -am "refactor: remove unused journey panel and recipe manager"
```

---

### Task 1.16: Phase 1 browser smoke

**Step 1:** Restart dev server.

```
cd autopep && bun run dev
```

**Step 2:** Use the Playwright MCP to:

- Navigate to `localhost:3000`.
- Confirm the new 3-column layout renders (no right rail "Journey" / "Recipes" sections).
- Confirm the file tree shows in the right rail (likely empty for a fresh workspace).
- Click the recipe-book icon at the rail bottom — confirm the dialog opens, list+editor render, Esc closes it.
- Send a short prompt, watch the chat stream render the user bubble and (with the existing event pipeline still running) tool/artifact cards inline.
- Confirm the floating bottom "Syncing" bar is gone; only a thin top strip flashes briefly on initial load.
- Hover the workspace tile → tooltip shows full name.

**Step 3:** Stop the dev server. No commit.

Phase 1 ships.

---

## Phase 2 — Backend streaming pipeline (Modal SSE + cursor polling + ledger trim)

### Task 2.1: DB migration — add `messages.metadata`, `agent_runs.auto_named_at`, `artifact_kind` enum value `attachment`

**Files:**

- Modify: `autopep/src/server/db/schema.ts`
- Generate: `autopep/drizzle/0006_*.sql`

**Step 1:** Edit `schema.ts`:

- Add `metadata: jsonb("metadata").$type<Record<string, unknown>>().default({}).notNull()` on the `messages` table.
- Add `autoNamedAt: timestamp("auto_named_at", { withTimezone: true })` on `agent_runs` (or `workspaces` — verify which table holds the name; if `workspaces`, put it there).
- Add `attachment` to the artifact kind enum if it's a Postgres enum, OR just to the Zod `artifactKindSchema` if the column is a `text` field.

**Step 2:** Generate migration.

```
cd autopep && bun run db:generate
```

Inspect the generated SQL.

**Step 3:** Apply.

```
cd autopep && bun run db:migrate
```

**Step 4:** Update `agentEventTypeSchema` and `artifactKindSchema` in [contracts.ts](autopep/src/server/agent/contracts.ts) — add `'attachment'` to artifact kind. Run

```
cd autopep && bun run test src/server/agent/contracts.test.ts
```

**Step 5: Commit**

```
git add autopep/src/server/db/schema.ts autopep/drizzle/ autopep/src/server/agent/contracts.ts autopep/src/server/agent/contracts.test.ts
git commit -m "feat: add message metadata, auto_named_at, attachment artifact kind"
```

---

### Task 2.2: Cursor-based event polling — server side

**Files:**

- Modify: `autopep/src/server/api/routers/workspace.ts`
- Modify: `autopep/src/server/api/routers/workspace.test.ts`

**Step 1: Failing test:**

```ts
it("returns events with sequence > sinceSequence", async () => {
  // setup: insert events with sequences 1..5
  const result = await caller.streamEvents({ runId: run.id, sinceSequence: 3 });
  expect(result.events.map((event) => event.sequence)).toEqual([4, 5]);
});
```

**Step 2:** Implement `streamEvents` query — `db.select().from(agentEvents).where(and(eq(agentEvents.runId, runId), gt(agentEvents.sequence, sinceSequence))).orderBy(asc(agentEvents.sequence))`. Returns `{ events, runStatus }`.

**Step 3:** Verify.

**Step 4: Commit**

```
git commit -am "feat: streamEvents tRPC query with sequence cursor"
```

---

### Task 2.3: Cursor-based event polling — client hook

**Files:**

- Create: `autopep/src/app/_components/use-run-events.ts`
- Create: `autopep/src/app/_components/use-run-events.test.ts`

**Step 1: Failing test** (use `@testing-library/react`'s `renderHook`):

```ts
it("polls until run completes", async () => {
  // mock api.workspace.streamEvents
  // first call returns { events: [{...}], runStatus: 'running' }
  // second call returns { events: [], runStatus: 'completed' }
  // expect the hook to stop polling after completed
});
```

**Step 2:** Implement — `useEffect` + `setInterval(800ms)`. Track `sinceSequence` in a ref. Stop when `runStatus` ∈ `{completed, failed, cancelled}`. Return `{ events, runStatus, isPolling }`.

**Step 3:** Wire into `autopep-workspace.tsx`: replace `getWorkspace.refetchInterval: 2000` with a slower 10s refetch, and run `useRunEvents(activeRunId)` on top, merging streamed events into the payload-derived events.

**Step 4: Commit**

```
git commit -am "feat: cursor-based run event polling hook"
```

---

### Task 2.4: Stop persisting token deltas — Modal `streaming.py`

**Files:**

- Modify: `autopep/modal/autopep_agent/streaming.py`
- Modify: `autopep/modal/autopep_agent/runner.py`
- Modify: `autopep/modal/tests/test_streaming.py` (or wherever the existing tests live)

**Step 1: Failing test** in `test_streaming.py`:

```python
def test_normalize_stream_event_drops_token_deltas():
    event = make_response_text_delta_event("hello")
    assert normalize_stream_event(event) is None  # not persisted; surfaced via channel only
```

**Step 2:** Edit `normalize_stream_event` so `response.output_text.delta` returns `None`. Same for `response.created` / `response.completed` and `agent_updated_stream_event`.

**Step 3:** In `runner.py`, before calling `appendRunEvent`, also push the delta into a Modal `Dict` keyed `f"run:{run_id}:tokens"` (or to a per-run `modal.Queue`):

```python
import modal

token_queue = modal.Queue.from_name(f"autopep-tokens-{run_id}", create_if_missing=True)
# on each delta:
await token_queue.put.aio({"type": "delta", "text": delta_text})
# on response.completed:
await token_queue.put.aio({"type": "done"})
# write the final messages row via the existing webhook back to Next.js
```

(If a Queue per run is too heavy, use a single `Dict` with run_id as key and a list value — the SSE handler tails the list. Pick whichever is supported. Verify by reading `modal` SDK docs via context7 if unsure.)

**Step 4:** Verify + commit

```
git commit -am "feat: route assistant token deltas to Modal Queue, stop persisting"
```

---

### Task 2.5: Modal SSE endpoint for run streams

**Files:**

- Modify: `autopep/modal/autopep_worker.py`
- Modify: `autopep/modal/tests/test_autopep_worker.py` (smoke test the endpoint signature)

**Step 1:** Add to `autopep_worker.py`:

```python
@app.function(
    image=control_image,
    secrets=[webhook_secret],
    timeout=AGENT_TIMEOUT_SECONDS,
)
@modal.fastapi_endpoint(method="GET", docs=False, label="run-stream")
async def run_stream(request: Request):
    from fastapi.responses import StreamingResponse

    run_id = request.query_params.get("runId", "")
    token = request.query_params.get("token", "")
    _verify_run_jwt(token, run_id)  # see Task 2.6 for JWT helper

    async def gen():
        token_queue = modal.Queue.from_name(f"autopep-tokens-{run_id}", create_if_missing=True)
        while True:
            try:
                msg = await token_queue.get.aio(timeout=15)
            except Exception:
                yield ": keep-alive\n\n"
                continue
            if msg.get("type") == "done":
                yield "event: done\ndata: {}\n\n"
                return
            if msg.get("type") == "delta":
                payload = json.dumps({"text": msg["text"]})
                yield f"event: delta\ndata: {payload}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

**Step 2:** Verify: `python -c "import autopep_worker"` from the modal/ dir, confirm no import errors.

**Step 3:** Deploy preview.

```
modal deploy modal/autopep_worker.py
```

Capture the new endpoint URL — note it for env update.

**Step 4: Commit**

```
git commit -am "feat: Modal SSE endpoint for per-run token stream"
```

---

### Task 2.6: JWT minting + verification (run-stream auth)

**Files:**

- Create: `autopep/src/server/agent/run-stream-token.ts`
- Create: `autopep/src/server/agent/run-stream-token.test.ts`
- Modify: `autopep/modal/autopep_agent/auth.py` (or inline in `autopep_worker.py`)
- Modify: `autopep/src/server/api/routers/workspace.ts` — add `mintRunStreamToken({ runId })` query

**Step 1: Failing test** — issue a token with `runId='r1'`, assert decoded payload matches; assert verification fails with a wrong secret.

**Step 2:** Implement using `jose` (already common), or HMAC-SHA256 manually with the existing `AUTOPEP_MODAL_WEBHOOK_SECRET`. 1h TTL. Encode `{ runId, userId, exp }`.

**Step 3:** Modal side: implement `_verify_run_jwt(token, run_id)` — same secret, same algorithm. On failure raise 401.

**Step 4:** Add tRPC query that returns the stream URL:

```ts
mintRunStreamToken: protectedProcedure
  .input(z.object({ runId: z.string().uuid() }))
  .query(async ({ ctx, input }) => {
    // assert run.workspace.ownerId === ctx.session.user.id
    const token = signRunStreamToken({ runId: input.runId, userId: ctx.session.user.id });
    return {
      url: `${env.AUTOPEP_MODAL_RUN_STREAM_URL}?runId=${input.runId}&token=${token}`,
    };
  }),
```

Add `AUTOPEP_MODAL_RUN_STREAM_URL` to env schema in [env.ts](autopep/src/env.ts).

**Step 5: Commit**

```
git commit -am "feat: signed JWT auth for Modal run stream"
```

---

### Task 2.7: Frontend EventSource hook

**Files:**

- Create: `autopep/src/app/_components/use-run-stream.ts`
- Create: `autopep/src/app/_components/use-run-stream.test.ts`

**Step 1: Failing test** — mock `EventSource`, dispatch `delta` and `done` events, assert `streamingText` accumulates and `done` flips `isStreaming` false.

**Step 2:** Implement — opens EventSource against the URL returned by `mintRunStreamToken`. Reconnects on error with backoff (cap 5 attempts). Returns `{ streamingText, isStreaming, error }`.

**Step 3:** Wire into `autopep-workspace.tsx`. The streaming text is rendered as a synthetic `assistant_message` stream item with `streaming: true` while running; on `done`, drop it and let the persisted `messages` row from the next `getWorkspace` refetch take over (idempotent — same id since the runner writes the row with a deterministic id).

**Step 4: Commit**

```
git commit -am "feat: SSE hook for run token stream"
```

---

### Task 2.8: Coalesce sandbox stdout/stderr deltas in the runner

**Files:**

- Modify: `autopep/modal/autopep_agent/runner.py`
- Modify: `autopep/modal/autopep_agent/streaming.py`
- Modify: `autopep/modal/tests/test_runner.py`

**Step 1:** In `runner.py`, when a sandbox command produces stdout/stderr chunks, accumulate them in memory keyed by `commandId`. Only on `sandbox_command_completed` do we call `appendRunEvent` once with `display.stdout`, `display.stderr` (truncated to 10KB; full log uploaded to R2 if larger and a `r2Url` set on display).

**Step 2:** Stop emitting `sandbox_stdout_delta` / `sandbox_stderr_delta` to the ledger entirely.

**Step 3:** Test: drive a fake sandbox session with 5 stdout chunks + 1 completed event; assert exactly one `sandbox_command_completed` is appended with the concatenated stdout.

**Step 4:** Commit

```
git commit -am "refactor: coalesce sandbox output deltas into command completion"
```

---

### Task 2.9: Persist final assistant message row from runner

**Files:**

- Modify: `autopep/modal/autopep_agent/runner.py`

**Step 1:** When `response.completed` fires, the runner already accumulates the full assistant text. Have it call back to Next.js (existing webhook pattern) with `POST /api/agent/messages` (new endpoint) that inserts a `messages` row with deterministic `id = sha256(runId + 'assistant' + sequence)`. The frontend already keys items by message id, so re-renders are idempotent.

**Step 2:** Implement the `/api/agent/messages` route in Next.js (mirror existing webhook auth via `AUTOPEP_MODAL_WEBHOOK_SECRET`).

**Step 3:** Commit

```
git commit -am "feat: persist final assistant message row on response completion"
```

---

### Task 2.10: Phase 2 smoke — end-to-end token streaming

**Step 1:** Deploy Modal worker.

```
modal deploy modal/autopep_worker.py
```

**Step 2:** Restart Next.js dev server with `AUTOPEP_MODAL_RUN_STREAM_URL` set.

**Step 3:** Browser test via Playwright MCP:

- Send a prompt that triggers the agent.
- Confirm assistant text *streams* into the chat panel character-by-character, not as a single blob at the end.
- Confirm tool/sandbox/artifact cards still appear inline.
- Reload the page mid-run and confirm the persisted assistant message text is replayed (cursor polling continues to surface meaningful events).

No commit; gate.

---

## Phase 3 — Attachments + workspace auto-naming

### Task 3.1: tRPC mutations for presigned PUT + confirm

**Files:**

- Modify: `autopep/src/server/api/routers/workspace.ts`
- Modify: `autopep/src/server/api/routers/workspace.test.ts`
- Use existing R2 helpers in `autopep/src/server/artifacts/r2.ts`.

**Step 1: Failing test** — call `createAttachment({ workspaceId, fileName, contentType, byteSize })` and assert the returned `presignedUrl` is a string and an `artifacts` row exists with `kind='attachment'` and `status='pending'` (add a status column if absent — or use the existence of `signedUrl=null` as pending).

**Step 2:** Implement `createAttachment`:

- Validate caller owns workspace.
- Reject `byteSize > 25 * 1024 * 1024` (configurable via `AUTOPEP_MAX_ATTACHMENT_BYTES`).
- Compute `storageKey = projects/{projectId}/workspaces/{workspaceId}/attachments/{uuid}/{sanitizedFileName}`.
- Insert artifact row (`kind='attachment'`, `runId=null`, `candidateId=null`).
- Generate presigned PUT URL via existing R2 client (15-minute expiry).
- Return `{ artifactId, uploadUrl, storageKey }`.

**Step 3:** Implement `confirmAttachment({ artifactId })`:

- Validate caller owns the artifact's workspace.
- HEAD the R2 object to confirm it exists (defends against half-uploads).
- Insert a `context_reference` row of `kind='artifact'` referencing the artifact.

**Step 4:** Implement `deleteAttachment({ artifactId })`:

- Validate ownership and that `kind='attachment'` (don't allow deleting agent-produced artifacts).
- Delete R2 object + artifact row.

**Step 5:** Tests + commit

```
git commit -am "feat: attachment upload mutations (createAttachment, confirmAttachment, deleteAttachment)"
```

---

### Task 3.2: Paperclip wired to file input + upload progress

**Files:**

- Modify: `autopep/src/app/_components/chat-panel.tsx`
- Create: `autopep/src/app/_components/use-attachment-upload.ts`
- Create: `autopep/src/app/_components/use-attachment-upload.test.ts`

**Step 1: Failing test** — render the chat panel, click the paperclip, simulate a file selection, assert `createAttachment` is called and a chip appears.

**Step 2:** Implement the hook — accepts `(workspaceId, files: File[])`. For each file:

1. Call `createAttachment` mutation → get `{ artifactId, uploadUrl }`.
2. `fetch(uploadUrl, { method: 'PUT', body: file, headers: { 'Content-Type': file.type } })` with progress via XHR if needed (or just async `fetch` for v1; progress is nice-to-have).
3. Call `confirmAttachment({ artifactId })`.
4. Update chip status: pending → uploading → ready / error.

**Step 3:** Wire the paperclip button: hidden `<input type="file" multiple>` triggered by click. Pass workspaceId from props.

**Step 4:** Verify + commit

```
git commit -am "feat: paperclip uploads files to R2 as attachments"
```

---

### Task 3.3: Modal worker copies attachments into sandbox

**Files:**

- Modify: `autopep/modal/autopep_agent/runner.py`

**Step 1:** Before invoking the agent, query the database (or via webhook) for the run's `context_references` of `kind='artifact'` with `kind='attachment'` artifacts. For each:

- Read from R2 via existing `r2_client.py`.
- Write to `/autopep-workspaces/{workspace_id}/inputs/{filename}` (sanitized).

**Step 2:** Inject a system message before the user prompt:

```python
if attachment_paths:
    system_msg = "Attached files available at:\n" + "\n".join(f"  {p}" for p in attachment_paths)
```

**Step 3:** Test (in `test_runner.py`): mock R2 client, drive a run with one attachment, assert the file is written and the system message contains the path.

**Step 4:** Commit

```
git commit -am "feat: mount attachments into sandbox inputs/ before agent run"
```

---

### Task 3.4: Defer-creation flow for new workspaces

**Files:**

- Modify: `autopep/src/app/_components/autopep-workspace.tsx`
- Modify: `autopep/src/server/api/routers/workspace.ts` — make `sendMessage` accept `workspaceId: string | null`; if null, create the workspace+thread+run inside the same transaction.
- Modify: `autopep/src/server/api/routers/workspace.test.ts`

**Step 1: Failing server test** — call `sendMessage({ workspaceId: null, prompt: 'design X' })`, assert workspace + thread + run all created.

**Step 2:** Implement — wrap inside a `db.transaction`. Reuse `inferWorkspaceName` for the synchronous fallback name (the AI auto-name fires after, in Task 3.5).

**Step 3:** Frontend — when user clicks `+`, set `activeWorkspaceId = null` and render an empty chat with a "draft" placeholder tile in the rail. On send, the mutation returns the new workspace; set it active.

**Step 4:** Disable the `+` button while a draft exists.

**Step 5:** Commit

```
git commit -am "feat: defer workspace creation until first message"
```

---

### Task 3.5: AI auto-name (gpt-5.4-mini)

**Files:**

- Create: `autopep/src/server/workspaces/auto-name.ts`
- Create: `autopep/src/server/workspaces/auto-name.test.ts`
- Modify: `autopep/src/server/api/routers/workspace.ts` — call `inferWorkspaceNameWithAi` non-blocking after creation.

**Step 1: Failing test:**

```ts
it("returns a 3-6 word title from gpt-5.4-mini", async () => {
  const ai = vi.fn(async () => ({ choices: [{ message: { content: "Spike RBD binder design" } }] }));
  const result = await inferWorkspaceNameWithAi({
    prompt: "design a protein binder for SARS-CoV-2 spike RBD",
    openaiClient: ai,
  });
  expect(result).toBe("Spike RBD binder design");
});

it("falls back to first-line trim on AI error", async () => {
  const ai = vi.fn(async () => { throw new Error("boom"); });
  const result = await inferWorkspaceNameWithAi({
    prompt: "  design protein binder  \n more",
    openaiClient: ai,
  });
  expect(result).toBe("design protein binder");
});
```

**Step 2:** Implement using the OpenAI SDK (already in deps via `OPENAI_API_KEY`). Model `gpt-5.4-mini`. 5s timeout via `AbortController`. Strip surrounding quotes and trailing punctuation. Cap at 6 words / 60 chars.

**Step 3:** In `sendMessage` (or `createWorkspace`), after the transaction commits, fire `void inferWorkspaceNameWithAi({ prompt }).then(name => db.update(workspaces).set({ name }))` — non-blocking.

**Step 4: Commit**

```
git commit -am "feat: AI auto-name workspaces from first prompt with gpt-5.4-mini"
```

---

### Task 3.6: Phase 3 smoke

**Step 1:** Restart dev server.

**Step 2:** Browser test via Playwright MCP:

- Click `+` → confirm a draft workspace appears in the rail (e.g. with a `…` initial).
- Send "design a protein binder for SARS-CoV-2 spike RBD".
- Confirm:
  - Workspace appears in rail with the AI-generated initial within ~5s.
  - Hover tooltip shows the full name (something like "Spike RBD binder design").
- Click the paperclip, attach a small `.pdb` file (use a test fixture).
- Confirm:
  - A chip appears in the composer.
  - The file shows up in the right rail under `Attachments/`.
- Send another prompt referencing the attached file; verify the agent acknowledges it (look for the file path in the assistant text or tool calls).

No commit; gate.

---

## Phase 4 — End-to-end validation against prod

The user authorized direct prod migration + redeploy.

### Task 4.1: Apply migrations to prod

**Step 1:** Set `DATABASE_URL` to the prod Neon URL in your shell (use the same env Vercel uses).

**Step 2:** Run

```
cd autopep && bun run db:migrate
```

Expected: applies migration `0006_*.sql` to prod. Confirm with `psql $DATABASE_URL -c "\d messages"` showing `metadata jsonb`.

**Step 3:** No commit (state change only).

---

### Task 4.2: Deploy Modal worker to prod

**Step 1:**

```
modal deploy modal/autopep_worker.py
```

Capture the new `run-stream` URL.

**Step 2:** Set the prod env var on Vercel:

```
vercel env add AUTOPEP_MODAL_RUN_STREAM_URL production
```

Paste the URL when prompted.

**Step 3:** No commit.

---

### Task 4.3: Deploy Next.js to prod

**Step 1:**

```
git push origin codex/harness:main
```

(Or open a PR if branch protection requires; user said zero users so direct push is fine.)

**Step 2:** Wait for Vercel deployment to go green. Confirm the deploy URL loads.

**Step 3:** No commit.

---

### Task 4.4: End-to-end pipeline validation

**Step 1: New workspace + first prompt + auto-name.**

- Open prod URL in a browser via the Playwright MCP.
- Sign in.
- Click `+`. Send: "Design a protein binder for SARS-CoV-2 spike RBD."
- Within 30s, confirm:
  - The rail tile gets a real letter avatar (not "?").
  - Hover tooltip shows an AI-generated multi-word name.

**Step 2: Streaming validation.**

- The assistant message renders character-by-character (visible streaming caret).
- Tool call cards (e.g. `rcsb_structure_search`) appear inline as the agent runs.
- Each card is collapsed; expanding one shows parsed args, not raw SDK structs.
- `assistant_token_delta` is **not** visible as a separate card (would indicate the ledger filter failed).

**Step 3: Candidates tab.**

- Once the first `candidate_ranked` event fires, a `Candidates` tab pins in the middle viewer.
- The table shows ranks, titles, scores.
- Click a row → opens the candidate's primary CIF as a new tab; molstar renders the structure.

**Step 4: File tree.**

- Right rail `Attachments/` is empty initially.
- `Candidates/#1 …/` appears with `prepared.cif`, `sequence.fasta`, etc.
- `Runs/` is collapsed; expanding shows the run with its raw artifacts.
- Clicking a `.fasta` file opens it in a text-preview tab.
- Clicking an unsupported file (e.g. fictional `.xyz`) shows the skeleton with a Download button.

**Step 5: Attachment flow.**

- Click paperclip, attach a small reference `.pdb`.
- Confirm chip appears, then a row appears under `Attachments/`.
- Send "use the attached structure as a reference"; confirm the agent's first sandbox command references the file path or reads the file.

**Step 6: Recipes dialog.**

- Click recipe-book icon at rail bottom.
- Create a new recipe, save it.
- Close dialog; reopen; confirm it's listed.
- Toggle "enabled by default", confirm composer chip reflects it.
- Archive the recipe; confirm it disappears from the list.

**Step 7: Workspace rename.**

- Hover a workspace tile, open kebab menu.
- Click Rename, type a new name, confirm.
- Confirm tooltip updates and rail tile letter changes.

**Step 8: Loading bar regression check.**

- Monitor the middle column for 30 seconds during a run.
- Confirm there is **no** flashing "Syncing workspace ledger" bar every 2s.
- The thin top progress strip only appears on the very first navigation, then disappears.

**Step 9: Stream resilience.**

- During a run, hard-reload the page.
- Confirm:
  - Persisted assistant text is restored (replay works).
  - The cursor poll continues to surface incoming meaningful events.
  - A new SSE connection picks up remaining tokens (if the run hasn't completed yet).

**Step 10: Document any failures.**

If any of the above fail, file a follow-up task in this plan with the specific gap. Do not patch silently.

**Step 11: Final commit (changelog/notes only):**

```
git commit -am "docs: capture end-to-end validation results"
```

(Adds a paragraph to NOTES.md or a new `docs/runbooks/2026-04-30-overhaul-validation.md` file documenting what was tested and confirmed.)

---

## Done.

If all of Task 4.4 passes, the overhaul is shipped. Total expected duration: ~6–8 working days, split into 4 phases with shippable boundaries.
