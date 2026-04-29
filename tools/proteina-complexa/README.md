# Proteina-Complexa on Modal

This directory deploys NVIDIA Proteina-Complexa as a Modal-hosted HTTP
inference service. Each request supplies a target structure, the server
preprocesses it into the Complexa target layout, runs the upstream `complexa`
CLI in the Modal container, and returns generated PDB text.

## Repository Layout

- `modal_app.py` is the Modal deployment entrypoint. It only wires the image,
  volumes, secrets, and ASGI app.
- `proteina_complexa/config.py` names Modal paths, model paths, defaults, and
  runtime constants.
- `proteina_complexa/modal_resources.py` builds the CUDA image, applies the
  upstream warm-start patch, and declares Modal Volumes/Secrets.
- `proteina_complexa/payloads.py` normalizes the HTTP JSON contract.
- `proteina_complexa/preprocessing.py` parses CIF/PDB text into sequence and
  C-alpha metadata.
- `proteina_complexa/target_preprocessing.py` writes the request target into
  Complexa's `/data` layout and builds target Hydra overrides.
- `proteina_complexa/warm_start.py` contains optional seed-binder support.
- `proteina_complexa/design.py` builds and runs the `complexa design` command.
- `proteina_complexa/http_server.py` owns FastAPI routes and response shaping.
- `patches/proteina-warm-start.patch` is the upstream Proteina-Complexa patch
  applied during Modal image build.

Generated run outputs belong under `runs/` and should not be committed.

## Inference Flow

The usual cold-start binder path is:

1. Validate and normalize the JSON request.
2. Parse the supplied target CIF/PDB text.
3. Write the target structure and metadata under `/data/preprocessed_targets`
   and `/data/target_data/preprocessed_targets`.
4. Build the normal `complexa design ...` command with checkpoint, output, and
   target overrides.
5. Run generation from Complexa's normal random/noisy binder prior.
6. Collect generated PDB files from `/runs/<run_name>/...` and return them in
   the HTTP response.

Warm start is optional. When a request includes `warm_start`, the same target
preprocessing path still runs first, then the seed binder is written under
`/data/seed_binders`, seed-binder Hydra overrides are added, and the patched
Complexa sampler resumes denoising from the supplied binder state. `warm_start`
can be either one seed object or a list of seed objects; the list form keeps the
target fixed and runs the seeds as one generation batch. If seed setup fails, the
wrapper logs the problem and falls back to the cold path. The response reports
this as `design.warm_start.mode: "cold"` or `"warm"`.

Warm-start controls:

- `noise_level`: lower stays closer to the seed; higher explores farther.
- `start_t`: direct diffusion-time override.
- `num_steps`: direct remaining-step override.
- `chain`: optional chain selection within the seed binder.

## Modal Resources

The service expects these resources in the `autopep` workspace's `main`
environment:

- `proteina-complexa-models` mounted at `/models`
- `proteina-complexa-data` mounted at `/data`
- `proteina-complexa-runs` mounted at `/runs`
- `huggingface-secret` containing `HF_TOKEN`
- `proteina-complexa-api-key` containing `PROTEINA_COMPLEXA_API_KEY`

Create them once:

```bash
modal volume create proteina-complexa-models --env main
modal volume create proteina-complexa-data --env main
modal volume create proteina-complexa-runs --env main
modal secret create huggingface-secret HF_TOKEN=hf_... --env main
modal secret create proteina-complexa-api-key PROTEINA_COMPLEXA_API_KEY='replace-with-your-api-key' --env main
```

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
modal setup
modal config set-environment main
```

## Deploy

```bash
cd tools/proteina-complexa
modal deploy modal_app.py
```

The first live container downloads `complexa.ckpt` and `complexa_ae.ckpt` into
the model Volume if they are missing.

For development, serve the ASGI app through Modal:

```bash
cd tools/proteina-complexa
modal serve modal_app.py
```

## HTTP API

Authentication accepts any of:

- `X-API-Key: <PROTEINA_COMPLEXA_API_KEY>`
- `Authorization: Bearer <PROTEINA_COMPLEXA_API_KEY>`
- `Authorization: Basic <base64(username:PROTEINA_COMPLEXA_API_KEY)>`

`POST /design` and `POST /predict` return JSON. `POST /design.pdb`,
`POST /predict.pdb`, or `"return_format": "pdb"` return the first generated PDB
as `chemical/x-pdb`.

```bash
curl -X POST "$PROTEINA_COMPLEXA_MODAL_URL/design" \
  -H "X-API-Key: $PROTEINA_COMPLEXA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "action": "smoke-cif",
  "run_name": "target_102L_smoke_api",
  "target": {
    "structure": "data_...\n#\n",
    "filename": "102L.cif",
    "name": "target_102L",
    "target_input": "A1-162",
    "hotspot_residues": [],
    "binder_length": [60, 120]
  },
  "warm_start": {
    "structure": "ATOM ...\n",
    "filename": "seed_binder.pdb",
    "chain": "B",
    "noise_level": 0.4
  },
  "overrides": [
    "++generation.dataloader.batch_size=1"
  ]
}
JSON
```

For a batched warm-start smoke request, send `warm_start` as a list. The server
sets the smoke `batch_size` and `nres.nsamples` to the number of seeds unless
you override them explicitly. `chain` may differ per seed; diffusion controls
such as `noise_level`, `start_t`, and `num_steps` must be shared across the
batch:

```json
{
  "action": "smoke-cif",
  "target": {
    "structure": "data_...\n#\n",
    "filename": "102L.cif",
    "name": "target_102L",
    "target_input": "A1-162"
  },
  "warm_start": [
    {"structure": "data_105M\n#\n", "filename": "105M.cif", "noise_level": 0.5},
    {"structure": "data_1OZ9\n#\n", "filename": "1OZ9.cif", "noise_level": 0.5}
  ]
}
```

The helper smoke script defaults to all files under
`test_proteins/warm_start_test/*.cif.gz` and JSON mode, so all returned PDBs
are preserved under `runs/http_smoke_pdbs_<timestamp>/`:

```bash
scripts/http_smoke_pdb.sh
```

Use `"action": "smoke-cif"` for a generation-only check. Use
`"action": "design-cif"` or omit `action` for the full design pipeline.

Response shape:

```json
{
  "run_name": "target_102L_smoke_api",
  "task_name": "target_102L",
  "mode": "smoke-cif",
  "format": "pdb",
  "warm_start_count": 1,
  "count": 1,
  "pdb_filename": "job_0_n_261_id_0_single_orig0.pdb",
  "pdb": "ATOM ...\n",
  "pdbs": [
    {
      "rank": 1,
      "filename": "job_0_n_261_id_0_single_orig0.pdb",
      "relative_path": "job_0_n_261_id_0_single_orig0/job_0_n_261_id_0_single_orig0.pdb",
      "pdb": "ATOM ...\n"
    }
  ],
  "preprocessed_target": {
    "target_name": "target_102L",
    "target_input": "A1-162",
    "pdb_path": "/data/target_data/preprocessed_targets/target_102L.pdb"
  },
  "design": {
    "warm_start": {
      "mode": "warm",
      "support_status": "native"
    }
  }
}
```

## Local Structure Parsing

For a lightweight local parse without Modal/GPU work:

```bash
python3 scripts/preprocess_cif.py /path/to/target.cif \
  --target-name my_target \
  --target-input A1-150 \
  --output-dir preprocessed
```

If `target_input` is omitted, the parser infers simple contiguous ranges such
as `A1-150`. Pass it explicitly for cropped targets, insertion codes, or
non-contiguous target selections.

## Notes

- The server preprocesses the target on every HTTP request, so a request is
  self-contained and does not rely on a preloaded target name.
- NVIDIA's upstream pipeline is Hydra-based; this wrapper injects paths and
  runtime choices with CLI overrides instead of editing upstream configs.
- Some full design/evaluation paths need optional community model checkpoints
  such as AF2/RF3. Use `smoke-cif` for a quick generation-only health check.
