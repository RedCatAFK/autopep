# Autopep Agent Orchestration

Last checked against Modal docs: 2026-04-28.

## Goal

The first orchestration milestone is a repeatable discovery run that takes a
plain-language target objective, searches PDB and literature, ranks the top-k
relevant protein structures, downloads canonical mmCIF structure files, derives
PDB files only when needed for Proteina-Complexa compatibility, and syncs both
progress and important artifacts into Neon so the T3 frontend can render status
and Mol* structure views.

The model executor is a Codex harness running `gpt-5.5` with OpenAI's
`life-science-research` plugin enabled. Shell-based research tools run inside
Modal Sandboxes, not inside the web application process.

## Current Persistence Boundary

Neon is the UI-facing source of truth:

- `autopep_project`: user-owned project and target objective.
- `autopep_project_workspace`: Modal app, shared Volume, per-project workspace
  root, active sandbox, and optional snapshot metadata.
- `autopep_agent_run`: one Codex discovery run for a project.
- `autopep_agent_event`: ordered append-only event stream for live progress.
- `autopep_protein_candidate`: ranked structure candidates, usually from RCSB
  PDB entries.
- `autopep_literature_hit`: literature evidence used in ranking.
- `autopep_artifact`: durable artifacts. Canonical mmCIF files and derived PDB
  compatibility files are stored as `content_text` in Neon and also keep their
  Modal Volume path for worker reuse.

The project workspace is a directory in the shared Modal Volume
`autopep-project-workspaces`. Store paths in Neon as Volume-relative paths so
workers can resolve them from different mount points:

```text
/projects/{project_id}/
  manifest.json
  search/
    pdb_results.json
    literature_hits.json
    ranking_inputs.json
  candidates/
    rank_001_{pdb_id}.json
  structures/
    rank_001_{pdb_id}.cif
    rank_001_{pdb_id}.pdb
  proteina/
    input/{run_id}/target.pdb
  logs/
    codex-harness.jsonl
```

The discovery Sandbox mounts the Volume at `/workspace/autopep`, so the full
discovery path is `/workspace/autopep/projects/{project_id}/...`. The Proteina
app mounts the same Volume at `/autopep`, so the same artifact resolves to
`/autopep/projects/{project_id}/...`. Per-project isolation is handled by paths
and database ownership checks.

## Modal Design Choices

Modal Sandboxes are the right execution primitive for plugin scripts because
they are secure containers for arbitrary or untrusted code and support direct
command execution. When spawned outside a Modal container, a Sandbox is created
under a Modal App; the controller should keep the Sandbox `object_id` in
`autopep_agent_run.modal_sandbox_id`.

Use a Modal Volume for persisted project state rather than treating the Sandbox
filesystem as canonical. Modal's filesystem APIs are convenient for control
files and copying files in/out during execution, but the docs recommend Volumes
for data reused by many Sandboxes. Prefer a v2 Volume for this workspace because
Modal documents an explicit `sync` command for committing intermediate Sandbox
writes before termination.

Filesystem snapshots are useful for debugging or resuming a configured agent
environment, but they should not replace the Volume plus Neon artifact store.
Snapshot IDs can be recorded in `filesystem_snapshot_image_id` fields.

Relevant docs:

- [Modal Sandboxes](https://modal.com/docs/guide/sandboxes)
- [Sandbox filesystem access](https://modal.com/docs/guide/sandbox-files)
- [Modal Volumes](https://modal.com/docs/guide/volumes)
- [Sandbox snapshots](https://modal.com/docs/guide/sandbox-snapshots)

## Discovery Run Contract

Input:

- `project_id`
- `objective`, for example "Generate a protein binder to X"
- `top_k`, default `5`

Required harness phases:

1. `intake`: restate objective and identify target entity strings.
2. `entity_normalization`: resolve target aliases, UniProt IDs, organism, and
   known complex/ligand context.
3. `pdb_search`: use the life-science plugin's RCSB PDB and UniProt-oriented
   skills, with shell helpers executed in Modal when needed.
4. `literature_search`: use biorXiv, PubMed/PMC, and related literature skills.
5. `ranking`: rank structure candidates using target match, biological relevance,
   structure quality, chain suitability, known binding or inhibition context,
   and literature support.
6. `pdb_download`: download top-k mmCIF files to the project workspace. The
   phase name is retained for now because the data source is RCSB PDB.
7. `artifact_sync`: hash mmCIF files, upload important files to Neon
   `autopep_artifact.content_text`, retain Modal paths, and derive validated PDB
   artifacts for candidates selected for Proteina-Complexa.
8. `ready_for_complexa`: create or identify the derived PDB artifact to pass to
   Proteina-Complexa while keeping the mmCIF artifact canonical.

Ready gate:

- At least one `autopep_protein_candidate` exists for the run.
- Rank 1 has a canonical `autopep_artifact` with `type = 'mmcif'`,
  `storage_kind = 'neon'`, `content_text` populated, `content_sha256`
  populated, and `modal_path` pointing at the Volume-relative workspace copy.
- Rank 1 has a derived `autopep_artifact` with `type = 'pdb'` when
  Proteina-Complexa still requires PDB input. Its metadata should include
  `sourceArtifactId` pointing to the canonical mmCIF artifact.
- A final `autopep_agent_event` has phase `ready_for_complexa`.

## Event Sync

The frontend should initially poll `autopep.listRunEvents` with the last seen
`sequence`. Events are ordered per run by `(run_id, sequence)` so the UI can
incrementally render a timeline without rereading logs. A later SSE or WebSocket
transport can sit on top of the same table without changing the harness
contract.

The harness should append events at every phase transition and after each major
artifact write. Raw stdout/stderr can remain in the Modal workspace unless it is
short enough to store as a log artifact.

## Proteina-Complexa Handoff

The existing `tools/proteina-complexa` app mounts fixed Modal Volumes. The next
implementation step should update that app to also mount
`autopep-project-workspaces` read-only, or copy the selected derived PDB
artifact from Neon into `proteina-complexa-data` before invoking
`design_binder`.

The handoff should pass a database artifact ID, not a loose file path. The
worker can resolve that ID to:

- Neon mmCIF text for display and deterministic retry.
- Derived PDB text for Proteina-Complexa compatibility.
- Modal `modal_path` for GPU-side reads.
- Ranking metadata and literature rationale for prompt/context provenance.

## Codex Harness Prompt Boundary

The harness should be instructed to:

- Use the `life-science-research` router first, then route to `rcsb-pdb`,
  `uniprot`, `biorxiv`, `ncbi-entrez`, and `ncbi-pmc` skills as needed.
- Execute shell/Python helpers only through the Modal Sandbox.
- Never treat a PDB ID as selected until the mmCIF file has been downloaded,
  parsed enough to verify it is mmCIF-format text, hashed, and synced to Neon.
  For Proteina handoff, also verify the derived PDB file before marking the run
  `ready_for_complexa`.
- Record concise selection rationales and source URLs for every ranked
  candidate.
- Stop the initial milestone once the ready gate is satisfied; Proteina
  generation is the next stage.
