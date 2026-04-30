# autopep

> An AI research agent for protein design. Tell it what you want to bind to — it searches the literature, generates candidate structures, folds them, scores them, and iterates.

## Inspiration

Designing a novel protein today means weeks of stitching together half a dozen tools by hand: digging through PDB, pulling papers off bioRxiv, running structure generators on one GPU box, sequence designers on another, folding models on a third, and energy scorers on a fourth — then trying to remember what you tried two days ago.

We kept thinking about what Cursor did for code: it didn't replace the compiler, it just put a smart agent next to the developer and let it drive the boring parts. Computational biology has the same shape — an enormous toolchain, lots of state, and a tight inner loop. So we built **autopep**: a directed-search agent for protein engineering that biologists can actually steer.

## What it does

Give autopep a target ("design a peptide that binds to PD-L1") and it runs a full design loop:

1. **Searches PDB and the literature** — RCSB, PubMed, and bioRxiv clients pull relevant structures and prior art.
2. **Selects and prepares a target** — top-k structures are retrieved, preprocessed, and stored as artifacts the rest of the pipeline can warm-start from.
3. **Generates candidate backbones** with NVIDIA Proteina Complexa (3D structure generation, served on Modal).
4. **Folds and validates** sequences with Chai-1 (no MSA), with ESMFold-style fallbacks for cheap re-folds.
5. **Scores in parallel** — a Prodigy-based binding affinity scorer, D-SCRIPT for interaction prediction, and an ESM-2 backbone with trained linear classifier heads for qualitative checks (safety, expressibility, plausibility).
6. **Mutates and iterates** — the agent picks the best survivors, calls `mutate_sequence` for constrained edits, warm-starts Proteina from the mutated structure, and goes back to step 3.

The whole loop is visible. A Mol* viewer renders every candidate in 3D, an Anthropic-style spinner cycles through verbs like *Folding*, *Docking*, and *Reticulating*, the chat panel streams the agent's tool calls live, and a workspace rail keeps every run, candidate, and artifact addressable.

## How we built it

- **Agent core.** GPT-5.5 in an OpenAI agent harness with a domain toolbelt: `search_rcsb`, `search_pubmed`, `search_biorxiv`, `fold`, `score`, `mutate_sequence`, `visualize`. The runner lives on Modal so each tool invocation can fan out to its own GPU app.
- **Frontend.** Next.js 15 + React 19 on the T3 stack (tRPC, Drizzle, Tailwind v4, Biome). Better-auth + Neon Postgres for accounts, workspaces, and run history. Mol* embedded for live 3D viz.
- **ML inference.** Modal for serverless GPU. Each model is its own Modal app:
  - `proteina-complexa` — NVIDIA Proteina for backbone generation, with target preprocessing and warm-start support
  - `chai-1` — folding for designed sequences
  - `quality-scorers` — ESM-2 embeddings + trained classifier heads
  - `protein_interaction_scoring` — Prodigy + D-SCRIPT for affinity and interaction
  - `structure_vis` — PyMOL-driven snapshot rendering for comparison
- **Artifacts.** Cloudflare R2 holds the heavy stuff (CIF/PDB structures, generation outputs); Postgres holds the lineage so the agent can reason about its own search history across generations.
- **Streaming.** A custom event pipeline pushes tool calls, tool results, and partial model output to the browser in real time, rendered as a chat-stream timeline plus a candidates table that fills in as scores land.
- **Deploy.** Vercel for the web app, Modal for the GPU side, Neon for the database, R2 for artifacts.

## Challenges we ran into

- **Wiring six SOTA models into one coherent loop.** Each one has its own input format, GPU requirements, and quirks (Chai-1's MSA toggle alone ate an afternoon). Modal made this tractable but not free — every tool got its own container, requirements, and integration test suite.
- **Keeping the agent grounded.** Unconstrained mutation drifts off into nonsense fast. We had to hand the model a small, sharp set of "moves" (mutate within a window, splice from a known motif, warm-start from the previous best) instead of letting it freely rewrite sequences.
- **PDB → mutate → PDB roundtrip.** Validating that we could ingest a real PDB structure, design against it, and produce a structure the next stage could re-ingest required us to write target preprocessing, structure utils, and a smoke pipeline before any of the science was visible.
- **Making the search legible.** A multi-generation tree of folded candidates is a lot to look at. We collapsed it into the spinner + Mol* viewer + chat-stream + candidates table so a researcher can glance at the screen and know what's happening.
- **Auth migration mid-build.** We started on NextAuth and swapped to better-auth + Neon when we needed email login and a real Postgres for run history. Worth it, but the diff was not small.

## Accomplishments that we're proud of

- An end-to-end agentic loop that actually closes — search → generate → fold → score → mutate → repeat — without a human in the inner loop.
- Parallel scoring across multiple GPU models on Modal, so a generation finishes in minutes instead of hours.
- A UI that feels like a tool, not a demo: live tool-call streaming, embedded Mol* viewer, persistent workspaces, and a candidates table that scores update in place.
- The agent surfaces *biologically plausible* candidates with citations back to the papers and PDB entries it pulled, so a researcher can sanity-check the reasoning, not just the output.
- A clean tools/ subtree where every model integration is independently testable — `chai-1`, `proteina-complexa`, `protein_interaction_scoring`, `quality-scorers`, and `structure_vis` each have their own README, Modal app, and pytest suite.

## What we learned

- Orchestration is the product. The foundation models already exist and are getting better every month — the moat is the loop that ties them together and the UX that makes them steerable.
- Constrained generation beats clever generation. Giving the model a small set of well-typed moves produced better proteins than handing it a blank canvas.
- Parallelism unlocks taste. When scoring is cheap enough, you can afford to keep the top-k wide and let the agent compare instead of commit.
- Plumbing pays. The hours we spent on streaming, artifacts, and lineage early on are why a researcher can trust the output later.

## What's next for autopep

- **Our own foundation models.** We're using off-the-shelf weights today. Once we have run data at scale, we want to train protein models tuned for our search loop — modular by design, swappable per-target.
- **Wet-lab handoff.** Export top candidates as ordering-ready sequences for Twist / IDT, with the full provenance trail attached.
- **More targets, more modalities.** Antibodies, cyclic peptides, and binders for membrane proteins are next.
- **Team mode.** Shared workspaces, comparison views, and the ability for a collaborator to fork a search tree from any node.

## Repo layout

```
autopep/                 Next.js app, tRPC API, Drizzle schema, Mol* viewer
autopep/modal/           Agent runner + biology tools running on Modal
tools/chai-1/            Chai-1 folding service (Modal)
tools/proteina-complexa/ NVIDIA Proteina backbone generation (Modal)
tools/quality-scorers/   ESM-2 embeddings + trained classifier heads (Modal)
tools/protein_interaction_scoring/  Prodigy + D-SCRIPT scoring (Modal)
tools/structure_vis/     PyMOL-driven structure rendering and comparison
docs/                    Plans and design docs
```

## Built with

`gpt-5.5` · `openai-agent-sdk` · `next.js` · `react` · `typescript` · `tailwind` · `trpc` · `drizzle` · `better-auth` · `neon` · `cloudflare-r2` · `vercel` · `python` · `modal` · `nvidia-proteina-complexa` · `proteinmpnn` · `chai-1` · `esm-2` · `prodigy` · `d-script` · `pymol` · `mol-star` · `rcsb-pdb` · `pubmed` · `biorxiv`
