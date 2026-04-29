from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from .config import COMPLEXA_ROOT, SEED_BINDER_DIR
from .preprocessing import sanitize_name

SEED_BINDER_OVERRIDE_PREFIX = "++generation.dataloader.dataset.conditional_features.0."


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
            ["seed_binder_pdb_path", "warm_start_coords_nm", "_seed_binder_list"],
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


def ensure_warm_start_support(complexa_root: Path = COMPLEXA_ROOT) -> str:
    status = warm_start_support_status(complexa_root)
    print(f"Proteina warm-start support: {status}", flush=True)
    if status == "missing":
        raise RuntimeError(
            "Proteina warm-start hooks are not installed in this image. "
            "Rebuild the Modal image with patches/proteina-warm-start.patch or use a custom Proteina-Complexa image."
        )
    return status


def seed_binder_remote_path(
    *,
    task_name: str,
    run_name: str,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_index: int | None = None,
) -> Path:
    safe_task_name = sanitize_name(task_name)
    safe_run_name = sanitize_name(run_name)
    seed_name = Path(seed_binder_filename).name
    seed_path = Path(seed_name)
    if seed_path.suffix.lower() == ".gz":
        suffix = seed_path.with_suffix("").suffix
    else:
        suffix = seed_path.suffix
    if suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
        suffix = ".pdb"
    if seed_binder_index is None:
        return SEED_BINDER_DIR / f"{safe_task_name}_{safe_run_name}{suffix}"
    seed_stem = seed_path.with_suffix("").stem if seed_path.suffix.lower() == ".gz" else seed_path.stem
    safe_seed_name = sanitize_name(seed_stem or f"seed_{seed_binder_index}")
    return SEED_BINDER_DIR / f"{safe_task_name}_{safe_run_name}_seed_{seed_binder_index}_{safe_seed_name}{suffix}"


def write_seed_binder_structure(
    *,
    task_name: str,
    run_name: str,
    seed_binder_text: str,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_index: int | None = None,
) -> Path:
    from .modal_resources import data_volume

    SEED_BINDER_DIR.mkdir(parents=True, exist_ok=True)
    seed_path = seed_binder_remote_path(
        task_name=task_name,
        run_name=run_name,
        seed_binder_filename=seed_binder_filename,
        seed_binder_index=seed_binder_index,
    )
    seed_path.write_text(seed_binder_text)
    data_volume.commit()
    return seed_path


def _hydra_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return json.dumps([str(item) if item is not None else None for item in value], separators=(",", ":"))
    return str(value)


def seed_binder_overrides(
    *,
    seed_binder_path: Path | Sequence[Path],
    seed_binder_chain: str | Sequence[str | None] | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
) -> list[str]:
    overrides = [f"{SEED_BINDER_OVERRIDE_PREFIX}seed_binder_pdb_path={_hydra_value(seed_binder_path)}"]
    if seed_binder_chain:
        overrides.append(f"{SEED_BINDER_OVERRIDE_PREFIX}seed_binder_chain={_hydra_value(seed_binder_chain)}")
    if seed_binder_noise_level is not None:
        overrides.append(f"{SEED_BINDER_OVERRIDE_PREFIX}seed_binder_noise_level={float(seed_binder_noise_level)}")
    if seed_binder_start_t is not None:
        overrides.append(f"{SEED_BINDER_OVERRIDE_PREFIX}seed_binder_start_t={float(seed_binder_start_t)}")
    if seed_binder_num_steps is not None:
        overrides.append(f"{SEED_BINDER_OVERRIDE_PREFIX}seed_binder_num_steps={int(seed_binder_num_steps)}")
    return overrides


def _same_optional_value(seed_binders: Sequence[dict[str, Any]], key: str) -> Any:
    values = [seed.get(key) for seed in seed_binders if seed.get(key) is not None]
    if not values:
        return None
    first = values[0]
    if any(value != first for value in values[1:]):
        raise ValueError(f"Batched warm starts require the same {key} for every seed")
    return first


def warm_start_batch_overrides(
    *,
    task_name: str,
    run_name: str,
    seed_binders: Sequence[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    if not seed_binders:
        return [], {"mode": "cold"}

    shared_noise_level = _same_optional_value(seed_binders, "noise_level")
    shared_start_t = _same_optional_value(seed_binders, "start_t")
    shared_num_steps = _same_optional_value(seed_binders, "num_steps")
    support_status = ensure_warm_start_support()
    seed_paths = []
    seed_chains = []
    for index, seed_binder in enumerate(seed_binders):
        seed_path = write_seed_binder_structure(
            task_name=task_name,
            run_name=run_name,
            seed_binder_text=str(seed_binder["structure_text"]),
            seed_binder_filename=str(seed_binder.get("filename") or f"seed_binder_{index}.pdb"),
            seed_binder_index=index,
        )
        seed_paths.append(seed_path)
        seed_chains.append(seed_binder.get("chain"))

    chain_override: str | Sequence[str | None] | None
    chain_override = seed_chains if any(seed_chains) else None
    return (
        seed_binder_overrides(
            seed_binder_path=seed_paths,
            seed_binder_chain=chain_override,
            seed_binder_noise_level=shared_noise_level,
            seed_binder_start_t=shared_start_t,
            seed_binder_num_steps=shared_num_steps,
        ),
        {
            "mode": "warm",
            "seed_binder_count": len(seed_paths),
            "seed_binder_paths": [str(seed_path) for seed_path in seed_paths],
            "support_status": support_status,
        },
    )


def warm_start_overrides(
    *,
    task_name: str,
    run_name: str,
    seed_binder_text: str | None,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_chain: str | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
) -> tuple[list[str], dict[str, str]]:
    if not seed_binder_text:
        return [], {"mode": "cold"}

    support_status = ensure_warm_start_support()
    seed_path = write_seed_binder_structure(
        task_name=task_name,
        run_name=run_name,
        seed_binder_text=seed_binder_text,
        seed_binder_filename=seed_binder_filename,
    )
    return (
        seed_binder_overrides(
            seed_binder_path=seed_path,
            seed_binder_chain=seed_binder_chain,
            seed_binder_noise_level=seed_binder_noise_level,
            seed_binder_start_t=seed_binder_start_t,
            seed_binder_num_steps=seed_binder_num_steps,
        ),
        {
            "mode": "warm",
            "seed_binder_path": str(seed_path),
            "support_status": support_status,
        },
    )
