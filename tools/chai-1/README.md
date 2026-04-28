# Chai-1 Modal Inference

HTTP inference endpoint for Chai-1 on Modal. It accepts FASTA input, runs Chai-1 without MSA or template search, and returns ranked PDB files as JSON strings.

## Files

- `modal_app.py`: Modal app, GPU image, auth, model-volume warmup, inference endpoint, CIF-to-PDB conversion.

## Modal Setup

Create the API key secret manually before deploying:

```bash
modal secret create chai-1-api-key CHAI_API_KEY='replace-with-your-api-key'
```

The app creates and uses a Modal Volume named `chai-1-models`. Chai weights, conformer data, and ESM weights are stored under `/models/chai-1` inside that Volume. On cold start, the app checks for the expected files before asking Chai to download anything.

Deploy:

```bash
cd tools/chai-1
modal deploy modal_app.py
```

Run locally on Modal during development:

```bash
cd tools/chai-1
modal serve modal_app.py
```

## HTTP API

Authentication accepts any of:

- `X-API-Key: <CHAI_API_KEY>`
- `Authorization: Bearer <CHAI_API_KEY>`
- `Authorization: Basic <base64(username:CHAI_API_KEY)>`

POST raw FASTA:

```bash
curl -X POST "$CHAI_MODAL_URL/predict" \
  -H "X-API-Key: $CHAI_API_KEY" \
  -H "Content-Type: text/plain" \
  --data-binary @input.fasta
```

POST JSON:

```bash
curl -X POST "$CHAI_MODAL_URL/predict" \
  -H "Authorization: Bearer $CHAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fasta": ">protein|name=example\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n",
    "num_trunk_recycles": 3,
    "num_diffn_timesteps": 200,
    "num_diffn_samples": 5,
    "seed": 42
  }'
```

Response shape:

```json
{
  "format": "pdb",
  "count": 5,
  "pdbs": [
    {
      "rank": 1,
      "filename": "rank_1_pred.model_idx_0.pdb",
      "pdb": "ATOM ...",
      "aggregate_score": 0.82,
      "mean_plddt": 78.3
    }
  ],
  "parameters": {
    "use_msa": false,
    "use_templates": false,
    "use_esm_embeddings": true
  }
}
```

Set `"include_cif": true` in the JSON body if the caller also wants Chai's native mmCIF output alongside each PDB string.

## Notes

- The endpoint scales to zero with `min_containers=0`.
- The configured GPU is `L40S`; change `GPU` in `modal_app.py` if needed.
- PDB conversion uses `gemmi`. For large complexes or entities that do not fit classic PDB constraints, use `"include_cif": true` and prefer the returned mmCIF.
