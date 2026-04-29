from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import (
    GeneratedScene,
    compare_structures,
    doctor_lines,
    expand_globs,
    html_structures,
    view_structures,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = run_doctor()
            return result
        if args.command == "html":
            run_html(args)
            return 0
        elif args.command == "view":
            result = run_view(args)
        elif args.command == "compare":
            result = run_compare(args)
        else:
            parser.print_help()
            return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"structure-vis: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote PyMOL script: {result.scene_path}")
    print(f"Wrote manifest: {result.manifest_path}")
    if result.opened:
        print("Launched PyMOL.")
    else:
        print(f"Open with: pymol {result.scene_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="structure-vis",
        description="Generate quick PyMOL visualizations for .pdb, .cif, and .mmcif files.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check local Python and PyMOL availability.")

    html_parser = subparsers.add_parser("html", help="Generate a browser viewer with embedded structures.")
    html_parser.add_argument("files", nargs="*", type=Path, help="PDB/mmCIF files to visualize.")
    html_parser.add_argument("--glob", action="append", default=[], help="Glob pattern for additional structure files.")
    html_parser.add_argument(
        "--compare",
        action="store_true",
        help="Treat the first two files as reference/mobile in the browser overlay.",
    )
    html_parser.add_argument("--out-dir", type=Path, default=None, help="Directory for generated HTML and metadata.")
    html_parser.add_argument("--open", action="store_true", help="Open the generated HTML in the default browser.")

    view = subparsers.add_parser("view", help="Open one or more structures in a single PyMOL scene.")
    view.add_argument("files", nargs="*", type=Path, help="PDB/mmCIF files to visualize.")
    view.add_argument("--glob", action="append", default=[], help="Glob pattern for additional structure files.")
    add_common_options(view)

    compare = subparsers.add_parser("compare", help="Align two structures and visualize their differences.")
    compare.add_argument("reference", type=Path, help="Reference PDB/mmCIF file.")
    compare.add_argument("mobile", type=Path, help="Mobile PDB/mmCIF file aligned onto the reference.")
    compare.add_argument(
        "extras",
        nargs="*",
        type=Path,
        help="Optional extra structures to load in the same scene for context.",
    )
    compare.add_argument(
        "--distance-cutoff",
        type=float,
        default=2.0,
        help="Draw CA-to-CA distance markers above this post-alignment threshold in angstroms.",
    )
    add_common_options(compare)
    return parser


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--style",
        choices=("cartoon", "surface", "sticks", "spheres"),
        default="cartoon",
        help="Primary PyMOL representation.",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="Directory for generated scripts and metadata.")
    parser.add_argument("--open", action="store_true", help="Launch PyMOL after generating the script.")
    parser.add_argument("--pymol", default=None, help="PyMOL executable to use with --open.")


def run_doctor() -> int:
    for line in doctor_lines():
        print(line)
    return 0


def run_html(args: argparse.Namespace) -> GeneratedScene:
    scene = html_structures(
        [*args.files, *expand_globs(args.glob)],
        compare=args.compare,
        out_dir=args.out_dir,
        open_browser=args.open,
    )
    print(f"Wrote HTML viewer: {scene.scene_path}")
    print(f"Wrote manifest: {scene.manifest_path}")
    if scene.opened:
        print("Opened browser viewer.")
    else:
        print(f"Open in a browser: {scene.scene_path}")
    return scene


def run_view(args: argparse.Namespace) -> GeneratedScene:
    return view_structures(
        [*args.files, *expand_globs(args.glob)],
        out_dir=args.out_dir,
        style=args.style,
        open_pymol=args.open,
        pymol=args.pymol,
    )


def run_compare(args: argparse.Namespace) -> GeneratedScene:
    return compare_structures(
        args.reference,
        args.mobile,
        args.extras,
        out_dir=args.out_dir,
        style=args.style,
        distance_cutoff=args.distance_cutoff,
        open_pymol=args.open,
        pymol=args.pymol,
    )


if __name__ == "__main__":
    raise SystemExit(main())
