from __future__ import annotations

from typing import Any, Sequence

from . import commands
from .config import COMPLEXA_ROOT, DEFAULT_PIPELINE_CONFIG
from .runtime import run_complexa
from .warm_start import warm_start_batch_overrides, warm_start_overrides


def run_design(
    *,
    task_name: str,
    run_name: str,
    pipeline_config: str = DEFAULT_PIPELINE_CONFIG,
    overrides: list[str] | None = None,
    steps: list[str] | None = None,
    seed_binder_text: str | None = None,
    seed_binder_filename: str = "seed_binder.pdb",
    seed_binder_chain: str | None = None,
    seed_binder_noise_level: float | None = None,
    seed_binder_start_t: float | None = None,
    seed_binder_num_steps: int | None = None,
    seed_binders: Sequence[dict[str, Any]] | None = None,
    include_generated_pdbs: bool = False,
) -> dict:
    """Run one Complexa design job in the current Modal container."""
    from .modal_resources import data_volume, model_volume, runs_volume

    model_volume.reload()
    data_volume.reload()
    runs_volume.reload()

    run_paths = commands.run_output_paths(
        task_name=task_name,
        run_name=run_name,
        pipeline_config=pipeline_config,
    )
    run_dir = run_paths["run_dir"]
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_logs = set(run_dir.glob("logs/**/*.log"))

    seed_overrides: list[str] = []
    warm_start: dict[str, Any] = {"mode": "cold"}
    if seed_binders:
        try:
            seed_overrides, warm_start = warm_start_batch_overrides(
                task_name=task_name,
                run_name=run_name,
                seed_binders=seed_binders,
            )
        except Exception as exc:
            print(f"Batched warm-start setup failed; falling back to cold start: {exc}", flush=True)
    elif seed_binder_text:
        try:
            seed_overrides, warm_start = warm_start_overrides(
                task_name=task_name,
                run_name=run_name,
                seed_binder_text=seed_binder_text,
                seed_binder_filename=seed_binder_filename,
                seed_binder_chain=seed_binder_chain,
                seed_binder_noise_level=seed_binder_noise_level,
                seed_binder_start_t=seed_binder_start_t,
                seed_binder_num_steps=seed_binder_num_steps,
            )
        except Exception as exc:
            print(f"Warm-start setup failed; falling back to cold start: {exc}", flush=True)

    command = commands.design_command(
        task_name=task_name,
        run_name=run_name,
        pipeline_config=pipeline_config,
        overrides=[
            *commands.run_output_overrides(
                task_name=task_name,
                run_name=run_name,
                pipeline_config=pipeline_config,
            ),
            *commands.normalize_overrides(overrides),
            *seed_overrides,
        ],
        steps=steps,
    )
    try:
        output = run_complexa(command, cwd=COMPLEXA_ROOT)
    except Exception as exc:
        log_tails = commands.collect_run_log_tails(run_dir, exclude=existing_logs)
        runs_volume.commit()
        if log_tails:
            raise RuntimeError(f"{exc}\n--- run log tails ---\n{log_tails}") from exc
        raise

    runs_volume.commit()
    result = {
        "run_name": run_name,
        "task_name": task_name,
        "warm_start": warm_start,
        "log_tail": output[-4000:],
    }
    if include_generated_pdbs:
        pdbs = commands.collect_generated_pdbs(inference_dir=run_paths["inference_dir"])
        result["format"] = "pdb"
        result["count"] = len(pdbs)
        result["pdbs"] = pdbs
        if pdbs:
            result["pdb_filename"] = pdbs[0]["filename"]
            result["pdb"] = pdbs[0]["pdb"]
    return result
