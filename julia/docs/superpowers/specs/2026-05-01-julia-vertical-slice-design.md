# Julia Vertical Slice Design

Date: 2026-05-01

## Purpose

Julia is the reboot of Autopep as a full-stack web app for agentic protein design workflows. The first vertical slice must prove the deployed loop that the `autopep2` CLI already validated locally: a user signs in, chats with a general agent, asks it to generate or analyze proteins, watches token and tool progress in real time, and opens generated structure files in the workspace.

This spec covers only the first shippable slice. It intentionally favors simple code and operational clarity over broad feature coverage.

## Design Context

Target audience: computational biology users and hackathon evaluators who need to see an end-to-end "generate proteins to bind X" workflow work in a browser.

Primary jobs:

- Start or continue a project-scoped chat.
- Ask general scientific questions.
- Ask for binder generation, which should trigger the baked-in protein design workflow.
- Watch model tokens, tool calls, and tool outputs as they happen.
- Browse generated files and open `.cif`, `.mmcif`, or `.pdb` structures.
- Add selected files or Mol* selections back into chat context.

Tone: utilitarian molecular workspace. The UI should feel like a quiet research cockpit: dense, legible, and direct. Simplicity is king for both UI and code. Avoid decorative dashboard patterns, marketing sections, and clever abstractions.

## Constraints

- All implementation work stays inside `/Users/pentest-duck/Desktop/autopep/julia`.
- `/Users/pentest-duck/Desktop/autopep/autopep` is read-only inspiration and should be treated with caution.
- `/Users/pentest-duck/Desktop/autopep/autopep2` is the source of truth for the working CLI workflow shape, but must not be edited for this slice.
- Better Auth uses email/password only, not GitHub OAuth.
- The existing external Modal endpoints for Proteina, Chai, interaction scoring, and quality scoring stay in use.
- Julia gets its own Vercel project, Neon project, R2 bucket, and Modal worker app.
- The first worker implementation uses single-pass protein generation only. Tree mode is modeled in the data shape but not implemented.

## Sources Checked

- OpenAI Agents SDK sandbox guidance was checked on 2026-05-01. The relevant design point is the control-plane versus compute-plane split: the app should keep trusted orchestration outside model-directed sandbox execution.
- The OpenAI Agents SDK repository has a Modal sandbox example using `SandboxAgent`, `SandboxRunConfig`, `ModalSandboxClient`, `ModalSandboxClientOptions`, streamed events, and Modal workspace persistence.
- Neon guidance and prior project experience indicate Vercel plus Neon should start with the normal Drizzle/Postgres path if it works, while keeping the design flexible enough to switch to a Neon serverless driver if TCP connectivity becomes a blocker.

## Architecture

The system has three planes.

### Next/Vercel Control Plane

The Next app owns authentication, user-visible APIs, and UI state.

Responsibilities:

- Better Auth email/password sign in and sign up.
- Project, thread, message, run, event, artifact, and context-reference APIs.
- Run creation and signed worker start requests.
- Event subscription for the browser through a Next-owned SSE route, with polling as an acceptable fallback if SSE slows the first slice.
- Signed artifact read URLs for file previews and Mol*.
- Deployment to a Vercel project named `julia`, rooted at `/Users/pentest-duck/Desktop/autopep/julia`.

### Modal Worker Execution Plane

A Julia Modal FastAPI app owns long-running agent execution.

Responsibilities:

- `POST /runs/start`: receive a signed start request from Next.
- `GET /health`: basic deployment sanity check.
- Build and run a Python Agents SDK `SandboxAgent`.
- Use `SandboxRunConfig(client=ModalSandboxClient(), options=ModalSandboxClientOptions(app_name="julia-agent-worker", ...))`.
- Normalize SDK stream events into Neon rows.
- Upload important generated files to R2.
- Mark run status completed or failed.

Worker modules should stay narrow:

- `main.py`: FastAPI routes and orchestration.
- `agent.py`: Julia agent construction and instructions.
- `tools.py`: minimal port of proven `autopep2` tools.
- `events.py`: SDK event normalization and database writes.
- `artifacts.py`: artifact extraction, R2 upload, final scans, and artifact rows.
- `storage.py` or `db.py`: small database and R2 clients if needed to avoid crowding route code.

Avoid queues for v1. Next creates the run row, calls Modal once, Modal does the work, and the browser observes durable state through Next.

### Artifact Plane

Cloudflare R2 and Neon are the durable project filesystem. Modal sandboxes are disposable execution workspaces.

The UI never depends on direct live Modal filesystem access. It reads file trees from Neon and file bytes through signed Next/R2 URLs.

## Agent Behavior

The Julia agent is a general chat agent with a protein-design workflow baked into its instructions.

General questions should receive normal concise answers.

When the user asks to "generate a protein to bind X", "design binders for X", or equivalent, the agent follows the proven `autopep2` single-pass workflow:

1. Search literature for the target, interface biology, useful complexes, hotspots, and caveats.
2. Search RCSB PDB for target structures and target-bound complexes.
3. Fetch selected target structures, preferring CIF/mmCIF.
4. Inspect chains, residue numbering, target sequence, and possible warm-start binders.
5. Prefer warm start when a suitable existing bound binder or partner exists.
6. Run Proteina for 3 candidates.
7. Fold each Proteina candidate with Chai as a target-plus-binder complex.
8. Score each folded candidate with the interaction and quality scorers.
9. Report ranked results with concise rationale and paths to generated artifacts.

The prompt should preserve the `autopep2` safety posture: do not claim wet-lab validation, clinical efficacy, safety, or therapeutic readiness.

## Data Model

Keep tables explicit and small.

Better Auth tables:

- `user`
- `session`
- `account`
- `verification`

Julia application tables:

- `project`: owner-scoped project/workspace.
- `thread`: chat thread inside a project.
- `message`: user and assistant messages with role, content, status, and metadata.
- `run`: one agent execution linked to a project, thread, and assistant message.
- `run_event`: append-only event stream for UI rendering and debugging.
- `artifact`: project-scoped file catalog entry backed by R2.
- `context_reference`: file or Mol* selection attached to a future prompt.

Run rows include:

- `runMode`: `single` for v1, with `tree` reserved.
- `status`: `queued`, `starting`, `running`, `completed`, `failed`, or `cancelled`.
- `model`: model/provider label.
- `errorSummary`: short user-visible failure summary.
- `startedAt`, `completedAt`, and `createdAt`.

Tree-ready fields exist where useful:

- `nodeId`
- `parentNodeId`
- `candidateRank`

They may be null for v1 single-pass runs.

## Event Model

The UI renders from `run_event` rows. Events should be durable, normalized, and safe to display.

Core event types:

- `run_status`: queued, starting, running, completed, failed, cancelled.
- `text_delta`: incremental assistant token text.
- `assistant_message_snapshot`: checkpointed assistant content.
- `tool_call_started`: tool name plus parsed arguments.
- `tool_call_completed`: tool name plus compact output summary.
- `artifact_created`: artifact row became available.
- `run_error`: structured visible error.

Tool event rows include:

- `toolName`
- `toolCallId`
- `status`
- `inputJson`
- `outputJson`
- `startedAt`
- `completedAt`
- `error`

Large JSON should be truncated for UI summaries while the full JSON file is stored as an artifact when useful.

## File Persistence

Use a project-scoped artifact library.

R2 key shape:

```text
workspaces/{projectId}/runs/{runId}/{artifactId}/{filename}
```

Neon `artifact` rows store:

- `projectId`
- `runId`
- `messageId` when relevant
- `sourceToolCallId` when known
- `displayPath`
- `filename`
- `sandboxPath`
- `r2Key`
- `sha256`
- `size`
- `artifactKind`: `structure`, `json`, `log`, `fasta`, `text`, or `other`
- `source`: `tool_result`, `final_scan`, or `user_upload`
- `metadataJson`
- timestamps

Sandbox-to-R2 sync is explicit:

- During execution, after a known tool completes, the worker extracts file paths from the tool result, uploads those files to R2, writes `artifact` rows, and emits `artifact_created` events.
- At completion or failure, the worker scans allowed output directories once and uploads any missed files.
- No background filesystem watcher in v1.

Allowed output directories:

```text
outputs/literature/
outputs/pdb/
outputs/proteina_runs/
outputs/chai_runs/
outputs/scoring_runs/
outputs/reports/
outputs/tool_logs/
```

## Multi-Turn Project Conversations

R2/Neon are the durable project memory for files. A Modal sandbox is a per-run workspace.

For each new run, the worker creates a fresh sandbox workspace:

```text
workspace/
  inputs/
    context.json
    artifacts/
      <artifactId>_<filename>
  outputs/
    literature/
    pdb/
    proteina_runs/
    chai_runs/
    scoring_runs/
    reports/
    tool_logs/
```

Hydration is explicit:

- Normal follow-up questions load recent thread messages and artifact metadata only.
- If the user attaches a file, file selection, or Mol* selection to context, the worker downloads only those R2 objects into `inputs/artifacts/`.
- `inputs/context.json` records selected artifact IDs, original filenames, display paths, Mol* selection metadata, and user-visible labels.

This matches the useful part of the `autopep2` mental model without requiring one long-lived Modal sandbox per project.

Modal sandbox snapshots or session resume can be added later for "continue exact live workspace", but they are not v1.

## UI Design

The first UI should be a working research workspace, not a landing page.

Layout:

- Left rail: minimal project/thread navigation.
- Left chat panel: prompt input, context pills, token stream, compact status, and expandable tool steps.
- Center viewer: Mol* structure viewer for selected `.cif`, `.mmcif`, and `.pdb` artifacts.
- Right panel: project artifact list first, with a tree visualizer area reserved for later tree mode.

Chat behavior:

- Show real-time token streaming.
- Show loading indicators tied to real events: queued, worker starting, model thinking, tool running, uploading artifacts, completed, failed.
- Avoid blank waiting periods.
- Render assistant messages as markdown.
- Failed run events appear inline in red.

Tool call behavior:

- Collapsed state shows tool name and status, for example `literature_research`, `search_pdb`, `run_proteina`, `run_chai`, `run_scorers`.
- Expanded state shows parsed parameters, compact output, timestamps, errors, and artifact links.
- Full raw output is available through artifact links when saved.

Mol* behavior:

- Load one selected structure artifact from a signed URL.
- Support "add file to context" in v1.
- Treat residue or atom selection context as a follow-up unless Mol* exposes a simple selected-chain/residue payload during implementation without custom structure parsing.

Visual direction:

- Brutally simple, workspace-first, and legible.
- Avoid nested cards, marketing heroes, gradient decoration, and ornamental dashboards.
- Use restrained color and stable panel geometry.
- Optimize for scanning repeated runs and debugging failures.

## Error Handling

Run state transitions:

```text
queued -> starting -> running -> completed
queued -> starting -> running -> failed
queued -> cancelled
```

Every failure writes:

- `run.status = "failed"`
- `run.errorSummary`
- a `run_error` event with structured detail

Expected failure classes:

- Missing environment or configuration.
- Modal sandbox creation failure.
- Model/provider failure.
- Tool HTTP failure from Proteina, Chai, or scorers.
- R2 upload failure.
- Neon write failure.

Tool failures should attach to the relevant tool row when possible. Worker-level failures become top-level run errors. If Neon writes fail, the worker fails the run because the UI state cannot be trusted.

Cancellation in v1 is best-effort and checked between major phases.

## Deployment

Create and link:

- Vercel project: `julia`
- Neon project: existing `Julia` project via `DATABASE_URL`
- Cloudflare R2 bucket: existing `julia`
- Modal app: new Julia worker app for agent/sandbox orchestration

Reuse existing external Modal tool endpoints:

- Proteina
- Chai
- protein interaction scoring
- quality scorers

Environment variables should include:

- Better Auth: `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`
- Database: `DATABASE_URL`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`
- Optional model fallback: Fireworks DeepSeek settings from `autopep2`
- Modal worker auth: shared webhook/signing secret
- Modal sandbox auth: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`
- R2: account ID, access key, secret key, bucket, optional public base URL
- Tool endpoints and API keys for Proteina, Chai, and scorers

## Testing

Keep verification bounded.

Next app:

- `bun run typecheck`
- `bun run check`
- focused route/component tests once the relevant test harness exists

Worker:

- Unit tests for event normalization.
- Unit tests for artifact path extraction.
- Unit tests for R2 key generation and dedupe.
- Unit tests for context hydration.
- Dry-run worker mode that emits fake token, tool, and artifact events without live protein tool calls.

Integration:

- Deployed dry-run smoke test through UI.
- One live protein-design canary only when explicitly enabled and envs are wired.

## Out Of Scope For V1

- Tree-mode execution.
- Long-lived per-project Modal sandbox filesystem.
- Automatic background filesystem watcher.
- Bulk R2 mounting into every run.
- Advanced Mol* selection visualization or tree-linked structure highlighting.
- Collaborative editing, billing, permissions beyond project ownership, and public sharing.
- Full old Autopep feature parity.

## Acceptance Criteria

- A user can create an account with email/password and sign in.
- A signed-in user sees the Julia workspace, not a landing page.
- A user can send a general chat message and see streamed assistant text.
- A user can ask for protein binder generation and see the single-pass workflow start.
- Tool rows appear in the chat panel, collapsed by default and expandable for parameters/output.
- Important tool-return artifacts are uploaded to R2 and indexed in Neon during execution.
- A final scan uploads missed allowed output files at run completion or failure.
- The right panel shows project artifacts from Neon.
- Clicking a structure artifact opens it in Mol* from a signed URL.
- A file can be added to chat context and hydrated into a later run.
- Residue-level Mol* context is not required for v1, but the data model can store it when available.
- Failed runs show visible red chat errors and leave enough event history to debug.
- The app can be deployed as Vercel project `julia` and the worker as a Julia Modal app.
