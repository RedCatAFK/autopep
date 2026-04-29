from __future__ import annotations

import glob
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .html_viewer import build_html_viewer
from .pymol_script import (
    StructureInput,
    build_compare_script,
    build_inputs,
    build_multi_view_script,
    object_name_for,
    validate_structure_files,
    write_manifest,
)


@dataclass(frozen=True)
class GeneratedScene:
    scene_path: Path
    manifest_path: Path
    opened: bool = False


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
    files: Iterable[str | Path],
    *,
    out_dir: str | Path | None = None,
    style: str = "cartoon",
    open_pymol: bool = False,
    pymol: str | None = None,
) -> GeneratedScene:
    paths = validate_structure_files([Path(path) for path in files])
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
    files: Iterable[str | Path],
    *,
    compare: bool = False,
    out_dir: str | Path | None = None,
    open_browser: bool = False,
) -> GeneratedScene:
    paths = validate_structure_files([Path(path) for path in files])
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
