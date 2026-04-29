export const demoRecipeName = "One-loop 3CL-protease binder demo";

export const demoRecipeBody = `When the user asks to generate a protein binder for 3CL-protease:
1. Search preprint/literature evidence for SARS-CoV-2 Mpro / 3CLpro context.
2. Run a filtered PDB search for SARS-CoV-2 3C-like proteinase structures.
3. Select a high-confidence experimental target structure, defaulting to 6LU7 chain A when appropriate.
4. Call Proteina-Complexa to generate binder candidates.
5. Fold generated candidates with Chai-1.
6. Score target-candidate interactions with the protein interaction scoring endpoint.
7. Pick the strongest candidate for the MVP and stop after this one loop.
`;
