UI ideas: 
Chatbot in the middle 
Visualiser window (collapsible) for showing/visualising PyMol files that are used as input 
Tree-searching codex progress working hard
Anthropic type spinner 

Flows:
Main model (chatbot): GPT 5.5 with codex harness (fork from openai repo)
Chatbot input: “Generate protein to bind to X”
Search PDB/literature (biorXiv): deep research / tool
Select top-k
Feed PyMol file into NVIDIA Proteina (inference via Modal) for candidate generation.
ProteinMPNN to get sequence from 3D structures outputted from Proteina
Chai-1 (most likely, without MSA) > Boltz-1 > ESMFold
Proteina into parallel scoring
Boltz-1 which checks binding affinity
ESM-2 as a backbone for qualitative scoring (i.e. train linear classifier for e.g. safety)
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




