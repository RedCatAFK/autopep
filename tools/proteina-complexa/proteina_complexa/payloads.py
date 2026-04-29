from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


MAX_STRUCTURE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class TargetPayload:
    structure_text: str
    filename: str
    target_name: str | None
    target_input: str | None
    chains: str | None
    hotspot_residues: list[str]
    binder_length: list[int]


@dataclass(frozen=True)
class WarmStartPayload:
    structure_text: str
    filename: str
    chain: str | None
    noise_level: float | None
    start_t: float | None
    num_steps: int | None


@dataclass(frozen=True)
class DesignPayload:
    target: TargetPayload
    run_name: str
    pipeline_config: str
    overrides: list[str]
    design_steps: list[str]
    smoke: bool
    warm_start: WarmStartPayload | None


_MISSING = object()


def normalize_design_payload(
    payload: dict[str, Any],
    *,
    default_pipeline_config: str,
    default_binder_length: list[int],
) -> DesignPayload:
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")

    target = _target_payload(payload, default_binder_length=default_binder_length)
    warm_start = _warm_start_payload(payload)
    action = str(payload.get("action") or "").strip().lower()
    allowed_actions = {"", "design", "design-cif", "predict", "smoke", "smoke-cif"}
    if action not in allowed_actions:
        raise ValueError(f"Unsupported action {action!r}. Use design or smoke-cif.")

    smoke = _as_bool(
        _first_present(payload, "smoke", "smoke_test", default=action in {"smoke", "smoke-cif"}),
        default=False,
        field_name="smoke",
    )
    run_name = str(payload.get("run_name") or _default_run_name(target.target_name)).strip()
    if not run_name:
        raise ValueError("run_name must not be empty")

    return DesignPayload(
        target=target,
        run_name=run_name,
        pipeline_config=str(payload.get("pipeline_config") or default_pipeline_config),
        overrides=_as_str_list(_first_present(payload, "overrides", "overrides_json", default=[]), "overrides"),
        design_steps=_as_str_list(
            _first_present(payload, "design_steps", "steps", "design_steps_json", default=[]),
            "design_steps",
        ),
        smoke=smoke,
        warm_start=warm_start,
    )


def _target_payload(payload: dict[str, Any], *, default_binder_length: list[int]) -> TargetPayload:
    nested = payload.get("target")
    if isinstance(nested, str):
        nested_payload: dict[str, Any] = {"structure": nested}
    elif nested is None:
        nested_payload = {}
    elif isinstance(nested, dict):
        nested_payload = nested
    else:
        raise ValueError("target must be an object or a structure text string")

    structure_text = _structure_text(
        _first_present(
            nested_payload,
            "structure",
            "structure_text",
            "target_structure",
            "cif",
            "pdb",
            default=_first_present(
                payload,
                "target_structure",
                "target_structure_text",
                "target_cif",
                "target_cif_text",
                "target_pdb",
                "target_pdb_text",
                "cif",
                default=_MISSING,
            ),
        ),
        field_name="target.structure",
    )
    filename = str(
        _first_present(
            nested_payload,
            "filename",
            "target_filename",
            "cif_filename",
            "pdb_filename",
            default=_first_present(
                payload,
                "target_filename",
                "cif_filename",
                "pdb_filename",
                default="target.cif",
            ),
        )
    )

    target_name = _optional_str(
        _first_present(
            nested_payload,
            "target_name",
            "name",
            "task_name",
            default=_first_present(payload, "target_name", "task_name", default=None),
        )
    )
    target_input = _optional_str(
        _first_present(nested_payload, "target_input", "input", default=payload.get("target_input"))
    )
    chains = _optional_str(_first_present(nested_payload, "chains", default=payload.get("chains")))
    hotspot_residues = _as_str_list(
        _first_present(
            nested_payload,
            "hotspot_residues",
            "hotspots",
            default=_first_present(payload, "hotspot_residues", "hotspots", "hotspot_residues_json", default=[]),
        ),
        "hotspot_residues",
    )
    binder_length = _as_int_pair(
        _first_present(
            nested_payload,
            "binder_length",
            default=_first_present(payload, "binder_length", "binder_length_json", default=default_binder_length),
        ),
        field_name="binder_length",
    )

    return TargetPayload(
        structure_text=structure_text,
        filename=filename,
        target_name=target_name,
        target_input=target_input,
        chains=chains,
        hotspot_residues=hotspot_residues,
        binder_length=binder_length,
    )


def _warm_start_payload(payload: dict[str, Any]) -> WarmStartPayload | None:
    nested = payload.get("warm_start")
    if nested is None:
        nested = payload.get("seed_binder")

    if isinstance(nested, str):
        nested_payload: dict[str, Any] = {"structure": nested}
    elif nested is None:
        nested_payload = {}
    elif isinstance(nested, dict):
        nested_payload = nested
    else:
        raise ValueError("warm_start must be an object or a structure text string")

    structure = _first_present(
        nested_payload,
        "structure",
        "structure_text",
        "seed_binder_structure",
        "pdb",
        "cif",
        default=_first_present(
            payload,
            "seed_binder_structure",
            "seed_binder_structure_text",
            "seed_binder_pdb",
            "seed_binder_pdb_text",
            "seed_binder_cif",
            "warm_start_structure",
            default=None,
        ),
    )
    if structure is None or structure == "":
        return None

    return WarmStartPayload(
        structure_text=_structure_text(structure, field_name="warm_start.structure"),
        filename=str(
            _first_present(
                nested_payload,
                "filename",
                "seed_binder_filename",
                default=payload.get("seed_binder_filename") or "seed_binder.pdb",
            )
        ),
        chain=_optional_str(
            _first_present(nested_payload, "chain", "seed_binder_chain", default=payload.get("seed_binder_chain"))
        ),
        noise_level=_optional_float(
            _first_present(
                nested_payload,
                "noise_level",
                "seed_binder_noise_level",
                default=payload.get("seed_binder_noise_level"),
            ),
            field_name="seed_binder_noise_level",
        ),
        start_t=_optional_float(
            _first_present(nested_payload, "start_t", "seed_binder_start_t", default=payload.get("seed_binder_start_t")),
            field_name="seed_binder_start_t",
        ),
        num_steps=_optional_int(
            _first_present(
                nested_payload,
                "num_steps",
                "seed_binder_num_steps",
                default=payload.get("seed_binder_num_steps"),
            ),
            field_name="seed_binder_num_steps",
        ),
    )


def _first_present(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _structure_text(value: Any, *, field_name: str) -> str:
    if value is _MISSING or value is None:
        raise ValueError(f"{field_name} is required")
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string containing CIF/PDB text")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is empty")
    if len(text.encode("utf-8")) > MAX_STRUCTURE_BYTES:
        raise ValueError(f"{field_name} exceeds {MAX_STRUCTURE_BYTES} bytes")
    if "\n" not in text and Path(text).suffix.lower() in {".pdb", ".cif", ".mmcif", ".gz"}:
        raise ValueError(f"{field_name} must contain file contents, not a local path")
    return text + "\n"


def _as_str_list(value: Any, field_name: str) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parsed = _maybe_json(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        if parsed is not value:
            if parsed is None or parsed == "":
                return []
            raise ValueError(f"{field_name} must be a JSON list")
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ValueError(f"{field_name} must be a list")


def _as_int_pair(value: Any, *, field_name: str) -> list[int]:
    if isinstance(value, str):
        value = _maybe_json(value)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field_name} must contain [min_length, max_length]")
    try:
        return [int(value[0]), int(value[1])]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} values must be integers") from exc


def _as_bool(value: Any, *, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    return parsed if parsed > 0 else None


def _maybe_json(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped[0] not in "[{\"0123456789-tfn":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _default_run_name(target_name: str | None) -> str:
    prefix = re.sub(r"[^A-Za-z0-9_]+", "_", target_name or "complexa").strip("_")
    if not prefix:
        prefix = "complexa"
    return f"{prefix}_{uuid4().hex[:12]}"
