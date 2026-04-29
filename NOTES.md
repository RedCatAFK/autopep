UI ideas:

- Chatbot in the middle
- Visualiser window (collapsible) for showing/visualising PyMol files that are used as input
- Tree-searching codex progress working hard
- Anthropic type spinner with spinner verbs (find in file)

Current focus: establish agent orchestration architecture, and first task is to ensure the agent can successfully search PDB/literature, select top-k structures, and prepare target artifacts that can feed into generation tools.

Workflow:

Main model/chatbot: GPT 5.5 with OpenAI agent tooling and the life-science-research plugin.
Chatbot input: "Generate protein to bind to X"

1. Search PDB/literature such as bioRxiv via life-sciences plugin skills, deep research, or tools.
2. Select top-k structures.
3. Feed prepared target structure into NVIDIA Proteina Complexa via Modal for candidate generation.
   1. ProteinMPNN or equivalent may be used where sequence extraction/design is needed.
   2. Chai-1 can fold amino-acid sequences into predicted structures.
4. Run parallel scoring once scoring functions are implemented.
   1. Boltz-style binding affinity scoring.
   2. ESM-2 qualitative scoring or a trained linear classifier for safety/plausibility.
   3. Free-field energy scoring or other off-the-shelf model.
5. Pass results back to the model.
   1. Energy scores.
   2. Proteina generation metadata.
   3. 3D structures as artifacts/queryable context.
6. Next generation.
   1. Give a set of known moves.
   2. Take best sequence from prior generation and call `mutate_sequence()`.
   3. Modify the best prior structure/sequence with constrained mutations to stay grounded.
   4. Use mutated sequence or structure as warm-start point.
   5. Repeat from generation/scoring.

Example actions:

- "Find similar proteins on PDB"
- "Search literature about this protein on bioRxiv"
- "Fold and visualise this protein"

Notes:

- Preserve found PDB files and useful residues.
- Mix cold-start data with existing inhibitors for grounding and exploration.
- Validate the pipeline for PDB in -> suggest mutations -> PDB back in.
- Mol* for protein 3D visualisation, matching the PDB viewer family.
- Cursor for biologists, but do not say it explicitly.
- Biologically plausible 3D visualization via image generation where useful.
- Automate exploration and reduce state space into human-comprehensible steps.
- Support human-driven and AI-driven steering.
- Directed search of candidates.
- Business proposition: orchestration layer that stitches existing models and datasets together.
- Built on existing models and datasets first; train our own foundation models after scaling.
- Keep modularity by design.
