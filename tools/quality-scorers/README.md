# Quality Scorer Training

Modal jobs for the learned sequence quality scorers described in
`autpep_sequence_filter_spec.md`.

The training flow is split into two Modal apps:

- `esm2_embedding_app.py`: heavier `L40S` jobs that download data, download
  `facebook/esm2_t12_35M_UR50D`, and cache frozen ESM2 embeddings once.
- `head_training_app.py`: lighter `T4` jobs that train heads from cached
  embeddings.
- `inference_modal_app.py`: `T4` ASGI/FastAPI endpoint that loads ESM2 and the
  trained heads for FASTA scoring.

## Modal Volumes

The apps create and use:

- `quality-scorers-data`: raw downloads, normalized parquet files, embedding
  tables, and manifests.
- `quality-scorers-models`: ESM2 snapshot and trained head artifacts.

The ESM2 snapshot is stored under `/models/esm2/<model-key>`. Head artifacts are
stored under `/models/heads/<model-key>`.

## Run Sequence

Run from this directory:

```bash
cd tools/quality-scorers
```

Download the ESM2 checkpoint:

```bash
modal run esm2_embedding_app.py::download_esm2
```

Ingest all datasets into the data volume:

```bash
modal run esm2_embedding_app.py::ingest_all
```

Cache all ESM2 embeddings:

```bash
modal run esm2_embedding_app.py::embed_all
```

Train all heads from cached embeddings:

```bash
modal run head_training_app.py::train_all
```

List saved head artifacts:

```bash
modal run head_training_app.py::list_artifacts
```

If your Modal CLI does not print direct function return values, use the
action-style entrypoint, which prints the returned JSON locally:

```bash
modal run head_training_app.py --action list-artifacts
```

## Inference Endpoint

Create the API key secret manually before deploying:

```bash
modal secret create quality-scorers-api-key QUALITY_SCORERS_API_KEY='replace-with-your-api-key'
```

Deploy:

```bash
cd tools/quality-scorers
modal deploy inference_modal_app.py
```

Authentication accepts any of:

- `X-API-Key: <QUALITY_SCORERS_API_KEY>`
- `Authorization: Bearer <QUALITY_SCORERS_API_KEY>`
- `Authorization: Basic <base64(username:QUALITY_SCORERS_API_KEY)>`

POST raw FASTA:

```bash
cat > input.fasta <<'EOF'
>candidate_a
MSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW
EOF

curl -X POST "$QUALITY_SCORERS_MODAL_URL/predict" \
  -H "X-API-Key: $QUALITY_SCORERS_API_KEY" \
  -H "Content-Type: text/plain" \
  --data-binary @input.fasta
```

POST JSON:

```bash
curl -X POST "$QUALITY_SCORERS_MODAL_URL/predict" \
  -H "Authorization: Bearer $QUALITY_SCORERS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fasta": ">candidate_a\nMSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDW\n"
  }'
```

Response shape:

```json
{
  "scores": {
    "solubility": 0.82,
    "aggregation_apr": 0.18,
    "hla_presentation_risk": 0.44
  }
}
```

The endpoint accepts exactly one FASTA record. Invalid amino-acid tokens are
rejected with HTTP 400.

## Smoke Runs

Use `limit` to take a small number of rows per split during ingestion or a small
prefix during embedding/training:

```bash
modal run esm2_embedding_app.py::ingest_all --limit 128
modal run esm2_embedding_app.py::embed_all --limit 128
modal run head_training_app.py::train_all --hla-limit 128 --hla-epochs 1
```

The local entrypoint also supports action-based calls:

```bash
modal run esm2_embedding_app.py --action embed-all --limit 128
modal run head_training_app.py --action train-all --hla-limit 128 --hla-epochs 1
```

## Outputs

Normalized data:

- `/data/normalized/solubility.parquet`
- `/data/normalized/apr_hex.parquet`
- `/data/normalized/apr_protein_sanity.parquet`
- `/data/normalized/hla_el_pairs.parquet`

Cached embeddings:

- `/data/embeddings/<model-key>/solubility.parquet`
- `/data/embeddings/<model-key>/solubility.npy`
- `/data/embeddings/<model-key>/apr_hex.parquet`
- `/data/embeddings/<model-key>/apr_hex.npy`
- `/data/embeddings/<model-key>/hla_el_pairs.parquet`
- `/data/embeddings/<model-key>/hla_peptides.npy`
- `/data/embeddings/<model-key>/hla_pseudosequences.npy`

Trained heads:

- `/models/heads/<model-key>/solubility.joblib`
- `/models/heads/<model-key>/apr.joblib`
- `/models/heads/<model-key>/hla_el_mlp.pt`

Each stage also writes a JSON manifest under `/data/manifests` or
`/models/heads/<model-key>`.

## Data Sources

- ESM2 weights: `facebook/esm2_t12_35M_UR50D`
- Solubility: `SaProtHub/Dataset-Solubility`
- APR aggregation: ANuPP `Hex1279`, `Hex142`, `Amy17`, `Amy37`
- HLA EL: DTU `NetMHCpan_train.tar.gz` and `NetMHCIIpan_train.tar.gz`

If ANuPP FASTA headers do not expose binary labels cleanly, ingestion writes
`/data/raw/anupp/needs_manual_label_map.json` and fails closed. Add
`/data/raw/anupp/manual_label_map.json` with header-or-sequence keys mapped to
`0` or `1`, then rerun `ingest_apr`.

## Local Tests

The local tests avoid heavy ML dependencies:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/quality-scorers/tests
```
