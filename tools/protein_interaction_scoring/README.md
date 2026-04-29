# Protein Interaction Scoring Server

HTTP API for batched protein-protein interaction scoring on Modal. The service returns two computational indicators when inputs are available:

- D-SCRIPT sequence-based interaction probability from `protein_a.sequence` and `protein_b.sequence`.
- PRODIGY structure-based predicted binding affinity from a supplied PDB or mmCIF complex.

PRODIGY cannot score sequence-only pairs. If a request omits `structure`, the API returns a D-SCRIPT score when possible and marks PRODIGY unavailable for that item.

All endpoints require an API key. For this workspace deployment the test key is `password123`; send it as either `X-API-Key: password123` or `Authorization: Bearer password123`.

## Layout

```text
protein_scoring_server/
  modal_app.py
  server.py
  scorers/
    dscript_scorer.py
    prodigy_scorer.py
    schemas.py
    utils.py
tests/
  test_batch_api.py
  test_schemas.py
```

## API

### `POST /score_batch`

JSON endpoint for clients that already have base64-encoded structure content.

```json
{
  "items": [
    {
      "id": "pair_001",
      "protein_a": {
        "name": "target_or_chain_a",
        "sequence": "MKWVTFISLL"
      },
      "protein_b": {
        "name": "binder_or_chain_b",
        "sequence": "GSHMASMTGG"
      },
      "structure": {
        "format": "pdb",
        "content_base64": "BASE64_PDB_OR_MMCIF",
        "chain_a": "A",
        "chain_b": "B"
      }
    }
  ],
  "options": {
    "run_dscript": true,
    "run_prodigy": true,
    "temperature_celsius": 25.0,
    "fail_fast": false
  }
}
```

The response preserves item ordering and returns per-item `dscript`, `prodigy`, `aggregate`, `errors`, and `warnings` fields. A syntactically valid batch returns HTTP 200 even when individual items are partial or failed, unless `fail_fast` is true.

### `POST /score_batch_upload`

Multipart endpoint for direct `.pdb`, `.cif`, or `.mmcif` uploads. Send a JSON `payload` form field plus one or more files. The payload can omit `structure.content_base64`; the server will attach the uploaded file by matching `structure.file_field`, the item ID, or the uploaded filename.

```bash
curl -X POST "http://localhost:8000/score_batch_upload" \
  -H "X-API-Key: password123" \
  -F 'payload={
    "items": [
      {
        "id": "pair_001",
        "protein_a": {"name": "chain_a"},
        "protein_b": {"name": "chain_b"},
        "structure": {
          "file_field": "pair_001",
          "chain_a": "A",
          "chain_b": "B"
        }
      }
    ]
  }' \
  -F "pair_001=@complex.pdb"
```

When `protein_a.sequence` or `protein_b.sequence` is missing, preprocessing tries to extract the sequence from the selected structure chains before D-SCRIPT runs.

### `GET /health`

```json
{
  "status": "ok",
  "dscript_loaded": true,
  "prodigy_available": true,
  "gpu_available": true
}
```

## Aggregate Indicator

The aggregate label is deliberately rule-based and is not a physical binding probability:

- `likely_binder`: D-SCRIPT probability >= 0.7 and PRODIGY delta G <= -7.0 kcal/mol.
- `possible_binder`: D-SCRIPT probability >= 0.5 or PRODIGY delta G <= -5.0 kcal/mol.
- `unlikely_binder`: D-SCRIPT probability < 0.5 and PRODIGY delta G > -5.0 kcal/mol.
- `insufficient_data`: one or both scorers are unavailable.

Always inspect the raw D-SCRIPT probability and PRODIGY predicted delta G alongside this label.

## Local Development

Install test/runtime dependencies in an environment that supports the scientific packages:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install pytest httpx
python3 -m pytest
```

Run the FastAPI app locally:

```bash
uvicorn protein_scoring_server.server:app --reload
```

The API tests use mock scorer classes, so they do not require a GPU, D-SCRIPT model download, or PRODIGY binary.

## Modal Deployment

Deploy:

```bash
modal deploy protein_scoring_server/modal_app.py
```

The Modal app requests a T4 GPU, installs `requirements.txt`, and serves the FastAPI app through `@modal.asgi_app`. The container is kept warm for a longer scaledown window to reduce repeated model/tool startup cost.

## Scorer Implementation Notes

D-SCRIPT and PRODIGY now share a preprocessing pass before scoring:

- Decodes or accepts uploaded `.pdb`, `.cif`, and `.mmcif` structures.
- Infers `chain_a` and `chain_b` from the first two protein chains when omitted.
- Extracts chain sequences from the structure to fill missing D-SCRIPT inputs.
- Writes a protein-only, first-model PDB copy for PRODIGY when possible.
- Removes waters, ligands, non-protein residues, later models, and non-primary alternate locations from that preprocessed copy.
- Falls back to the uploaded structure if sanitization is unavailable, with warnings.

D-SCRIPT defaults to an in-process Python backend. On container startup it attempts to load `DSCRIPTModel.from_pretrained(DSCRIPT_MODEL)` once and reuse that model for later requests. If that backend is unavailable and `DSCRIPT_BACKEND=auto`, it falls back to a batch CLI flow:

1. Write one FASTA containing all requested protein sequences.
2. Write one no-header TSV containing all candidate pairs.
3. Run `dscript embed`.
4. Run `dscript predict`.
5. Parse the resulting TSV and map scores back to input item IDs.

Set `DSCRIPT_BACKEND=python` to require the reusable in-process backend, or `DSCRIPT_BACKEND=cli` to force the CLI wrapper.

PRODIGY is invoked per structure with the `prodigy` CLI from `prodigy-prot`. When chain IDs are supplied, they are passed via `--selection`. When they are missing, the wrapper tries to infer protein chains and adds a warning.

## Safety

- Protein sequences are normalized to uppercase with whitespace removed.
- Standard amino acids are accepted. `X`, `U`, `B`, and `Z` are accepted with warnings.
- Other residue codes are rejected by request validation.
- Structure content is decoded from base64 into a temporary request directory.
- Direct uploads are read only into request-local temporary files.
- Structure payloads are capped at 25 MB decoded by default.
- User filenames are never trusted or used.
- Logs include item IDs, sequence lengths, and hashes, but not full sequences or structure contents.
