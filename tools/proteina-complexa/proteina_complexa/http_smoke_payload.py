from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import shlex
from pathlib import Path
from typing import Mapping, Sequence


def read_structure_text(path: Path | str) -> str:
    structure_path = Path(path)
    if structure_path.suffix == ".gz":
        with gzip.open(structure_path, "rt") as handle:
            return handle.read()
    return structure_path.read_text()


def expand_seed_binder_paths(raw_paths: str) -> list[Path]:
    paths: list[str] = []
    for token in shlex.split(raw_paths.strip()):
        matches = glob.glob(token)
        paths.extend(matches or [token])
    resolved = [Path(path) for path in paths]
    missing = [str(path) for path in resolved if not path.is_file()]
    if missing:
        raise ValueError(f"Warm-start seed binder not found: {', '.join(missing)}")
    if not resolved:
        raise ValueError("SEED_BINDERS did not match any warm-start seed files")
    return sorted(dict.fromkeys(resolved))


def _structure_filename(path: Path) -> str:
    return path.name.removesuffix(".gz")


def build_http_smoke_payload(
    *,
    target_cif: Path | str,
    seed_binders: Sequence[Path | str],
    target_name: str,
    target_input: str,
    binder_length: Sequence[int],
    hotspot_residues: Sequence[str],
    seed_binder_chain: str | None,
    seed_binder_noise_level: float,
    run_name: str,
) -> dict:
    seed_chain = (seed_binder_chain or "").strip()
    warm_starts = []
    for seed_binder in seed_binders:
        seed_path = Path(seed_binder)
        warm_start = {
            "structure": read_structure_text(seed_path),
            "filename": _structure_filename(seed_path),
            "noise_level": float(seed_binder_noise_level),
        }
        if seed_chain:
            warm_start["chain"] = seed_chain
        warm_starts.append(warm_start)

    target_path = Path(target_cif)
    return {
        "action": "smoke-cif",
        "run_name": run_name,
        "target": {
            "structure": read_structure_text(target_path),
            "filename": _structure_filename(target_path),
            "name": target_name,
            "target_input": target_input,
            "hotspot_residues": list(hotspot_residues),
            "binder_length": [int(item) for item in binder_length],
        },
        "warm_start": warm_starts,
    }


def build_http_smoke_payload_from_env(env: Mapping[str, str] | None = None) -> dict:
    values = env or os.environ
    return build_http_smoke_payload(
        target_cif=values["TARGET_CIF"],
        seed_binders=expand_seed_binder_paths(values["SEED_BINDERS"]),
        target_name=values["TARGET_NAME"],
        target_input=values["TARGET_INPUT"],
        binder_length=json.loads(values["BINDER_LENGTH_JSON"]),
        hotspot_residues=json.loads(values["HOTSPOT_RESIDUES_JSON"]),
        seed_binder_chain=values.get("SEED_BINDER_CHAIN", ""),
        seed_binder_noise_level=float(values["SEED_BINDER_NOISE_LEVEL"]),
        run_name=values["RUN_NAME"],
    )


def write_http_smoke_payload(output_path: Path | str, env: Mapping[str, str] | None = None) -> dict:
    payload = build_http_smoke_payload_from_env(env)
    payload_path = Path(output_path)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps(payload))
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Proteina-Complexa HTTP warm-start smoke payload.")
    parser.add_argument("payload_path", type=Path, help="Output JSON payload path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    payload = write_http_smoke_payload(args.payload_path)
    print(f"Prepared {len(payload['warm_start'])} warm-start seed binders")


if __name__ == "__main__":
    main()
