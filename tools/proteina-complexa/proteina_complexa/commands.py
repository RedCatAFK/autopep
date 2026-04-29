from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Iterable

from .config import (
    COMPLEXA_BIN,
    COMPLEXA_ROOT,
    DEFAULT_PIPELINE_CONFIG,
    MAX_PDB_BYTES,
    MAX_RETURNED_PDBS,
    MODEL_DIR,
    RUNS_DIR,
)


def checkpoint_overrides() -> list[str]:
    return [
        f"++ckpt_path={MODEL_DIR}",
        "++ckpt_name=complexa.ckpt",
        f"++autoencoder_ckpt_path={MODEL_DIR / 'complexa_ae.ckpt'}",
    ]


def normalize_design_steps(steps: Iterable[str] | None) -> list[str]:
    allowed = {"generate", "filter", "evaluate", "analyze"}
    normalized = [step for step in (steps or []) if step]
    invalid = [step for step in normalized if step not in allowed]
    if invalid:
        raise ValueError(f"Invalid design steps: {invalid}. Allowed: {sorted(allowed)}")
    return normalized


def normalize_overrides(overrides: Iterable[str] | None) -> list[str]:
    return [override for override in (overrides or []) if override]


def config_path(pipeline_config: str) -> str:
    path = Path(pipeline_config)
    if path.is_absolute():
        return str(path)
    return str(COMPLEXA_ROOT / path)


def design_command(
    *,
    task_name: str,
    run_name: str,
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: Iterable[str] | None = None,
    steps: Iterable[str] | None = None,
) -> list[str]:
    design_steps = normalize_design_steps(steps)
    command = [
        str(COMPLEXA_BIN),
        "design",
        config_path(pipeline_config),
        *checkpoint_overrides(),
        f"++run_name={run_name}",
        f"++generation.task_name={task_name}",
        *normalize_overrides(overrides),
    ]
    if design_steps:
        command.extend(["--steps", *design_steps])
    return command


def smoke_overrides(sample_count: int = 1) -> list[str]:
    sample_count = max(1, int(sample_count))
    return [
        "++generation.search.algorithm=single-pass",
        "++generation.reward_model=null",
        f"++generation.dataloader.batch_size={sample_count}",
        f"++generation.dataloader.dataset.nres.nsamples={sample_count}",
        "++generation.args.nsteps=20",
    ]


def pipeline_config_name(pipeline_config: str) -> str:
    return Path(pipeline_config).stem


def run_output_paths(*, task_name: str, run_name: str, pipeline_config: str) -> dict[str, Path]:
    run_dir = RUNS_DIR / run_name
    config_name = pipeline_config_name(pipeline_config)
    inference_dir = run_dir / "inference" / f"{config_name}_{task_name}_{run_name}"
    evaluation_dir = run_dir / "evaluation_results" / f"{config_name}_{task_name}_{run_name}"
    hydra_dir = run_dir / "logs" / "hydra_outputs" / "${now:%Y-%m-%d}" / "${now:%H-%M-%S}"
    return {
        "run_dir": run_dir,
        "inference_dir": inference_dir,
        "evaluation_dir": evaluation_dir,
        "hydra_dir": hydra_dir,
    }


def run_output_overrides(*, task_name: str, run_name: str, pipeline_config: str) -> list[str]:
    paths = run_output_paths(task_name=task_name, run_name=run_name, pipeline_config=pipeline_config)
    return [
        f"++root_path={paths['inference_dir']}",
        f"++sample_storage_path={paths['inference_dir']}",
        f"++output_dir={paths['evaluation_dir']}",
        f"++results_dir={paths['evaluation_dir']}",
        f"++hydra.run.dir={paths['hydra_dir']}",
    ]


def read_structure_text(path: Path) -> str:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt").read()
    return path.read_text()


def tail_text(path: Path, *, limit: int = 12000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(errors="replace")
    return text[-limit:]


def collect_run_log_tails(
    run_dir: Path,
    *,
    exclude: set[Path] | None = None,
    limit: int = 12000,
) -> str:
    log_paths = sorted(run_dir.glob("logs/**/*.log"), key=lambda path: path.stat().st_mtime)
    if exclude:
        log_paths = [path for path in log_paths if path not in exclude]
    if not log_paths:
        return ""
    sections = []
    for path in log_paths[-6:]:
        relative = path.relative_to(run_dir)
        sections.append(f"--- {relative} ---\n{tail_text(path, limit=limit)}")
    return "\n\n".join(sections)


def collect_generated_pdbs(
    *,
    inference_dir: Path,
    max_files: int = MAX_RETURNED_PDBS,
    max_file_bytes: int = MAX_PDB_BYTES,
) -> list[dict[str, Any]]:
    if not inference_dir.exists():
        return []

    pdb_paths = sorted(
        (
            path
            for path in inference_dir.rglob("*.pdb")
            if path.is_file() and path.stat().st_size <= max_file_bytes
        ),
        key=lambda path: str(path),
    )
    pdbs = []
    for rank, path in enumerate(pdb_paths[:max_files], start=1):
        pdbs.append(
            {
                "rank": rank,
                "filename": path.name,
                "path": str(path),
                "relative_path": str(path.relative_to(inference_dir)),
                "pdb": path.read_text(errors="replace"),
            }
        )
    return pdbs
