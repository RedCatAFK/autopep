# Autopep E2E Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current Autopep research workspace usable end to end for target Q&A, PDB/literature retrieval, CIF artifact access, and Mol* visualization.

**Architecture:** Keep the existing Next.js/tRPC/Drizzle worker architecture. Fix the environment and schema path first, then close any narrow frontend/API gaps needed for the local user flow.

**Tech Stack:** Next.js 16, React 19, tRPC 11, Drizzle/Postgres, Better Auth, Cloudflare R2/S3 APIs, Mol*, Vitest, Bun.

---

## File Structure

- Inspect/modify `autopep/drizzle.config.ts`: ensure Drizzle migrations include Autopep domain tables.
- Inspect/possibly regenerate `autopep/drizzle/*.sql` and `autopep/drizzle/meta/*.json`: keep schema snapshots aligned with the table filter.
- Inspect/modify `autopep/next.config.js`: silence the Next/Turbopack workspace-root warning if it affects local development.
- Inspect/modify `autopep/src/server/api/routers/workspace.ts`: add durable read endpoints only if the current workspace payload cannot support Q&A, candidates, artifacts, and download URLs.
- Inspect/modify `autopep/src/app/_components/autopep-workspace.tsx`: map any new workspace fields and selected-artifact state.
- Inspect/modify `autopep/src/app/_components/workspace-shell.tsx`: expose candidate filtering/sorting, artifact download affordance, and research/Q&A trace without changing the larger visual direction.
- Inspect/modify `autopep/src/app/_components/molstar-viewer.tsx`: verify CIF URL loading and nonblank fallback behavior.
- Inspect/modify `autopep/src/server/agent/retrieval-pipeline.ts`: verify direct runner emits literature/PDB events, candidates, source CIF artifacts, and Proteina-ready state.
- Use existing tests in `autopep/src/server/agent/*.test.ts` and `autopep/src/server/artifacts/*.test.ts`; add focused tests only for changed behavior.

## Task 1: Root-Cause The Schema Failure

- [ ] **Step 1: Confirm current symptom**

Run the app path or tRPC call and confirm the error references `autopep_project`.

- [ ] **Step 2: Compare schema and migration config**

Read `autopep/src/server/db/schema.ts`, `autopep/drizzle.config.ts`, and generated migration SQL. Confirm whether `autopep_*` tables exist in migrations but are excluded by config.

- [ ] **Step 3: Verify database migration state**

Use Drizzle or Neon to check whether the connected database has `autopep_project`, `autopep_agent_run`, `autopep_agent_event`, `autopep_target_entity`, `autopep_protein_candidate`, and `autopep_artifact`.

- [ ] **Step 4: Fix the setup path**

If the table filter excludes domain tables, update `autopep/drizzle.config.ts` so future generation/migration includes `autopep_*`.

- [ ] **Step 5: Apply schema only after confirmation**

Run the existing generated migrations or prepare a Neon migration, then verify the tables exist.

## Task 2: Verify Authenticated Workspace Creation

- [ ] **Step 1: Open `http://localhost:3000`**

Use Browser/Playwright to inspect the local app.

- [ ] **Step 2: Sign in with a local test account**

Create or use a development-only account after action-time confirmation.

- [ ] **Step 3: Create a run**

Submit `Design a protein binder for SARS-CoV-2 spike RBD` and confirm the app creates a project and queued run without tRPC errors.

## Task 3: Execute The Retrieval Runner

- [ ] **Step 1: Run direct worker path**

Use `bun run worker:cif --once` or a run-specific worker invocation, depending on created run state.

- [ ] **Step 2: Verify durable outputs**

Confirm the run has events, target entities, ranked candidates, an artifact row, and a ready candidate.

- [ ] **Step 3: Handle external-service failures narrowly**

If RCSB, PubMed, or R2 fails, preserve partial state and show a useful failure event rather than masking the error.

## Task 4: Close UI Gaps

- [ ] **Step 1: Verify research/Q&A trace**

The assistant area must show enough event detail to answer what was searched, what was found, and why a candidate was selected.

- [ ] **Step 2: Verify candidate sorting/filtering**

The candidate area must support at least rank, score/readiness, and method/resolution visibility. Add lightweight controls only if absent.

- [ ] **Step 3: Verify CIF download/access**

Artifacts must expose a download/open affordance when a signed or public URL is available.

- [ ] **Step 4: Verify Mol***

The viewer must receive the selected artifact URL and show a meaningful loading/error/ready state.

## Task 5: Final Verification

- [ ] **Step 1: Run typecheck**

Run `bun run typecheck`.

- [ ] **Step 2: Run tests**

Run `bun run test`.

- [ ] **Step 3: Run Biome**

Run `bun run check`; fix formatter-only issues in touched files.

- [ ] **Step 4: Browser E2E**

Verify sign-in, run creation, worker completion, candidate display, artifact access, and Mol* behavior in the local browser.

