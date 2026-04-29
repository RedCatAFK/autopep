# Quality Scorer Training

Modal jobs for the learned sequence quality scorers described in
`autpep_sequence_filter_spec.md`. These scorers help answer whether a generated
protein candidate is practical enough to keep working on after binding,
structure, and stability checks.

The training flow is split into three Modal apps:

- `esm2_embedding_app.py`: heavier `L40S` jobs that download data, download
  `facebook/esm2_t12_35M_UR50D`, and cache frozen ESM2 embeddings once.
- `head_training_app.py`: lighter `T4` jobs that train heads from cached
  embeddings.
- `inference_modal_app.py`: `T4` ASGI/FastAPI endpoint that loads ESM2 and the
  trained heads for FASTA scoring.

## What The Scores Mean

The API returns numbers between `0.0` and `1.0`. They are triage signals, not
guarantees from an experiment. A good candidate usually wants high solubility
and low aggregation and HLA risk.

Here, "quality" means practical usability: can we make enough of the protein,
handle it in solution, avoid obvious clumping, and avoid avoidable immune-risk
signals? `APR` means aggregation-prone region. `HLA` molecules are display
proteins on human cells that show small protein pieces to immune cells.

| Score | Plain-English question | Direction | What it means for usability |
|---|---|---|---|
| `solubility` | Does this look like a protein that can be made and kept dissolved? | Higher is better | A high score means the sequence resembles proteins that can be produced, purified, concentrated, and tested as dissolved material. A low score means the candidate may be hard to make or may fall out of solution, which makes lab work slower and less reliable. |
| `aggregation_apr` | Does any short patch look sticky enough to start clumping? | Lower is better | A high score means at least one 6-amino-acid window resembles known aggregation-prone peptides. That can make the sample cloudy, reduce usable yield, cause nonspecific binding, or make storage and formulation harder. |
| `hla_presentation_risk` | Are pieces of this protein likely to be shown to the immune system by common HLA molecules? | Lower is better | A high score means more short pieces of the candidate look displayable by HLA molecules. That does not prove clinical immunogenicity, but it is a reason to review or mutate the flagged regions before treating the sequence as therapy-ready. |

Useful starting bands are:

- `solubility`: `>= 0.70` good, `0.40-0.70` review, `< 0.40` poor.
- `aggregation_apr`: `< 0.40` low concern, `0.40-0.75` review, `>= 0.75` high concern.
- `hla_presentation_risk`: `< 0.35` low concern, `0.35-0.70` review, `>= 0.70` high concern.

Recalibrate these bands after looking at validation metrics and at the score
distribution for your own generated candidates.

## How The Learned Scorers Work

ESM2 is used as a general protein sequence reader. It turns each amino-acid
sequence, short peptide window, or HLA pseudo-sequence into numeric features.
The small trained models on top of those features are the "heads":

- `solubility.joblib`: predicts whether a full protein sequence resembles
  soluble or insoluble training examples.
- `apr.joblib`: predicts whether a 6-amino-acid window is aggregation-prone.
  Candidate-level `aggregation_apr` is currently the highest window score.
- `hla_el_mlp.pt`: predicts whether a peptide-HLA pair resembles eluted-ligand
  examples. At inference, the candidate is split into 8-11 amino-acid MHC-I
  windows and 15 amino-acid MHC-II windows and scanned against a default HLA
  panel.

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
- `/data/embeddings/<model-key>/hla_peptides.parquet`
- `/data/embeddings/<model-key>/hla_peptides.npy`
- `/data/embeddings/<model-key>/hla_pseudosequences.parquet`
- `/data/embeddings/<model-key>/hla_pseudosequences.npy`

Trained heads:

- `/models/heads/<model-key>/solubility.joblib`
- `/models/heads/<model-key>/apr.joblib`
- `/models/heads/<model-key>/hla_el_mlp.pt`

Each stage also writes a JSON manifest under `/data/manifests` or
`/models/heads/<model-key>`.

## Data Sources And Targets

### ESM2 Encoder

Source: [`facebook/esm2_t12_35M_UR50D`](https://huggingface.co/facebook/esm2_t12_35M_UR50D)

ESM2 is not one of the quality-label datasets. It is a pretrained protein
sequence model used to turn amino-acid text into features that the quality heads
can learn from.

- What is inside it: model weights and tokenizer files for a 12-layer,
  roughly 35M-parameter ESM2 checkpoint.
- Input: amino-acid sequence text.
- Target: none in this pipeline; it is used as a frozen feature extractor.
- Pipeline output: cached embedding tables and `.npy` matrices under
  `/data/embeddings/<model-key>/`.

### Solubility Dataset

Source: [`SaProtHub/Dataset-Solubility`](https://huggingface.co/datasets/SaProtHub/Dataset-Solubility)

This dataset is used to teach the model whether a full protein sequence looks
likely to stay dissolved.

- What is inside it: `71,419` amino-acid sequences with columns `protein`,
  `label`, and `stage`.
- Source split sizes: `62,478` train, `6,942` valid, and `1,999` test rows.
- Input to our model: the cleaned full protein sequence from `protein`, stored
  as `sequence`.
- Target: binary `label`, where `1` means soluble and `0` means insoluble.
- Split field: `stage`, normalized to `split`.
- Normalized output: `/data/normalized/solubility.parquet`.
- Training use: ESM2 embeds each full sequence; `solubility.joblib` learns to
  return a high score for soluble-like sequences.

The ingest step drops invalid amino-acid sequences, removes exact duplicate
sequences with conflicting labels, and keeps only one row for exact duplicates.

### APR Aggregation Dataset

Source: [ANuPP datasets](https://web.iitm.ac.in/bioinfo2/anupp/datasets/)

APR means "aggregation-prone region": a short patch that can make a protein
stick to itself or other proteins. This model is deliberately narrow. It looks
for risky 6-amino-acid windows; it does not prove full formulation behavior.

- `Hex1279`: training set with `461` amyloidogenic and `818`
  non-amyloidogenic hexapeptides.
- `Hex142`: held-out test set with `51` amyloidogenic and `91`
  non-amyloidogenic hexapeptides.
- `Amy17`: `17` amyloidogenic proteins with APR annotations.
- `Amy37`: `37` amyloidogenic proteins with APR annotations.

For `Hex1279` and `Hex142`:

- What is inside them: labeled 6-amino-acid peptides.
- Input to our model: the peptide sequence, stored as `sequence`.
- Target: binary `label`, where `1` means amyloidogenic or aggregation-prone
  and `0` means non-amyloidogenic.
- Split policy: `Hex1279` is `train`; `Hex142` is `test`. A validation split is
  carved out of `Hex1279` during head training.
- Normalized output: `/data/normalized/apr_hex.parquet`.
- Training use: ESM2 embeds each 6-mer; `apr.joblib` learns to return a high
  score for aggregation-prone windows.

For `Amy17` and `Amy37`:

- What is inside them: whole amyloidogenic protein sequences with APR
  annotations in the source data.
- Input in the current pipeline: full protein sequence and FASTA header.
- Target in the current pipeline: none. The files are stored for protein-level
  sanity checks, not for supervised head training.
- Normalized output: `/data/normalized/apr_protein_sanity.parquet`.

If ANuPP FASTA headers do not expose binary labels cleanly, ingestion writes
`/data/raw/anupp/needs_manual_label_map.json` and fails closed. Add
`/data/raw/anupp/manual_label_map.json` with header-or-sequence keys mapped to
`0` or `1`, then rerun `ingest_apr`.

### HLA Eluted-Ligand Dataset

Source: [DTU NetMHCpan / NetMHCIIpan supplementary training data](https://services.healthtech.dtu.dk/suppl/immunology/NAR_NetMHCpan_NetMHCIIpan/)

HLA molecules show short protein pieces to the immune system. "Eluted ligand"
data are peptides observed after being displayed by HLA molecules. This is why
the score is called `hla_presentation_risk`, not clinical immunogenicity.

The pipeline downloads:

- `NetMHCpan_train.tar.gz` for MHC-I.
- `NetMHCIIpan_train.tar.gz` for MHC-II.

MHC-I source files:

- What is inside them: binding-affinity partitions and eluted-ligand partitions;
  this pipeline uses only the `c00?_el` eluted-ligand files.
- Row shape used here: peptide, target value, and HLA molecule or cell-line.
- Support files: `allelelist` maps cell lines to expressed alleles, and
  `MHC_pseudo.dat` maps alleles to HLA pseudo-sequences.
- Split policy: `c000_el` is `test`, `c001_el` is `valid`, and the other
  `c00?_el` files are `train`.

MHC-II source files:

- What is inside them: binding-affinity partitions and eluted-ligand partitions;
  this pipeline uses only the `train_EL*` and `test_EL*` eluted-ligand files.
- Row shape used here: peptide, target value, HLA molecule or cell-line, plus a
  context column that the current parser ignores.
- Support files: `allelelist.txt` maps cell lines to expressed alleles, and
  `pseudosequence.2016.all.X.dat` maps alleles to HLA pseudo-sequences.
- Split policy: `test_EL*` is `test`, `train_EL4` is `valid`, and the other
  `train_EL*` files are `train`.

For both classes:

- Input to our model: a peptide sequence plus the HLA pseudo-sequence for the
  allele it is paired with.
- Target: the numeric eluted-ligand target value from the source row. The ingest
  also stores `target_binary`, where values `>= 0.5` count as presented for
  binary metrics.
- Normalized output: `/data/normalized/hla_el_pairs.parquet`.
- Embedding outputs: peptide and HLA pseudo-sequence tables plus `.npy` matrices
  under `/data/embeddings/<model-key>/`.
- Training use: `hla_el_mlp.pt` learns from peptide-HLA pairs. Rows with
  invalid peptides, unresolved HLA names, or ambiguous multi-allele cell-line
  mappings are skipped.

## Local Tests

The local tests avoid heavy ML dependencies:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/quality-scorers/tests
```
