# Chai-1 Inference API Integration Guide

This guide is for teams integrating with the Chai-1 Modal HTTP endpoint.

Endpoint base URL:

```text
https://autopep--chai-1-inference-fastapi-app.modal.run
```

## What This API Does

The API predicts 3D protein structures from amino-acid sequences.

For non-bio context:

- A protein sequence is a string of amino-acid letters, for example `MSEQNNTEMTFQ...`.
- The API sends that sequence to Chai-1, a structure-prediction model.
- The model returns one or more ranked 3D structure predictions.
- The primary returned structure format is CIF/mmCIF, a text file format used by structural biology tools.
- A browser UI can render the returned CIF text with a molecular viewer such as 3Dmol.js, Mol*, or NGL.

This endpoint is intended for inference only. It does not store user submissions, expose job history, or provide a queue/status API.

## Authentication

Every request must include the API key configured in Modal Secrets.

Preferred header:

```http
X-API-Key: <api-key>
```

Also accepted:

```http
Authorization: Bearer <api-key>
Authorization: Basic <base64(username:api-key)>
```

Do not expose the API key directly in browser code. Call this endpoint from your backend, or through a server-side proxy that owns the key.

## Endpoints

### GET `/health`

Checks whether the deployed endpoint is reachable and the API key is accepted.

Request:

```bash
curl -i \
  -H "X-API-Key: $CHAI_API_KEY" \
  "https://autopep--chai-1-inference-fastapi-app.modal.run/health"
```

Success response:

```json
{
  "status": "ok"
}
```

### POST `/predict`

Runs Chai-1 structure prediction.

The endpoint accepts either:

- JSON body with a `fasta` field
- raw FASTA text body

JSON is recommended for product integration because it allows optional settings.

## Input Format

### FASTA

The required biological input is FASTA text.

A FASTA record has:

- one header line starting with `>`
- one or more sequence lines after it

For a single protein:

```text
>protein|name=test
MSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW
```

The current implementation validates only that the FASTA is non-empty, starts with `>`, and is under `128 KiB`. Chai-1 performs deeper biological parsing.

Use uppercase amino-acid sequences where possible. Avoid spaces inside the sequence.

## Recommended Request

```bash
curl -X POST \
  "https://autopep--chai-1-inference-fastapi-app.modal.run/predict" \
  -H "X-API-Key: $CHAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fasta": ">protein|name=test\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n"
  }'
```

JavaScript backend example:

```js
const response = await fetch(
  "https://autopep--chai-1-inference-fastapi-app.modal.run/predict",
  {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": process.env.CHAI_API_KEY
    },
    body: JSON.stringify({
      fasta: ">protein|name=test\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n"
    })
  }
);

if (!response.ok) {
  throw new Error(`Chai API failed: ${response.status} ${await response.text()}`);
}

const result = await response.json();
```

Python example:

```python
import os
import requests

response = requests.post(
    "https://autopep--chai-1-inference-fastapi-app.modal.run/predict",
    headers={"X-API-Key": os.environ["CHAI_API_KEY"]},
    json={
        "fasta": ">protein|name=test\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n"
    },
    timeout=3600,
)
response.raise_for_status()
result = response.json()
```

## JSON Request Contract

All fields except `fasta` are optional.

```json
{
  "fasta": ">protein|name=test\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n",
  "num_trunk_recycles": 3,
  "num_diffn_timesteps": 200,
  "num_diffn_samples": 5,
  "seed": 42,
  "include_pdb": false,
  "include_viewer_html": false
}
```

Field reference:

| Field | Type | Default | Allowed | Notes |
| --- | --- | --- | --- | --- |
| `fasta` | string | required | max `128 KiB`, must start with `>` | FASTA text containing the sequence(s). |
| `num_trunk_recycles` | integer | `3` | `1` to `20` | More recycles can improve refinement but increases runtime. |
| `num_diffn_timesteps` | integer | `200` | `1` to `1000` | More timesteps can improve sampling but increases runtime. |
| `num_diffn_samples` | integer | `5` | `1` to `10` | Number of candidate structures to generate. Response count usually matches this. |
| `seed` | integer | `42` | `0` to `2147483647` | Controls stochastic sampling. Same input/settings/seed should be more reproducible. |
| `include_pdb` | boolean | `false` | `true` or `false` | Adds PDB text in addition to CIF. CIF remains the primary format. |
| `include_viewer_html` | boolean | `false` | `true` or `false` | Adds standalone 3Dmol.js HTML strings to the JSON response. Usually better generated client-side instead. |

Model settings fixed by the server:

| Setting | Value |
| --- | --- |
| MSA search | disabled |
| Template search | disabled |
| ESM embeddings | enabled |
| Primary output format | CIF/mmCIF |

## Raw FASTA Request

Raw FASTA is useful for simple command-line testing.

```bash
curl -X POST \
  "https://autopep--chai-1-inference-fastapi-app.modal.run/predict" \
  -H "X-API-Key: $CHAI_API_KEY" \
  -H "Content-Type: text/plain" \
  --data-binary $'>protein|name=test\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n'
```

Raw FASTA does not allow optional JSON fields, so defaults are used.

## Success Response Contract

The response is JSON.

```json
{
  "format": "cif",
  "count": 5,
  "request_id": "0b67f9839a0d4f1aa67fd626f2debf44",
  "cifs": [
    {
      "rank": 1,
      "filename": "rank_1_pred.model_idx_2.cif",
      "cif": "data_pred_model_idx_2\n#\n...",
      "aggregate_score": 0.82,
      "mean_plddt": 78.3
    }
  ],
  "parameters": {
    "num_trunk_recycles": 3,
    "num_diffn_timesteps": 200,
    "num_diffn_samples": 5,
    "seed": 42,
    "use_msa": false,
    "use_templates": false,
    "use_esm_embeddings": true,
    "include_pdb": false,
    "include_viewer_html": false
  },
  "timings": {
    "inference_seconds": 123.45,
    "packaging_seconds": 0.12,
    "total_seconds": 124.01
  }
}
```

Top-level fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | string | Always `"cif"` for the primary structure output. |
| `count` | integer | Number of returned candidate structures. |
| `request_id` | string | Server-generated ID useful for correlating UI errors with Modal logs. |
| `cifs` | array | Ranked candidate structures. Best candidate is first. |
| `parameters` | object | Effective settings used for this request. |
| `timings` | object | Runtime timings in seconds. |

Each `cifs[]` item:

| Field | Type | Meaning |
| --- | --- | --- |
| `rank` | integer | Rank order, starting at `1`. Use rank `1` as the default displayed result. |
| `filename` | string | Suggested filename if saving the CIF. |
| `cif` | string | Full CIF/mmCIF text. This can be large. |
| `aggregate_score` | number or null | Chai ranking score. Higher is generally better for ranking outputs from the same request. |
| `mean_plddt` | number or null | Average confidence-like score. Higher generally means more confident local structure. |
| `pdb_filename` | string, optional | Present only when `include_pdb=true`. |
| `pdb` | string, optional | PDB text, present only when `include_pdb=true`. |
| `viewer_filename` | string, optional | Present only when `include_viewer_html=true`. |
| `viewer_html` | string, optional | Standalone 3Dmol.js HTML, present only when `include_viewer_html=true`. |

## Displaying Structures In A Web App

Recommended integration:

1. Call `/predict` from your backend.
2. Store or forward the returned `cifs[0].cif` string.
3. Render rank `1` by default.
4. Let advanced users switch between ranks if needed.
5. Use a browser molecular viewer that accepts CIF/mmCIF text.

3Dmol.js example:

```html
<div id="viewer" style="width: 100%; height: 500px;"></div>
<script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<script>
  const cifText = result.cifs[0].cif;
  const viewer = $3Dmol.createViewer("viewer", { backgroundColor: "white" });
  viewer.addModel(cifText, "cif");
  viewer.setStyle({}, { cartoon: { color: "spectrum" } });
  viewer.zoomTo();
  viewer.render();
</script>
```

For production UI work, generate the viewer in the frontend rather than asking the API for `include_viewer_html=true`. Returning viewer HTML is mainly useful for debugging and manual inspection.

## Error Responses

Common statuses:

| Status | Meaning | Typical cause |
| --- | --- | --- |
| `200` | Success | Prediction completed. |
| `400` | Invalid request | Empty FASTA, body is not UTF-8, invalid optional field type/range. |
| `401` | Unauthorized | Missing or incorrect API key. |
| `422` | Request shape rejected before model code runs | Usually incorrect content type or server route/deployment mismatch. |
| `500` | Server error | Model/runtime failure. Check Modal logs with `request_id` if available. |
| `504` or client timeout | Long-running request exceeded caller/proxy timeout | Increase client timeout or add an async job wrapper in your own backend. |

Example `400`:

```json
{
  "detail": "FASTA input must start with a FASTA header line beginning with '>'"
}
```

Example `401`:

```json
{
  "detail": "Missing or invalid API key"
}
```

## Runtime Expectations

This is a GPU-backed endpoint that scales to zero. A request can include:

- cold start time if no container is running
- model asset check time
- Chai inference time
- response packaging time

The response includes `timings.total_seconds`, but client-side elapsed time may be higher because of cold start, network transfer, and JSON parsing. CIF strings can be large.

Use a long HTTP timeout. The local test script uses `3600` seconds.

## Operational Notes

- The deployed Modal endpoint scales to zero between requests.
- Model weights are stored in the Modal Volume `chai-1-models`.
- The implementation intentionally disables MSA and template search.
- Logs in Modal include request start/end, inference time, packaging time, and total time.
- The `request_chai.py` script is a testing toy for local/manual checks. Web applications should call the HTTP API directly from backend code.

## Minimal Backend Handler Pattern

For a production web app, prefer this pattern:

1. Browser submits a sequence to your backend.
2. Backend validates basic input length and character set.
3. Backend creates FASTA text.
4. Backend calls this Modal API with `X-API-Key`.
5. Backend returns selected response fields to the browser.

Do not put `CHAI_API_KEY` in browser JavaScript.

Example backend payload builder:

```js
function toProteinFasta(sequence, name = "query") {
  const cleanSequence = sequence.replace(/\s+/g, "").toUpperCase();
  if (!cleanSequence) {
    throw new Error("Sequence is empty");
  }
  return `>protein|name=${name}\n${cleanSequence}\n`;
}
```
