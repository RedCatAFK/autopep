# Chai-1 Modal Inference

HTTP inference endpoint for Chai-1 on Modal. It accepts FASTA input, runs Chai-1 without MSA or template search, and returns ranked CIF files as JSON strings. PDB conversion is still available under an explicit flag.

## Files

- `modal_app.py`: Modal app, GPU image, auth, model-volume warmup, inference endpoint, CIF output, optional PDB conversion, optional 3Dmol.js viewer HTML.
- `request_chai.py`: Local client script for sending FASTA/sequence requests, saving CIFs, and optionally writing HTML visualizations.

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
cat > input.fasta <<'EOF'
>protein|name=test
MSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW
EOF

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
    "seed": 42,
    "include_pdb": false,
    "include_viewer_html": false
  }'
```

Response shape:

```json
{
  "format": "cif",
  "count": 5,
  "cifs": [
    {
      "rank": 1,
      "filename": "rank_1_pred.model_idx_0.cif",
      "cif": "data_...",
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

Set `"include_pdb": true` in the JSON body if the caller also wants PDB strings. Set `"include_viewer_html": true` if the caller wants each structure to include a standalone 3Dmol.js HTML viewer.

## Python Client

The client uses `requests`:

```bash
python -m pip install requests
```

From a raw sequence:

```bash
python request_chai.py \
  --url "$CHAI_MODAL_URL" \
  --api-key "$CHAI_API_KEY" \
  --sequence MSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW \
  --name test \
  --output-dir chai_outputs \
  --visualize
```

From an existing FASTA:

```bash
python request_chai.py \
  --url "$CHAI_MODAL_URL" \
  --api-key "$CHAI_API_KEY" \
  --fasta-file input.fasta \
  --output-dir chai_outputs \
  --visualize
```

The client writes:

- `response.json`
- ranked `.cif` files
- ranked `.pdb` files if `--include-pdb` is passed
- ranked `.html` 3Dmol.js viewers if `--visualize` is passed. The viewer HTML loads 3Dmol.js from `https://3Dmol.org`.

## Notes

- The endpoint scales to zero with `min_containers=0`.
- The configured GPU is `L40S`; change `GPU` in `modal_app.py` if needed.
- CIF is the primary output format. PDB conversion uses `gemmi` and is intended only for downstream tools that still require PDB.
