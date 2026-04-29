from __future__ import annotations

import glob
import html
import json
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Iterable

from .html_viewer import build_html_viewer
from .pymol_script import (
    StructureInput,
    build_compare_script,
    build_inputs,
    build_multi_view_script,
    object_name_for,
    structure_suffix,
    validate_structure_files,
    write_manifest,
)


@dataclass(frozen=True)
class GeneratedScene:
    scene_path: Path
    manifest_path: Path
    opened: bool = False


@dataclass(frozen=True)
class BatchResult:
    scenes: list[GeneratedScene]
    index_path: Path


def compare_structures(
    reference: str | Path,
    mobile: str | Path,
    extras: Iterable[str | Path] = (),
    *,
    out_dir: str | Path | None = None,
    style: str = "cartoon",
    distance_cutoff: float = 2.0,
    open_pymol: bool = False,
    pymol: str | None = None,
) -> GeneratedScene:
    paths = validate_structure_files([Path(reference), Path(mobile), *[Path(path) for path in extras]])
    reference_input = StructureInput(paths[0], object_name_for(paths[0], 1, role="reference"), role="reference")
    mobile_input = StructureInput(paths[1], object_name_for(paths[1], 2, role="mobile"), role="mobile")
    extra_inputs = build_inputs(paths[2:], role="context", start_index=3)

    output_dir = prepare_output_dir(out_dir, "compare")
    pml_path = output_dir / "compare.pml"
    pml_path.write_text(
        build_compare_script(
            reference_input,
            mobile_input,
            extras=extra_inputs,
            style=style,
            distance_cutoff=distance_cutoff,
        ),
        encoding="utf-8",
    )
    inputs = [reference_input, mobile_input, *extra_inputs]
    manifest_path = write_manifest(
        output_dir,
        command="compare",
        inputs=inputs,
        pml_path=pml_path,
        metadata={"style": style, "distance_cutoff": distance_cutoff},
    )
    return GeneratedScene(pml_path, manifest_path, launch_pymol(pml_path, open_pymol=open_pymol, pymol=pymol))


def view_structures(
    files: str | Path | Iterable[str | Path],
    *,
    out_dir: str | Path | None = None,
    style: str = "cartoon",
    open_pymol: bool = False,
    pymol: str | None = None,
) -> GeneratedScene:
    paths = resolve_structure_inputs(files)
    inputs = build_inputs(paths, role="structure")
    output_dir = prepare_output_dir(out_dir, "view")
    pml_path = output_dir / "view.pml"
    pml_path.write_text(build_multi_view_script(inputs, style=style), encoding="utf-8")
    manifest_path = write_manifest(
        output_dir,
        command="view",
        inputs=inputs,
        pml_path=pml_path,
        metadata={"style": style},
    )
    return GeneratedScene(pml_path, manifest_path, launch_pymol(pml_path, open_pymol=open_pymol, pymol=pymol))


def html_structures(
    files: str | Path | Iterable[str | Path],
    *,
    compare: bool = False,
    out_dir: str | Path | None = None,
    open_browser: bool = False,
) -> GeneratedScene:
    paths = resolve_structure_inputs(files)
    if compare and len(paths) < 2:
        raise ValueError("compare=True requires at least two structure files.")

    if compare:
        inputs = [
            StructureInput(paths[0], object_name_for(paths[0], 1, role="reference"), role="reference"),
            StructureInput(paths[1], object_name_for(paths[1], 2, role="mobile"), role="mobile"),
            *build_inputs(paths[2:], role="context", start_index=3),
        ]
        title = f"Compare: {paths[0].name} / {paths[1].name}"
        prefix = "html_compare"
    else:
        inputs = build_inputs(paths, role="structure")
        title = "Structure Viewer"
        prefix = "html_view"

    output_dir = prepare_output_dir(out_dir, prefix)
    html_path = output_dir / "viewer.html"
    html_path.write_text(build_html_viewer(inputs, title=title, compare=compare), encoding="utf-8")
    manifest_path = write_manifest(
        output_dir,
        command="html",
        inputs=inputs,
        pml_path=html_path,
        metadata={"compare": compare, "viewer": "3Dmol.js"},
    )
    opened = webbrowser.open(html_path.as_uri()) if open_browser else False
    return GeneratedScene(html_path, manifest_path, opened)


def batch_compare_structures(
    inputs: str | Path | Iterable[str | Path],
    *,
    out_dir: str | Path | None = None,
    viewer: str = "html",
    strategy: str = "all_pairs",
    reference: str | Path | None = None,
    style: str = "cartoon",
    distance_cutoff: float = 2.0,
    open_first: bool = False,
    pymol: str | None = None,
) -> BatchResult:
    paths = resolve_structure_inputs(inputs)
    if len(paths) < 2:
        raise ValueError("Batch comparison requires at least two structure files.")

    pairs = comparison_pairs(paths, strategy=strategy, reference=Path(reference) if reference else None)
    output_dir = prepare_output_dir(out_dir, "batch_compare")
    scenes: list[GeneratedScene] = []
    for index, (reference_path, mobile_path) in enumerate(pairs, start=1):
        pair_dir = output_dir / f"{index:03d}_{safe_stem(reference_path)}__vs__{safe_stem(mobile_path)}"
        should_open = open_first and index == 1
        if viewer == "html":
            scene = html_structures(
                [reference_path, mobile_path],
                compare=True,
                out_dir=pair_dir,
                open_browser=should_open,
            )
        elif viewer == "pymol":
            scene = compare_structures(
                reference_path,
                mobile_path,
                out_dir=pair_dir,
                style=style,
                distance_cutoff=distance_cutoff,
                open_pymol=should_open,
                pymol=pymol,
            )
        else:
            raise ValueError(f"Unknown viewer: {viewer}")
        scenes.append(scene)

    index_path = write_batch_index(output_dir, scenes, pairs, viewer=viewer, strategy=strategy)
    return BatchResult(scenes=scenes, index_path=index_path)


def comparison_pairs(
    paths: list[Path],
    *,
    strategy: str,
    reference: Path | None = None,
) -> list[tuple[Path, Path]]:
    if strategy == "all_pairs":
        return list(combinations(paths, 2))
    if strategy == "to_reference":
        reference_path = reference.expanduser().resolve() if reference else paths[0]
        if reference_path not in paths:
            paths = [reference_path, *paths]
            paths = resolve_structure_inputs(paths)
        return [(reference_path, path) for path in paths if path != reference_path]
    raise ValueError("strategy must be 'all_pairs' or 'to_reference'.")


def resolve_structure_inputs(inputs: str | Path | Iterable[str | Path], *, recursive: bool = True) -> list[Path]:
    paths: list[Path] = []
    input_items = [inputs] if isinstance(inputs, str | Path) else inputs
    for raw_input in input_items:
        text = str(raw_input)
        expanded = Path(raw_input).expanduser()
        if has_glob_magic(text):
            paths.extend(Path(match) for match in sorted(glob.glob(text, recursive=recursive)))
        elif expanded.is_dir():
            paths.extend(structures_in_dir(expanded, recursive=recursive))
        else:
            paths.append(expanded)

    unique: dict[Path, None] = {}
    for path in validate_structure_files(paths):
        unique[path] = None
    return sorted(unique)


def structures_in_dir(directory: Path, *, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(
        path
        for path in iterator
        if path.is_file() and structure_suffix(path) in {
            ".pdb",
            ".cif",
            ".mmcif",
            ".pdb.gz",
            ".cif.gz",
            ".mmcif.gz",
        }
    )


def has_glob_magic(value: str) -> bool:
    return any(character in value for character in "*?[")


def safe_stem(path: Path) -> str:
    stem = object_name_for(path, 1, role="").strip("_")
    return stem[:80]


def write_batch_index(
    output_dir: Path,
    scenes: list[GeneratedScene],
    pairs: list[tuple[Path, Path]],
    *,
    viewer: str,
    strategy: str,
) -> Path:
    json_index_path = output_dir / "batch_index.json"
    payload = {
        "viewer": viewer,
        "strategy": strategy,
        "comparisons": [
            {
                "reference": str(reference),
                "mobile": str(mobile),
                "scene": str(scene.scene_path),
                "manifest": str(scene.manifest_path),
            }
            for scene, (reference, mobile) in zip(scenes, pairs, strict=True)
        ],
    }
    json_index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    html_index_path = output_dir / "index.html"
    rows = []
    for scene, (reference, mobile) in zip(scenes, pairs, strict=True):
        scene_href = html.escape(scene.scene_path.relative_to(output_dir).as_posix())
        reference_name = html.escape(reference.name)
        mobile_name = html.escape(mobile.name)
        rows.append(
            f"<tr><td>{reference_name}</td><td>{mobile_name}</td>"
            f'<td><a href="{scene_href}">open</a></td></tr>'
        )
    html_index_path.write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Structure Batch Comparisons</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #18202b; }
    table { border-collapse: collapse; width: 100%; max-width: 1100px; }
    th, td { border-bottom: 1px solid #d9dee7; padding: 8px 10px; text-align: left; }
    th { background: #f7f8fa; }
    a { color: #2563eb; }
  </style>
</head>
<body>
  <h1>Structure Batch Comparisons</h1>
  <p>Viewer: """
        + html.escape(viewer)
        + " | Strategy: "
        + html.escape(strategy)
        + """</p>
  <table>
    <thead><tr><th>Reference</th><th>Mobile</th><th>Scene</th></tr></thead>
    <tbody>
      """
        + "\n      ".join(rows)
        + """
    </tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_index_path


def expand_globs(patterns: Iterable[str]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(Path(path) for path in sorted(glob.glob(pattern)))
    return matches


def prepare_output_dir(requested: str | Path | None, prefix: str) -> Path:
    if requested is not None:
        output_dir = Path(requested).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir.resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("runs") / f"{prefix}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def launch_pymol(pml_path: Path, *, open_pymol: bool, pymol: str | None = None) -> bool:
    if not open_pymol:
        return False
    executable = pymol or shutil.which("pymol") or shutil.which("pymol-open-source")
    if executable is None:
        raise FileNotFoundError("PyMOL executable not found. Install PyMOL or pass a pymol executable path.")
    subprocess.Popen([executable, str(pml_path)])
    return True


def doctor_lines() -> list[str]:
    lines = [f"Python: {sys.version.split()[0]} at {sys.executable}"]
    pymol_executable = shutil.which("pymol") or shutil.which("pymol-open-source")
    if pymol_executable:
        lines.append(f"PyMOL executable: {pymol_executable}")
    else:
        lines.append("PyMOL executable: not found on PATH")

    try:
        import pymol  # type: ignore  # noqa: F401
    except Exception as exc:
        lines.append(f"PyMOL Python package: unavailable ({exc.__class__.__name__}: {exc})")
    else:
        lines.append("PyMOL Python package: importable")

    if sys.version_info >= (3, 13):
        lines.append(
            "Note: Python 3.13+ may not have compatible pymol-open-source wheels. "
            "This tool can still generate .pml files without installing PyMOL as a Python package."
        )
    return lines
