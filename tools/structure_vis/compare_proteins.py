from __future__ import annotations

from pathlib import Path

from structure_vis.pipeline import compare_structures, html_structures, view_structures


ROOT = Path(__file__).resolve().parent

# Edit this block, then run:
#   python3 compare_proteins.py
MODE = "compare"  # "compare" or "view"
VIEWER = "html"  # "html" needs no PyMOL install; "pymol" writes a .pml scene
OPEN_VIEWER = False

REFERENCE = ROOT / "examples" / "102L.cif"
MOBILE = ROOT / "examples" / "hot.pdb"
EXTRA_PROTEINS: list[Path] = []

# Used when MODE = "view"; ignored for compare mode.
PROTEINS: list[Path] = [
    ROOT / "examples" / "reference.pdb",
    ROOT / "examples" / "model_shifted.pdb",
]

OUT_DIR = ROOT / "runs" / "latest"
STYLE = "cartoon"
DISTANCE_CUTOFF = 2.0
PYMOL_EXECUTABLE = None  # Example: "/Applications/PyMOL.app/Contents/MacOS/PyMOL"


def main() -> None:
    if MODE == "compare":
        files = [REFERENCE, MOBILE, *EXTRA_PROTEINS]
        if VIEWER == "html":
            scene = html_structures(files, compare=True, out_dir=OUT_DIR, open_browser=OPEN_VIEWER)
        elif VIEWER == "pymol":
            scene = compare_structures(
                REFERENCE,
                MOBILE,
                EXTRA_PROTEINS,
                out_dir=OUT_DIR,
                style=STYLE,
                distance_cutoff=DISTANCE_CUTOFF,
                open_pymol=OPEN_VIEWER,
                pymol=PYMOL_EXECUTABLE,
            )
        else:
            raise ValueError(f"Unknown VIEWER: {VIEWER}")
    elif MODE == "view":
        if VIEWER == "html":
            scene = html_structures(PROTEINS, compare=False, out_dir=OUT_DIR, open_browser=OPEN_VIEWER)
        elif VIEWER == "pymol":
            scene = view_structures(
                PROTEINS,
                out_dir=OUT_DIR,
                style=STYLE,
                open_pymol=OPEN_VIEWER,
                pymol=PYMOL_EXECUTABLE,
            )
        else:
            raise ValueError(f"Unknown VIEWER: {VIEWER}")
    else:
        raise ValueError(f"Unknown MODE: {MODE}")

    print(f"Scene: {scene.scene_path}")
    print(f"Manifest: {scene.manifest_path}")
    if scene.opened:
        print("Opened viewer.")
    elif VIEWER == "html":
        print(f"Open in browser: {scene.scene_path}")
    else:
        print(f"Open with PyMOL: pymol {scene.scene_path}")


if __name__ == "__main__":
    main()
