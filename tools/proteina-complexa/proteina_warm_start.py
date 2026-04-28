from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


DEFAULT_PATCH_PATH = Path(__file__).resolve().parent / "patches" / "proteina-warm-start.patch"


def _run_git_apply(args: list[str], *, cwd: Path, patch_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "apply", *args, str(patch_path)],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _file_contains(path: Path, markers: list[str]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(errors="replace")
    return all(marker in text for marker in markers)


def has_native_warm_start_support(complexa_root: Path) -> bool:
    """Return True when the upstream checkout already exposes compatible hooks."""
    return (
        _file_contains(
            complexa_root / "src/proteinfoundation/datasets/gen_dataset.py",
            ["seed_binder_pdb_path", "warm_start_coords_nm"],
        )
        and _file_contains(
            complexa_root / "src/proteinfoundation/proteina.py",
            ["warm_start_initial_state", "partial_simulation"],
        )
        and _file_contains(
            complexa_root / "src/proteinfoundation/search/beam_search.py",
            ["warm_start_initial_state", "warm_start_checkpoints"],
        )
    )


def warm_start_support_status(complexa_root: Path) -> str:
    """Report whether a Proteina-Complexa checkout has compatible warm-start hooks."""
    complexa_root = complexa_root.resolve()
    if not (complexa_root / "src/proteinfoundation").exists():
        raise FileNotFoundError(f"Proteina-Complexa source tree not found: {complexa_root}")
    if has_native_warm_start_support(complexa_root):
        return "native"
    return "missing"


def apply_warm_start_patch(complexa_root: Path, patch_path: Path = DEFAULT_PATCH_PATH) -> str:
    """Apply optional warm-start support from a normal patch artifact."""
    complexa_root = complexa_root.resolve()
    patch_path = patch_path.resolve()
    if not (complexa_root / "src/proteinfoundation").exists():
        raise FileNotFoundError(f"Proteina-Complexa source tree not found: {complexa_root}")
    if not patch_path.exists():
        raise FileNotFoundError(f"Warm-start patch not found: {patch_path}")

    reverse_check = _run_git_apply(["--reverse", "--check"], cwd=complexa_root, patch_path=patch_path)
    if reverse_check.returncode == 0:
        return "already-applied"

    if has_native_warm_start_support(complexa_root):
        return "native"

    check = _run_git_apply(["--check"], cwd=complexa_root, patch_path=patch_path)
    if check.returncode == 0:
        apply = _run_git_apply([], cwd=complexa_root, patch_path=patch_path)
        if apply.returncode != 0:
            raise RuntimeError(apply.stdout)
        return "applied"

    raise RuntimeError(check.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Proteina warm-start support into an upstream checkout.")
    parser.add_argument("complexa_root", type=Path)
    parser.add_argument("--patch-path", type=Path, default=DEFAULT_PATCH_PATH)
    args = parser.parse_args()
    print(apply_warm_start_patch(args.complexa_root, patch_path=args.patch_path))


if __name__ == "__main__":
    main()
