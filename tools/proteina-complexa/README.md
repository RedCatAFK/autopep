# Proteina-Complexa on Modal

This directory contains a Modal deployment for running NVIDIA's
Proteina-Complexa protein-target binder model on Modal GPUs with open weights.

The deployed FastAPI endpoint accepts a target structure on every request,
optionally accepts a seed binder for warm-start generation, and runs the
upstream `complexa` CLI inside the persistent Modal container. The local
`modal run --action ...` commands remain available for development and volume
maintenance.

## Modal Resources

The app uses these resources in the `autopep` workspace's `main` environment:

- `proteina-complexa-models` mounted at `/models`
- `proteina-complexa-data` mounted at `/data`
- `proteina-complexa-runs` mounted at `/runs`
- `huggingface-secret` containing `HF_TOKEN`
- `proteina-complexa-api-key` containing `PROTEINA_COMPLEXA_API_KEY`

Create the volumes once:

```bash
modal volume create proteina-complexa-models --env main
modal volume create proteina-complexa-data --env main
modal volume create proteina-complexa-runs --env main
```

Create the Hugging Face secret once:

```bash
modal secret create huggingface-secret HF_TOKEN=hf_... --env main
```

Create the HTTP API key secret once:

```bash
modal secret create proteina-complexa-api-key PROTEINA_COMPLEXA_API_KEY='replace-with-your-api-key' --env main
```

If the Hugging Face model is public for your account, the token can still be a
normal read token. Keeping it as a secret avoids hard-coding auth assumptions.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
modal setup
modal config set-environment main
```

## Deploy

Deploy the persistent HTTP endpoint:

```bash
cd tools/proteina-complexa
modal deploy modal_app.py
```

The first deployed container checks the model Volume and downloads the checkpoint
pair if needed. You can still pre-populate the Volume explicitly:

```bash
cd tools/proteina-complexa
modal run modal_app.py --action download-weights
```

Run the app locally on Modal during development:

```bash
cd tools/proteina-complexa
modal serve modal_app.py
```

## Build and Download Weights

The first build creates a large CUDA/PyTorch image and can take a while.

```bash
modal run modal_app.py --action download-weights
```

Check the persisted checkpoint pair:

```bash
modal run modal_app.py --action list-weights
```

Expected files:

- `/models/protein-target-160m/complexa.ckpt`
- `/models/protein-target-160m/complexa_ae.ckpt`

## HTTP API

Authentication accepts any of:

- `X-API-Key: <PROTEINA_COMPLEXA_API_KEY>`
- `Authorization: Bearer <PROTEINA_COMPLEXA_API_KEY>`
- `Authorization: Basic <base64(username:PROTEINA_COMPLEXA_API_KEY)>`

`POST /design` and `POST /predict` accept the same JSON contract. The target
structure contents are required on every request; the warm-start seed binder is
optional.

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

Use `"action": "design-cif"` or omit `action` for the full design pipeline.
Use `"action": "smoke-cif"` for the generation-only smoke path. The API also
accepts flat aliases such as `target_cif`, `target_name`,
`hotspot_residues`, `binder_length`, `seed_binder_pdb`,
`seed_binder_chain`, `seed_binder_noise_level`, `steps`, and `overrides` for
parity with the local flags.

Response shape:

```json
{
  "run_name": "target_102L_smoke_api",
  "task_name": "target_102L",
  "mode": "smoke-cif",
  "format": "pdb",
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
    "run_name": "target_102L_smoke_api",
    "warm_start": {
      "mode": "warm",
      "support_status": "native"
    }
  }
}
```

The HTTP response includes generated PDB text directly, Chai-style. For
development commands such as `modal run modal_app.py --action smoke-cif`, the
return payload stays lightweight and points at persisted files in the
`proteina-complexa-runs` Volume.

To get the first generated structure as an actual `.pdb` download instead of
JSON, post the same JSON body to `/design.pdb`:

```bash
curl -X POST "$PROTEINA_COMPLEXA_MODAL_URL/design.pdb" \
  -H "X-API-Key: $PROTEINA_COMPLEXA_API_KEY" \
  -H "Content-Type: application/json" \
  -o proteina_complexa_prediction.pdb \
  -d @request.json
```

You can also use `/predict.pdb`, or send `"return_format": "pdb"` to
`/design`. The generated PDB remains persisted in the `proteina-complexa-runs`
Volume as well.

## Validate

Validate the default protein-target binder pipeline before launching a long GPU
job:

```bash
modal run modal_app.py --action validate
```

Pass Hydra overrides as JSON when needed:

```bash
modal run modal_app.py \
  --action validate \
  --overrides-json '["++gen_njobs=1", "++eval_njobs=1"]'
```

## Preprocess a CIF Target

The preprocessing layer accepts a local `.cif` or `.mmcif`, extracts amino acid
sequence and C-alpha geometry for metadata, uploads the CIF into the Modal
`/data` volume, converts it to the target PDB layout expected by Complexa, and
checks the atom37 target tensors through Complexa's own loader.

For a lightweight local parse:

```bash
python3 scripts/preprocess_cif.py /path/to/target.cif \
  --target-name my_target \
  --target-input A1-150 \
  --output-dir preprocessed
```

For the full Modal preprocessing path:

```bash
modal run modal_app.py \
  --action preprocess-cif \
  --cif-path /path/to/target.cif \
  --target-name my_target \
  --target-input A1-150 \
  --hotspot-residues-json '["A45", "A67"]' \
  --binder-length-json '[60, 120]'
```

This writes:

- `/data/preprocessed_targets/my_target.cif`
- `/data/target_data/preprocessed_targets/my_target.pdb`
- `/data/preprocessed_targets/my_target.preprocess.json`
- `/data/preprocessed_targets/my_target.fasta`

The returned `target_tensor_info` reports the actual Complexa target tensor
shapes, including `x_target` as `[num_res, 37, 3]`, `target_mask` as
`[num_res, 37]`, and `seq_target` as `[num_res]`. Optional
`/data/preprocessed_targets/my_target.latents.pt` encoding can be requested with
`--encode-latents`; it is a diagnostic artifact and is not consumed by the
standard generation config.
If a structure has insertion codes or a cropped `--target-input`, treat
`target_residue_count` and `target_tensor_info` as authoritative for what
Complexa will generate against; the JSON/FASTA files are metadata.

The returned `hydra_overrides` can be passed to Complexa directly. To preprocess
and run a fast generation-only smoke test that does not require AlphaFold2
community-model weights:

```bash
modal run modal_app.py \
  --action smoke-cif \
  --cif-path /path/to/target.cif \
  --target-name my_target \
  --target-input A1-150 \
  --run-name my_target_smoke
```

To preprocess and then launch the full binder design pipeline in one command:

```bash
modal run modal_app.py \
  --action design-cif \
  --cif-path /path/to/target.cif \
  --target-name my_target \
  --target-input A1-150 \
  --run-name my_target_design \
  --hotspot-residues-json '["A45", "A67"]'
```

The full `design-cif` pipeline uses AF2 reward/evaluation stages. Provision the
upstream community model weights under `/workspace/protein-foundation-models/community_models/ckpts/AF2`
or use `smoke-cif` for a model-generation check without those artifacts.

If `--target-input` is omitted, the local parser infers a simple contiguous
range per chain such as `A1-150`. Pass it explicitly for cropped targets,
insertion codes, or non-contiguous target selections.

## Run a Binder Design

```bash
modal run modal_app.py \
  --action design \
  --task-name 02_PDL1 \
  --run-name pdl1_modal_smoke \
  --overrides-json '["++gen_njobs=1", "++eval_njobs=1"]'
```

The app writes outputs to `/runs` and commits the Volume after the CLI exits.
Use unique `run_name` values for parallel jobs so containers never write to the
same output directory.

### Warm-Start From a Seed Binder

Pass `--seed-binder-pdb-path` to initialize binder generation from an existing
binder structure instead of the usual random prior:

```bash
modal run modal_app.py \
  --action design \
  --task-name 02_PDL1 \
  --run-name pdl1_warm_seed_001 \
  --seed-binder-pdb-path /path/to/binder_seed.pdb \
  --seed-binder-chain B \
  --seed-binder-noise-level 0.4
```

`--seed-binder-noise-level` defaults to `0.5` inside the patched sampler when
omitted. Lower values start closer to the seed; higher values explore farther
from it. You can alternatively pass `--seed-binder-start-t` or
`--seed-binder-num-steps` for more direct control over where denoising begins.

Warm start is optional and defensive: if no seed is supplied, or if seed parsing
cannot be applied safely in the Modal container, the run falls back to the
existing cold-start path instead of treating the seed as a second fixed target.
Warm-start hooks are installed when the Modal image is built from
`patches/proteina-warm-start.patch`, so GPU jobs only verify that the image
contains compatible support (`support_status: "native"`). A long-term cleaner
option is to replace the build-time patch step with a maintained
Proteina-Complexa fork or upstream branch that already includes these hooks.

## Batch Usage

For fanout, put jobs in a JSON file like [examples/jobs.json](examples/jobs.json):

```bash
modal run modal_app.py --action batch --jobs-json examples/jobs.json
```

The current default is one `A100-80GB` per Modal container. After a smoke test,
benchmark cheaper GPUs or multi-GPU containers with overrides such as
`++gen_njobs=4` and `++eval_njobs=4`.

## Notes

- NVIDIA's upstream pipeline is Hydra-based; this app injects checkpoint paths
  with CLI overrides instead of editing their config files.
- Modal Volumes require explicit `commit()` after writes and `reload()` before
  reading fresh state from another container.
- Some evaluation/reward paths depend on optional community model checkpoints
  such as AF2/RF3. The image sets the paths expected by NVIDIA's Docker setup,
  but those artifacts may need separate provisioning depending on the pipeline
  configuration you choose.
