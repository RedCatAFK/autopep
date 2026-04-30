from __future__ import annotations

from typing import Any, Sequence

from . import commands
from .config import COMPLEXA_ROOT, DEFAULT_PIPELINE_CONFIG
from .logging_utils import log_event
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
    existing_run_logs = commands.collect_log_paths(run_dir / "logs")
    existing_complexa_logs = commands.collect_log_paths(COMPLEXA_ROOT / "logs")

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
            log_event(
                "warm_start_setup_failed",
                run_name=run_name,
                task_name=task_name,
                mode="batched",
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
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
            log_event(
                "warm_start_setup_failed",
                run_name=run_name,
                task_name=task_name,
                mode="single",
                error_type=exc.__class__.__name__,
                error=str(exc),
            )

    log_event(
        "warm_start_setup_completed",
        run_name=run_name,
        task_name=task_name,
        warm_start=warm_start,
        seed_override_count=len(seed_overrides),
    )

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
    log_event(
        "complexa_command_starting",
        run_name=run_name,
        task_name=task_name,
        pipeline_config=pipeline_config,
        steps=list(steps or []),
        command_preview=command,
        override_count=len(commands.normalize_overrides(overrides)),
        seed_override_count=len(seed_overrides),
    )
    try:
        output = run_complexa(command, cwd=COMPLEXA_ROOT)
    except Exception as exc:
        log_event(
            "complexa_command_failed",
            run_name=run_name,
            task_name=task_name,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        log_tail_sections = []
        run_log_tails = commands.collect_run_log_tails(run_dir, exclude=existing_run_logs)
        if run_log_tails:
            log_tail_sections.append(f"--- run volume log tails ---\n{run_log_tails}")
        complexa_log_tails = commands.collect_complexa_log_tails(COMPLEXA_ROOT, exclude=existing_complexa_logs)
        if complexa_log_tails:
            log_tail_sections.append(f"--- complexa stage log tails ---\n{complexa_log_tails}")
        runs_volume.commit()
        if log_tail_sections:
            log_tails = "\n\n".join(log_tail_sections)
            raise RuntimeError(f"{exc}\n--- failure log tails ---\n{log_tails}") from exc
        raise

    runs_volume.commit()
    log_event(
        "complexa_command_completed",
        run_name=run_name,
        task_name=task_name,
        log_tail_chars=len(output),
    )
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
