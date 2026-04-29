# Structure Vis

Small pipeline for quickly visualizing local `.pdb`, `.cif`, or `.mmcif` protein structures.

The fastest workflow is to edit `compare_proteins.py` with the structures you care about, then run that file directly. It can generate either a no-install browser viewer or a PyMOL script.

## Setup

```bash
python3 -m pip install -e .
```

No third-party Python packages are required to generate scripts.

PyMOL is only required when you actually want to open the scenes. The easiest path is to use a normal PyMOL executable from Homebrew, conda, or Schrödinger PyMOL and either keep it on `PATH` or pass `--pymol /path/to/pymol`.

Check what this machine can use:

```bash
python3 -m structure_vis.cli doctor
```

If you are on Python 3.13 or newer and this fails:

```bash
python3 -m pip install ".[pymol]"
```

skip it and use a standalone PyMOL executable instead. PyMOL wheels commonly lag newer Python releases, while generated `.pml` scripts work independently of the Python package.

## Fast Script Workflow

Edit this block in `compare_proteins.py`:

```python
MODE = "batch_compare"  # "batch_compare", "compare", or "view"
VIEWER = "html"  # "html" needs no PyMOL install; "pymol" writes a .pml scene
OPEN_VIEWER = False

STRUCTURE_INPUTS = [
    ROOT / "examples",
    # ROOT / "your_structure_folder",
    # ROOT / "your_structure_folder" / "*.cif",
]
BATCH_STRATEGY = "all_pairs"  # "all_pairs" or "to_reference"

REFERENCE = ROOT / "examples" / "reference.pdb"
MOBILE = ROOT / "examples" / "model_shifted.pdb"
EXTRA_PROTEINS = []
```

Then run:

```bash
python3 compare_proteins.py
```

Folder inputs are expanded recursively. Supported files are `.pdb`, `.cif`, `.mmcif`, plus `.pdb.gz`, `.cif.gz`, and `.mmcif.gz`.

`BATCH_STRATEGY = "all_pairs"` compares every structure to every other structure. For many structures this grows quickly: 10 structures means 45 comparisons. Use `BATCH_STRATEGY = "to_reference"` to compare every structure against one reference instead.

Batch mode writes an `index.html` with links to every generated comparison scene.

For a PyMOL diff scene, set:

```python
VIEWER = "pymol"
OPEN_VIEWER = True
```

If PyMOL is not on `PATH`, set:

```python
PYMOL_EXECUTABLE = "/Applications/PyMOL.app/Contents/MacOS/PyMOL"
```

## Open Multiple Structures

```bash
structure-vis view path/to/a.pdb path/to/b.cif --open
```

Without installation, this also works from the repo:

```bash
python3 -m structure_vis.cli view path/to/a.pdb path/to/b.cif --open
```

If PyMOL is not installed yet, generate a browser viewer instead:

```bash
python3 -m structure_vis.cli html path/to/a.pdb path/to/b.cif
```

That writes `viewer.html` with the structures embedded directly in the file.

Load an entire folder:

```bash
structure-vis view --glob "structures/*.pdb" --glob "structures/*.cif" --open
```

The generated scene colors each structure separately, shows proteins as cartoons, keeps ligands as sticks, and keeps metals/waters visible as spheres.

## Compare Two Structures

```bash
structure-vis compare reference.pdb predicted.cif --open
```

For a no-install browser overlay:

```bash
python3 -m structure_vis.cli html reference.pdb predicted.cif --compare
```

The comparison scene:

- aligns the mobile structure onto the reference using PyMOL `super` on CA atoms
- overlays both structures in contrasting colors
- colors matched residues by post-alignment CA deviation
- draws red distance markers where matched CA atoms differ by at least `--distance-cutoff`
- adds a small PyMOL label with matched-pair count, RMSD, and max deviation

Example with a stricter threshold and an extra context structure:

```bash
structure-vis compare reference.pdb model_a.cif model_b.cif --distance-cutoff 1.0 --open
```

## Outputs

Each run writes to `runs/<mode>_<timestamp>/` unless `--out-dir` is supplied:

- `view.pml` or `compare.pml`: PyMOL script
- `manifest.json`: input files, object names, and visualization options

Open a generated script later with:

```bash
pymol runs/compare_YYYYMMDD_HHMMSS/compare.pml
```

## Python API

Use these functions directly from another script:

```python
from structure_vis.pipeline import batch_compare_structures, compare_structures, html_structures, view_structures

batch_compare_structures(["folder/of/structures"], viewer="html", out_dir="runs/latest")
html_structures(["a.pdb", "b.cif"], compare=True, out_dir="runs/latest")
compare_structures("reference.pdb", "model.cif", distance_cutoff=1.0, out_dir="runs/latest")
view_structures(["a.pdb", "b.pdb", "c.cif"], out_dir="runs/latest")
```
