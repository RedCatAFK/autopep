# Julia Vertical Slice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first deployed Julia vertical slice: email/password auth, project chat, real-time run events, expandable tool steps, R2-backed artifact library, Mol* structure viewing, and a Modal SandboxAgent worker with dry-run and single-pass protein workflow support.

**Architecture:** Next.js is the control plane for auth, UI, Neon-backed state, signed worker starts, event streaming, and artifact reads. Modal runs the Python worker and OpenAI `SandboxAgent`; R2 plus Neon are the durable project filesystem, while each sandbox run is disposable and hydrated only with explicit context artifacts.

**Tech Stack:** Next.js 16, React 19, tRPC, Drizzle, Better Auth email/password, Neon Postgres, Cloudflare R2 S3-compatible storage, EventSource/SSE, Mol*, Python FastAPI, Modal, OpenAI Agents SDK SandboxAgent, pytest, Biome, TypeScript.

---

## Ground Rules

- Only edit files under `/Users/pentest-duck/Desktop/autopep/julia`.
- Do not edit `/Users/pentest-duck/Desktop/autopep/autopep2`; copy proven ideas into `/julia/worker` instead of importing from it.
- Keep code boring and debuggable. Prefer explicit modules over framework cleverness.
- Build dry-run end-to-end before live protein tools.
- Commit after each completed task or small group of tightly related changes.
- Use these verification commands frequently from `/Users/pentest-duck/Desktop/autopep/julia`:

```bash
bun run check
bun run typecheck
bun run test
cd worker && uv run pytest
```

If a command is not available yet, add it in the task that introduces the relevant tooling.

---

### Task 1: Add Minimal Dependencies And Test Scripts

**Files:**
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/package.json`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/env.js`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/.env.example`

**Step 1: Add runtime dependencies**

Install the smallest dependency set needed for v1:

```bash
bun add @aws-sdk/client-s3 @aws-sdk/s3-request-presigner lucide-react molstar react-markdown remark-gfm
```

**Step 2: Add test dependencies**

```bash
bun add -d vitest jsdom @testing-library/react @testing-library/jest-dom
```

**Step 3: Add scripts**

Update `package.json` scripts:

```json
{
  "test": "vitest run",
  "test:watch": "vitest"
}
```

Keep existing `check`, `typecheck`, and Drizzle scripts.

**Step 4: Expand env schema**

In `src/env.js`, remove required GitHub OAuth vars and add server envs:

```ts
BETTER_AUTH_URL: z.string().url().optional(),
JULIA_WORKER_START_URL: z.string().url().optional(),
JULIA_WORKER_WEBHOOK_SECRET: z.string().optional(),
R2_ACCOUNT_ID: z.string().optional(),
R2_ACCESS_KEY_ID: z.string().optional(),
R2_SECRET_ACCESS_KEY: z.string().optional(),
R2_BUCKET: z.string().default("julia"),
R2_PUBLIC_BASE_URL: z.string().url().optional(),
OPENAI_API_KEY: z.string().optional(),
OPENAI_DEFAULT_MODEL: z.string().default("gpt-5.5")
```

Also add the Modal/tool endpoint env names from `autopep2/.env.example`, but make them optional in the Next app because only the worker needs them at runtime.

**Step 5: Update `.env.example`**

Remove GitHub OAuth entries. Add grouped Julia env placeholders:

```bash
BETTER_AUTH_URL="http://localhost:3000"
JULIA_WORKER_START_URL=""
JULIA_WORKER_WEBHOOK_SECRET=""
R2_ACCOUNT_ID=""
R2_ACCESS_KEY_ID=""
R2_SECRET_ACCESS_KEY=""
R2_BUCKET="julia"
R2_PUBLIC_BASE_URL=""
OPENAI_API_KEY=""
OPENAI_DEFAULT_MODEL="gpt-5.5"
```

**Step 6: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: both pass, or fail only on code that later tasks explicitly replace.

**Step 7: Commit**

```bash
git add package.json bun.lock src/env.js .env.example
git commit -m "chore(julia): add vertical slice dependencies"
```

---

### Task 2: Replace GitHub Auth With Email/Password Auth UI

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/auth-card.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/better-auth/config.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/page.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/layout.tsx`

**Step 1: Update Better Auth config**

Remove `socialProviders.github` entirely. Keep:

```ts
export const auth = betterAuth({
  baseURL: env.BETTER_AUTH_URL,
  database: drizzleAdapter(db, { provider: "pg" }),
  emailAndPassword: { enabled: true },
});
```

If `baseURL` rejects `undefined`, pass it conditionally:

```ts
export const auth = betterAuth({
  ...(env.BETTER_AUTH_URL ? { baseURL: env.BETTER_AUTH_URL } : {}),
  database: drizzleAdapter(db, { provider: "pg" }),
  emailAndPassword: { enabled: true },
});
```

**Step 2: Create `AuthCard`**

Use the proven old app shape but simplify styles. Required behavior:

- toggle sign in/sign up
- sign up with `authClient.signUp.email({ name, email, password })`
- sign in with `authClient.signIn.email({ email, password })`
- sign out with `authClient.signOut()`
- show inline error text
- `router.refresh()` after success

**Step 3: Replace stock homepage**

In `src/app/page.tsx`:

- call `getSession()`
- if no session, render a simple two-column Julia sign-in page with `AuthCard`
- if session exists, render a temporary workspace placeholder until Task 8 replaces it

Do not keep T3 links, sample post UI, or GitHub sign-in.

**Step 4: Update metadata**

Set layout metadata:

```ts
export const metadata: Metadata = {
  title: "Julia",
  description: "Agentic protein design workspace",
  icons: [{ rel: "icon", url: "/favicon.ico" }],
};
```

**Step 5: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 6: Commit**

```bash
git add src/server/better-auth/config.ts src/app/page.tsx src/app/layout.tsx src/app/_components/auth-card.tsx
git commit -m "feat(julia): add email password auth screen"
```

---

### Task 3: Add Pure Run And Artifact Helpers With Tests

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/vitest.config.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/lib/artifacts.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/lib/artifacts.test.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/lib/run-events.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/lib/run-events.test.ts`

**Step 1: Add Vitest config**

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

**Step 2: Write failing artifact tests**

Test:

- `.cif`, `.mmcif`, `.pdb` classify as `structure`
- `.json` as `json`
- `.fa`, `.fasta` as `fasta`
- `.log`, `.txt`, `.md` as text/log
- R2 key sanitizes filenames and includes `projectId`, `runId`, `artifactId`

**Step 3: Implement artifact helpers**

Expose:

```ts
export type ArtifactKind = "structure" | "json" | "log" | "fasta" | "text" | "other";

export function classifyArtifactKind(filename: string): ArtifactKind;
export function isStructureArtifact(filename: string): boolean;
export function buildArtifactR2Key(input: {
  projectId: string;
  runId: string;
  artifactId: string;
  filename: string;
}): string;
```

Use simple extension matching and filename sanitization.

**Step 4: Write failing run-event tests**

Test:

- tool event labels show `toolName`
- failed event maps to red/error state
- queued/running/completed map to stable status labels

**Step 5: Implement run-event helpers**

Expose:

```ts
export type RunEventType =
  | "run_status"
  | "text_delta"
  | "assistant_message_snapshot"
  | "tool_call_started"
  | "tool_call_completed"
  | "artifact_created"
  | "run_error";

export function eventDisplayLabel(event: { type: RunEventType; toolName?: string | null }): string;
export function eventTone(event: { type: RunEventType; status?: string | null }): "neutral" | "active" | "success" | "error";
```

**Step 6: Verify**

Run:

```bash
bun run test
bun run check
bun run typecheck
```

Expected: pass.

**Step 7: Commit**

```bash
git add vitest.config.ts src/lib/artifacts.ts src/lib/artifacts.test.ts src/lib/run-events.ts src/lib/run-events.test.ts package.json bun.lock
git commit -m "test(julia): add run and artifact helpers"
```

---

### Task 4: Define Drizzle Schema For Projects, Runs, Events, And Artifacts

**Files:**
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/db/schema.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/drizzle.config.ts`

**Step 1: Fix table prefix**

Use a Julia app prefix for app tables:

```ts
export const createTable = pgTableCreator((name) => `julia_${name}`);
```

Keep Better Auth tables as `user`, `session`, `account`, `verification`.

**Step 2: Add enums**

Add pg enums:

```ts
export const messageRole = pgEnum("julia_message_role", ["user", "assistant", "system"]);
export const messageStatus = pgEnum("julia_message_status", ["pending", "streaming", "complete", "failed"]);
export const runStatus = pgEnum("julia_run_status", ["queued", "starting", "running", "completed", "failed", "cancelled"]);
export const runMode = pgEnum("julia_run_mode", ["single", "tree"]);
export const runEventType = pgEnum("julia_run_event_type", [
  "run_status",
  "text_delta",
  "assistant_message_snapshot",
  "tool_call_started",
  "tool_call_completed",
  "artifact_created",
  "run_error",
]);
export const artifactKind = pgEnum("julia_artifact_kind", ["structure", "json", "log", "fasta", "text", "other"]);
```

**Step 3: Add tables**

Add:

- `projects`
- `threads`
- `messages`
- `runs`
- `runEvents`
- `artifacts`
- `contextReferences`

Use `uuid().defaultRandom().primaryKey()` for app IDs. Use `jsonb` for metadata payloads. Add indexes on owner/project/thread/run foreign keys and `runEvents(runId, sequence)`.

**Step 4: Update Drizzle table filter**

Use:

```ts
tablesFilter: ["julia_*", "user", "session", "account", "verification"],
```

**Step 5: Generate migration**

Run:

```bash
bun run db:generate
```

Expected: a new migration under `/Users/pentest-duck/Desktop/autopep/julia/drizzle`.

If env validation blocks generation due missing `DATABASE_URL`, run:

```bash
SKIP_ENV_VALIDATION=1 bun run db:generate
```

**Step 6: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 7: Commit**

```bash
git add src/server/db/schema.ts drizzle.config.ts drizzle
git commit -m "feat(julia): add workspace run schema"
```

---

### Task 5: Add Server-Side Workspace And Run APIs

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/server/api/routers/workspace.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/server/api/routers/run.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/api/root.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/server/worker-signing.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/server/run-service.ts`

**Step 1: Workspace router**

Create protected procedures:

- `getOrCreateDefaultProject`
- `getProjectState({ projectId })`
- `createThread({ projectId })`
- `listArtifacts({ projectId })`
- `addContextReference({ projectId, threadId, artifactId, label })`
- `removeContextReference({ id })`

Keep the return shape UI-friendly: project, threads, current thread, messages, latest runs, events, artifacts, context references.

**Step 2: Run service**

Implement `createRunForPrompt`:

- validate project/thread ownership
- insert user message
- insert assistant placeholder message with `status="pending"`
- insert run with `status="queued"`, `runMode="single"`
- insert first `run_status` event
- call `startWorkerRun(runId)` after DB writes

If worker env is missing, create a dry-run event sequence locally in development instead of throwing. This lets UI work before Modal is deployed.

**Step 3: Worker signing**

Implement HMAC signing:

```ts
export function signWorkerPayload(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("hex");
}
```

Send signature as `x-julia-signature`.

**Step 4: Run router**

Create protected mutation:

- `sendMessage({ projectId, threadId, content, contextReferenceIds })`

Return `{ runId, assistantMessageId }`.

**Step 5: Register routers**

Add `workspace` and `run` to `src/server/api/root.ts`.

**Step 6: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 7: Commit**

```bash
git add src/server/api/root.ts src/server/api/routers/workspace.ts src/server/api/routers/run.ts src/server/worker-signing.ts src/server/run-service.ts
git commit -m "feat(julia): add workspace run APIs"
```

---

### Task 6: Add Artifact Storage And Signed Read Routes

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/server/r2.ts`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/api/artifacts/[artifactId]/route.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/api/routers/workspace.ts`

**Step 1: R2 client**

Implement:

```ts
export function getR2Client(): S3Client;
export async function createSignedArtifactUrl(key: string): Promise<string>;
```

Endpoint shape:

```ts
const endpoint = `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`;
```

If `R2_PUBLIC_BASE_URL` is present, signed URL helper can return `${base}/${key}`.

**Step 2: Artifact route**

`GET /api/artifacts/[artifactId]`:

- require session
- load artifact
- verify project owner
- redirect to signed URL

Use a redirect so Mol* can load the actual file URL.

**Step 3: Workspace artifact response**

Include `viewerUrl: /api/artifacts/${artifact.id}` for each artifact.

**Step 4: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 5: Commit**

```bash
git add src/server/r2.ts src/app/api/artifacts/[artifactId]/route.ts src/server/api/routers/workspace.ts
git commit -m "feat(julia): add artifact read URLs"
```

---

### Task 7: Add Run Event SSE With Polling Fallback Shape

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/api/runs/[runId]/events/route.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/api/routers/run.ts`

**Step 1: SSE route**

Implement `GET /api/runs/[runId]/events?after=<sequence>`:

- require session
- verify run belongs to user's project
- loop for up to 55 seconds
- query events where `sequence > after`
- write `event: run-event` payloads
- send heartbeat comments every 10 seconds
- close when run is terminal and all events after `after` are sent

Keep it simple: DB polling every 500-1000ms inside the route.

**Step 2: Polling fallback**

Add tRPC query:

- `run.listEvents({ runId, afterSequence })`

The client can use this if EventSource errors.

**Step 3: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 4: Commit**

```bash
git add src/app/api/runs/[runId]/events/route.ts src/server/api/routers/run.ts
git commit -m "feat(julia): stream run events"
```

---

### Task 8: Build The Workspace Shell UI

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/workspace-shell.tsx`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/chat-panel.tsx`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/tool-step.tsx`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/file-panel.tsx`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/context-pills.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/page.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/styles/globals.css`

**Step 1: Workspace shell**

Implement a stable 4-region layout:

```text
left rail | chat panel | viewer | files/tree panel
```

Use simple CSS grid, fixed min widths, and no nested cards.

**Step 2: Chat panel**

Requirements:

- render messages
- markdown assistant content through `react-markdown` and `remark-gfm`
- prompt textarea
- submit calls `api.run.sendMessage`
- context pills above input
- compact status row while a run is active

**Step 3: Event source hook**

Inside `chat-panel.tsx` or a local `use-run-events.ts`:

- open `EventSource('/api/runs/${runId}/events?after=${lastSequence}')`
- append events to local state
- update assistant message text from `text_delta`
- fallback to `api.run.listEvents` if EventSource errors

**Step 4: Tool step rows**

Collapsed:

```text
run_chai · running
```

Expanded:

- arguments JSON
- output JSON summary
- timestamps
- errors
- artifact links

Use native `<button>` plus conditional content. Keep animation minimal.

**Step 5: File panel**

Show artifacts grouped by run or display path:

- filename
- artifact kind
- source tool
- created time
- click selects file for viewer
- button adds file to context

**Step 6: Styling**

Use a restrained light/dim workspace palette. Avoid decorative gradients. Use CSS variables in `globals.css` for panel borders, background, text, warning, and error colors.

**Step 7: Verify**

Run:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 8: Commit**

```bash
git add src/app/page.tsx src/app/_components/workspace src/styles/globals.css
git commit -m "feat(julia): add workspace chat shell"
```

---

### Task 9: Add Mol* Structure Viewer

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/molstar-viewer.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/workspace-shell.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/file-panel.tsx`

**Step 1: Dynamic client-only viewer**

Create a client component that:

- accepts `{ artifactId, viewerUrl, filename }`
- initializes Mol* in a `ref`
- loads `.cif`, `.mmcif`, and `.pdb`
- disposes plugin on unmount or file change

If Mol* import needs dynamic loading, use `await import("molstar/lib/mol-plugin-ui")` style imports inside `useEffect`.

**Step 2: Selection behavior**

Required v1:

- selected file can be added to context

Optional only if straightforward:

- current chain/residue selection can become a context reference

Do not write custom CIF/PDB parsing for residue selection in v1.

**Step 3: Empty/error states**

Viewer states:

- no file selected
- selected artifact is not a structure
- loading
- failed to load

**Step 4: Verify**

Run:

```bash
bun run check
bun run typecheck
```

If possible, run local dev and manually open a known small CIF/PDB artifact after the dry-run worker creates one.

**Step 5: Commit**

```bash
git add src/app/_components/workspace/molstar-viewer.tsx src/app/_components/workspace/workspace-shell.tsx src/app/_components/workspace/file-panel.tsx
git commit -m "feat(julia): add molstar artifact viewer"
```

---

### Task 10: Scaffold Python Worker With Tests

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/pyproject.toml`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/__init__.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/config.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/events.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/artifacts.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/tests/test_events.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/tests/test_artifacts.py`

**Step 1: Add worker pyproject**

Dependencies:

```toml
dependencies = [
  "boto3>=1.34",
  "fastapi>=0.115",
  "httpx>=0.28.1",
  "modal>=1.0",
  "openai-agents>=0.7.0",
  "psycopg[binary]>=3.2",
  "python-dotenv>=1.0.1",
  "uvicorn>=0.32",
]

[dependency-groups]
dev = ["pytest>=8.0"]
```

If the Modal sandbox extension imports are missing after `uv sync`, check the current OpenAI Agents SDK Modal extension installation docs and adjust the worker dependencies before writing feature code. Keep import tests authoritative.

**Step 2: Config module**

Read envs:

- `DATABASE_URL`
- `JULIA_WORKER_WEBHOOK_SECRET`
- `OPENAI_API_KEY`
- `OPENAI_DEFAULT_MODEL`
- `R2_*`
- `MODAL_*`
- tool endpoint envs

Do not print secrets.

**Step 3: Event tests**

Write tests for:

- text delta normalization
- tool call started/completed normalization
- run error normalization

**Step 4: Artifact tests**

Write tests for:

- allowed output path detection
- artifact kind classification
- R2 key generation
- final scan ignores files outside `outputs/`

**Step 5: Implement minimal helpers**

Keep helpers pure and tested before DB/R2 clients exist.

**Step 6: Verify**

Run:

```bash
cd worker
uv sync
uv run pytest
```

Expected: pass.

**Step 7: Commit**

```bash
git add worker
git commit -m "test(julia): scaffold worker helpers"
```

---

### Task 11: Add Worker DB, R2, And Dry-Run Route

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/db.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/storage.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/main.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/tests/test_signing.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/events.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/artifacts.py`

**Step 1: Signing tests**

Test worker rejects missing/bad signature and accepts valid HMAC over raw request body.

**Step 2: DB helpers**

Implement small sync helpers with `psycopg`:

- `mark_run_status(run_id, status, error_summary=None)`
- `insert_run_event(run_id, type, payload, sequence)`
- `append_assistant_delta(message_id, delta)`
- `insert_artifact(...)`
- `load_run_context(run_id)`

Keep SQL explicit. Avoid ORM in the worker.

**Step 3: R2 helpers**

Implement upload with boto3 S3 client. Return key, size, sha256.

**Step 4: Dry-run route**

`POST /runs/start`:

- verify signature
- if payload has `dryRun: true` or env `JULIA_WORKER_DRY_RUN=1`, emit fake events:
  - status starting
  - status running
  - text deltas
  - tool call started/completed for `literature_research`
  - artifact_created for a tiny generated example text or CIF file
  - status completed

This route writes to Neon exactly like a real run.

**Step 5: Health route**

`GET /health` returns `{ ok: true }`.

**Step 6: Verify**

Run:

```bash
cd worker
uv run pytest
```

From `/julia`:

```bash
bun run check
bun run typecheck
```

Expected: pass.

**Step 7: Commit**

```bash
git add worker
git commit -m "feat(julia): add dry run worker"
```

---

### Task 12: Wire Next Run Start To Dry-Run Worker And UI

**Files:**
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/server/run-service.ts`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/chat-panel.tsx`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/src/app/_components/workspace/file-panel.tsx`

**Step 1: Start worker from Next**

In `startWorkerRun`, POST:

```json
{
  "runId": "...",
  "projectId": "...",
  "threadId": "...",
  "assistantMessageId": "...",
  "dryRun": true
}
```

Sign raw JSON with `JULIA_WORKER_WEBHOOK_SECRET`.

**Step 2: UI dry-run validation**

Submit a message locally and verify:

- assistant text streams in
- tool row appears collapsed
- expanding shows params/output
- artifact appears in file panel
- failed worker start produces a red run error

**Step 3: Verify**

Run:

```bash
bun run check
bun run typecheck
```

If local DB is configured:

```bash
bun run dev
```

Expected: dry-run prompt works end-to-end.

**Step 4: Commit**

```bash
git add src/server/run-service.ts src/app/_components/workspace/chat-panel.tsx src/app/_components/workspace/file-panel.tsx
git commit -m "feat(julia): wire dry run event flow"
```

---

### Task 13: Port Single-Pass Protein Tools Into Worker

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/tools.py`
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/tests/test_tools_paths.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/artifacts.py`

**Step 1: Copy tool logic intentionally**

From `/autopep2/main.py`, copy and adapt only needed pieces:

- safe slug/path helpers
- trim/jsonable helpers
- PMC literature search
- RCSB search/fetch
- structure sequence/chain parsing
- Proteina request
- Chai request
- scorer request
- bash/python execution if still needed by the agent

Adapt paths to the v1 workspace:

```text
inputs/
outputs/literature/
outputs/pdb/
outputs/proteina_runs/
outputs/chai_runs/
outputs/scoring_runs/
outputs/tool_logs/
```

**Step 2: Path tests**

Test:

- tool output paths stay under `outputs/`
- unsafe paths are rejected
- structure files classify as uploadable artifacts
- allowed final scan ignores `inputs/`

**Step 3: Tool-return artifact extraction**

In `artifacts.py`, implement:

```python
def artifact_paths_from_tool_result(tool_name: str, result: dict[str, Any]) -> list[Path]:
    ...
```

Handle:

- `literature_search`: `sandbox_path`
- `search_pdb`: `sandbox_path`
- `fetch_pdb`: `sandbox_path`
- `run_proteina`: response and candidate paths
- `run_chai`: input FASTA, response, CIF/PDB paths
- `run_scorers`: response paths and summary

**Step 4: Verify**

Run:

```bash
cd worker
uv run pytest
```

Expected: pass without live external calls.

**Step 5: Commit**

```bash
git add worker/julia_agent/tools.py worker/julia_agent/artifacts.py worker/tests/test_tools_paths.py
git commit -m "feat(julia): port protein workflow tools"
```

---

### Task 14: Build SandboxAgent Runner

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/agent.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/main.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/events.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/worker/julia_agent/artifacts.py`

**Step 1: Agent prompt**

Create concise Julia instructions:

- general chat is allowed
- binder generation trigger follows the `autopep2` workflow
- prefer warm starts when available
- use CIF/mmCIF for targets
- keep replies concise
- do not claim wet-lab validation or therapeutic readiness

**Step 2: Build SandboxAgent**

Use current SDK imports:

```python
from agents import Runner
from agents.run import RunConfig
from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
from agents.sandbox.entries import File
from agents.extensions.sandbox import ModalSandboxClient, ModalSandboxClientOptions
```

If imports differ with the installed SDK, update the worker code and leave a short comment with the verified import source.

**Step 3: Manifest**

Build manifest with:

- `inputs/context.json`
- hydrated artifact files as `inputs/artifacts/<artifactId>_<filename>`
- empty output directories

**Step 4: Stream events**

Use `Runner.run_streamed`.

Map:

- raw text deltas -> `text_delta`
- run item tool calls -> `tool_call_started`
- tool outputs -> `tool_call_completed`
- exceptions -> `run_error`

After each tool completion, call `artifact_paths_from_tool_result`, upload those files, and emit `artifact_created`.

**Step 5: Final scan**

Always final-scan allowed `outputs/` directories on completed or failed runs.

**Step 6: Verify with dry model guard**

Add an env guard:

```bash
JULIA_WORKER_ALLOW_LIVE_RUNS=1
```

Without it, `/runs/start` should use dry-run mode even if `dryRun` is false.

Run:

```bash
cd worker
uv run pytest
```

Expected: pass.

**Step 7: Commit**

```bash
git add worker/julia_agent/agent.py worker/julia_agent/main.py worker/julia_agent/events.py worker/julia_agent/artifacts.py
git commit -m "feat(julia): run sandbox agent worker"
```

---

### Task 15: Add Modal App Entrypoint And Deploy Config

**Files:**
- Create: `/Users/pentest-duck/Desktop/autopep/julia/worker/modal_app.py`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/README.md`
- Modify: `/Users/pentest-duck/Desktop/autopep/julia/.env.example`

**Step 1: Modal app**

Create a Modal app named `julia-agent-worker`.

Expose FastAPI app from `julia_agent.main`.

Include secrets by Modal secret name, for example:

```python
app = modal.App("julia-agent-worker")
```

Use a simple image with Python deps installed from `worker/pyproject.toml`.

**Step 2: README deployment section**

Document:

- Vercel project root is `/julia`
- Modal deploy command from `/julia/worker`
- required env groups
- dry-run first, live run only with `JULIA_WORKER_ALLOW_LIVE_RUNS=1`

**Step 3: Verify locally**

Run:

```bash
cd worker
uv run python -m julia_agent.main
```

Expected: FastAPI can start locally, or exits with only expected missing-env messages.

**Step 4: Commit**

```bash
git add worker/modal_app.py README.md .env.example
git commit -m "chore(julia): add worker deployment entrypoint"
```

---

### Task 16: Run Local End-To-End Dry Verification

**Files:**
- Modify only files needed for bugs found during verification.

**Step 1: Prepare DB**

Run:

```bash
bun run db:push
```

If TCP connectivity to Neon blocks local pushes, document the failure and use deployed/alternate network migration path later.

**Step 2: Start app**

Run:

```bash
bun run dev
```

**Step 3: Start worker locally**

In another terminal:

```bash
cd worker
JULIA_WORKER_DRY_RUN=1 uv run uvicorn julia_agent.main:app --reload --port 8001
```

Set `JULIA_WORKER_START_URL=http://localhost:8001/runs/start`.

**Step 4: Manual smoke**

Verify:

- sign up
- sign in
- send general prompt
- see streaming text
- see expandable `literature_research` dry-run tool step
- see artifact in file panel
- click artifact URL
- add artifact to context
- send follow-up and verify context reference appears

**Step 5: Automated checks**

Run:

```bash
bun run test
bun run check
bun run typecheck
cd worker && uv run pytest
```

Expected: all pass, except explicitly documented network-limited DB push.

**Step 6: Commit fixes**

```bash
git add <fixed-files>
git commit -m "fix(julia): stabilize dry run flow"
```

Only commit if fixes were needed.

---

### Task 17: Deploy Vercel, Modal, And Dry-Run Smoke

**Files:**
- Modify only deployment docs or config files if needed.

**Step 1: Link Vercel**

Create/link Vercel project `julia` with project root `/Users/pentest-duck/Desktop/autopep/julia`.

**Step 2: Set Vercel envs**

Set:

- `DATABASE_URL`
- `BETTER_AUTH_SECRET`
- `BETTER_AUTH_URL`
- `JULIA_WORKER_START_URL`
- `JULIA_WORKER_WEBHOOK_SECRET`
- R2 envs

**Step 3: Deploy Modal worker**

Deploy `julia-agent-worker` with dry-run enabled first.

**Step 4: Deploy Vercel**

Deploy Julia app.

**Step 5: Dry-run smoke**

In production:

- sign in
- submit dry-run prompt
- verify streamed text/tool/artifact UI
- verify artifact route returns file bytes or signed redirect

**Step 6: Commit deployment doc fixes**

```bash
git add README.md .env.example
git commit -m "docs(julia): document deployment smoke flow"
```

Only commit if docs changed.

---

### Task 18: Enable One Controlled Live Protein Canary

**Files:**
- Modify only files needed for live-run bugs.

**Step 1: Set live envs**

In Modal, set:

- `OPENAI_API_KEY`
- `JULIA_WORKER_ALLOW_LIVE_RUNS=1`
- `MODAL_CHAI_URL`
- `MODAL_CHAI_API_KEY`
- `MODAL_PROTEINA_URL`
- `MODAL_PROTEINA_API_KEY`
- `MODAL_PROTEIN_INTERACTION_SCORING_URL`
- `MODAL_PROTEIN_INTERACTION_SCORING_API_KEY`
- `MODAL_QUALITY_SCORERS_URL`
- `MODAL_QUALITY_SCORERS_API_KEY`
- R2 envs
- `DATABASE_URL`

**Step 2: Run one live prompt**

Use a controlled prompt:

```text
Generate 3 candidate binder proteins for BACE1 and show me the generated files.
```

**Step 3: Verify UI**

Check:

- tool calls stream in order
- tool rows expand with inputs/outputs
- Proteina, Chai, and scorer artifacts appear
- at least one `.cif` or `.pdb` opens in Mol*
- failure events are visible if any external tool fails

**Step 4: Run checks**

Run locally after any fixes:

```bash
bun run test
bun run check
bun run typecheck
cd worker && uv run pytest
```

**Step 5: Commit fixes**

```bash
git add <fixed-files>
git commit -m "fix(julia): stabilize live protein run"
```

Only commit if fixes were needed.

---

## Final Verification Checklist

Before declaring done:

- `bun run test` passes.
- `bun run check` passes.
- `bun run typecheck` passes.
- `cd worker && uv run pytest` passes.
- Dry-run deployed smoke passes.
- Live canary either passes or has a clear external-tool/environment failure recorded in the UI.
- No files outside `/Users/pentest-duck/Desktop/autopep/julia` were edited by implementation.
- Unrelated pre-existing changes in `/autopep2` remain untouched.
