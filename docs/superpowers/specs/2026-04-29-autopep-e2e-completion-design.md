# Autopep E2E Completion Design

Date: 2026-04-29

## Scope

This pass finishes the current Autopep research-workspace milestone. A signed-in user should be able to ask basic target questions, start a target research run, see literature and PDB-search progress, inspect ranked and filterable PDB candidates, download CIF-backed artifacts, and visualize a selected protein in Mol*.

The milestone does not generate protein sequences, mutate proteins, run ProteinMPNN, run Proteina generation, score with Chai/Boltz, or implement iterative design loops.

## Approach

Keep the existing T3/Next, Better Auth, tRPC, Drizzle, Neon, R2, worker, and Mol* architecture. The immediate work is to make the already-planned vertical slice actually executable in local development and ready for deployment wiring.

The frontend remains workspace-first. It exposes a plain-English prompt surface, an assistant/research trace, ranked candidates, artifact actions, and the Mol* viewer. The server remains the owner of authenticated workspace state and creates durable agent runs. The worker remains the execution boundary for RCSB/PubMed retrieval and artifact persistence.

## Data Flow

1. User signs in and enters a target request or Q&A prompt.
2. The app creates a project and queued run through tRPC.
3. The runner claims the run and emits events while normalizing the target, searching PDB/literature, ranking candidates, downloading CIF, uploading/storing artifact metadata, and marking the top candidate ready.
4. The app polls workspace state, updates the research trace and candidate list, and passes the selected CIF URL to Mol*.
5. The user can inspect or download the CIF artifact and use the visible trace as the basic answer/literature-review surface.

## Debugging Focus

The observed blocker is that `workspace.getLatestWorkspace` queries `autopep_project`, but the connected database does not have that relation. Root-cause investigation should verify whether migrations were not run, whether the migration config excludes Autopep tables, or whether the app points at a different database/branch than expected. The fix should address the schema setup path, not hide the query error.

## Verification

Required checks:

- TypeScript typecheck.
- Vitest suite.
- Biome check or documented remaining formatter-only issues.
- Browser flow on `http://localhost:3000`: sign in, create/run a target request, observe research/PDB events, see ranked candidates, obtain a CIF artifact URL/download affordance, and see Mol* attempt to render the selected artifact.

