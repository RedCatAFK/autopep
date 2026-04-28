UI ideas: 

- Chatbot in the middle   
- Visualiser window (collapsible) for showing/visualising PyMol files that are used as input   
- Tree-searching codex progress working hard  
- Anthropic type spinner with spinner verbs (find in file)

**Workflow**:  
Main model (chatbot): GPT 5.5 with openai codex harness (fork from openai repo) and life-sciences-plugin ([https://github.com/openai/plugins/tree/main/plugins/life-science-research/skills](https://github.com/openai/plugins/tree/main/plugins/life-science-research/skills))   
Chatbot input: “Generate protein to bind to X”

1. Search for PDB/literature (biorXiv): (via skills from life-sciences plugin / deep research / tools)  
2. Select top-k  
3. Feed PyMol file into NVIDIA Proteina (inference via Modal) for candidate generation.  
   1. ProteinMPNN to get sequence from 3D structures outputted from Proteina  
   2. Chai-1 (most likely, without MSA) \> Boltz-1 \> ESMFold  
4. Proteina into parallel scoring  
   1. Boltz-1 which checks binding affinity  
   2. ESM-2 as a backbone for qualitative scoring (i.e. this will be a trained linear classifier for e.g. safety)  
   3. Free field energy scorer (off-the-shelf model)  
5. Pass info back to model   
   1. Energy scores (2x)   
   2. Proteina information (if any)   
   3. 3D structure (kept as a RAG type thing; data analysis with Bash / code execution)   
6. Next generation   
   1. Give a set of like known “moves”   
      1. E.g. take best sequence from prior generation and calls mutate\_sequence() (function that we write)   
      2. Modify the PyMol sequence of the best sequence from before (constrained mutation to stay grounded)  
      3. Mutated sequence is warm start point for Proteina model   
      4. Rinse repeat back to step 3

“Find similar proteins (on PDB)”  
“Search literature about this protein (on biorXiv)”  
“Fold and visualise this protein”

Enforce pdb \-\> pdb format (input and output is always a pdb file)

Found PDB files  
Useful residues

- Mix cold start data with existing inhibitors (entropy bonus from the cold start data) for the agent to then synthesise both de novo and known sources for grounding but also exploration 

Validate the pipeline for PDB in \-\> suggest mutations \-\> PDB back in. 

Mol\* for protein 3D visualisation (same one that PDB uses)

Cursor for Biologists (but we don’t say it)  
Biologically plausible 3d viz via image-gen  
Automate exploration; reduce state space into human comprehensible  
Human-driven vs AI-driven (human steering)

- Directed search of candidates  
- Business prop/value: orchestration layer that stitches a lot of frameworks together  
  - Built on top of existing models and datasets  
    - Cursor business model  
      - We will train our own foundation models after scaling  
    - But modularity by design