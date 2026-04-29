UI ideas: 
Chatbot in the middle 
Visualiser window (collapsible) for showing/visualising PyMol files that are used as input 
Tree-searching codex progress working hard
Anthropic type spinner with spinner verbs (find in file)

Flows:
Main model (chatbot): GPT 5.5-codex with openai codex harness (fork from openai repo) and life-sciences-plugin (https://github.com/openai/plugins/tree/main/plugins/life-science-research/skills) 
Chatbot input: “Generate protein to bind to X”

Current focus: establish agent orchestration architecture, and first task is to ensure the agent can successfully search for PDB/literature, select top-k and have a pymol ready to feed into proteina


Search for PDB/literature (biorXiv): (via deep research / tool / skills)
Select top-k
Feed PyMol file into NVIDIA Proteina (inference via Modal) for candidate generation.
ProteinMPNN to get sequence from 3D structures outputted from Proteina
Chai-1 (most likely, without MSA) > Boltz-1 > ESMFold
Proteina into parallel scoring
Boltz-1 which checks binding affinity
ESM-2 as a backbone for qualitative scoring (i.e. this will be a trained linear classifier for e.g. safety)
Free field energy scorer (off-the-shelf model)
Pass info back to model 
Energy scores (2x) 
Proteina information (if any) 
3D structure (kept as a RAG type thing; data analysis with Bash / code execution) 
Next generation 
Give a set of like known “moves” 
E.g. take best sequence from prior generation and calls mutate_sequence() (function that we write) 
Modify the PyMol sequence of the best sequence from before (constrained mutation to stay grounded)
Mutated sequence is warm start point for Proteina model 
Rinse repeat back to step 3


“Find similar proteins (on PDB)”
“Search literature about this protein (on biorXiv)”
“Fold and visualise this protein”

Enforce pdb -> pdb format (input and output is always a pdb file)

Cursor for Biologists (but we don’t say it)
Biologically plausible 3d viz via image-gen
Automate exploration; reduce state space into human comprehensible
Human-driven vs AI-driven (human steering)
Directed search of candidates
Business prop/value: orchestration layer that stitches a lot of frameworks together
Built on top of existing models and datasets
Cursor business model
We will train our own foundation models after scaling
But modularity by design




Found PDB files
Useful residues



Mix cold start data with existing inhibitors (entropy bonus from the cold start data) for the agent to then synthesise both de novo and known sources for grounding but also exploration 

Validate the pipeline for PDB in -> suggest mutations -> PDB back in. 



Mol* for protein 3D visualisation (same one that PDB uses)
