from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import main


def _candidate_score(path: Path, chain_order: list[str]) -> tuple[int, str]:
    score = 0
    path_text = str(path)
    if "tree_edits" in path_text:
        score += 20
    if "warmstart" in path.name.lower():
        score += 10
    if len(chain_order) >= 3:
        score += 5
    if "C" in chain_order:
        score += 5
    return -score, path_text


def _find_warm_start_pdb() -> tuple[Path, list[str], dict[str, str]]:
    candidates: list[tuple[tuple[int, str], Path, list[str], dict[str, str]]] = []
    for path in sorted(main.SANDBOX_ROOT.rglob("*.pdb")):
        if ".venv" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chain_order = main._extract_pdb_chain_order(text)
        sequences = main._extract_pdb_sequences(text)
        if not chain_order or not sequences:
            continue
        if "C" not in sequences and len(sequences) < 3:
            continue
        candidates.append((_candidate_score(path, chain_order), path, chain_order, sequences))

    if not candidates:
        raise RuntimeError("No multi-chain warm-start PDB fixture found under sandbox.")

    _, path, chain_order, sequences = sorted(candidates, key=lambda item: item[0])[0]
    return path, chain_order, sequences


def _find_target_cif() -> Path:
    candidates: list[tuple[int, str, Path]] = []
    for path in sorted(main.SANDBOX_ROOT.rglob("*.cif")):
        if ".venv" in path.parts:
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:200]
        except OSError:
            continue
        if head.lstrip().startswith("data_"):
            score = 0
            if "pdb" in path.parts:
                score -= 20
            if path.name[:4].isalnum() and len(path.stem) == 4:
                score -= 5
            candidates.append((score, str(path), path))
    if candidates:
        return sorted(candidates)[0][2]
    raise RuntimeError("No target CIF fixture found under sandbox.")


def _copy_fixture(source: Path, name: str) -> Path:
    target = main._sandbox_path(f"warm_start_sanity/{name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    target = dict(redacted.get("target") or {})
    if isinstance(target.get("structure"), str):
        target["structure"] = f"<{len(target['structure'])} chars>"
    redacted["target"] = target

    warm_start = dict(redacted.get("warm_start") or {})
    if isinstance(warm_start.get("structure"), str):
        warm_start["structure"] = f"<{len(warm_start['structure'])} chars>"
    redacted["warm_start"] = warm_start
    return redacted


async def _dry_run(target_path: str, warm_start_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    captured_payload: dict[str, Any] = {}
    warm_start_text = main._sandbox_path(warm_start_path).read_text(encoding="utf-8")

    async def fake_post_modal_json(
        *,
        base_url: str,
        api_key: str,
        path: str,
        payload: Mapping[str, Any],
        timeout_seconds: int = main.DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        del base_url, api_key, path, timeout_seconds
        captured_payload.update(dict(payload))
        return {
            "ok": True,
            "dry_run": True,
            "pdbs": [
                {
                    "filename": "dry_run_candidate.pdb",
                    "pdb": warm_start_text,
                },
            ],
        }

    original_modal_config = main._modal_config
    original_post_modal_json = main._post_modal_json
    main._modal_config = lambda *_args, **_kwargs: ("https://example.invalid", "dry-run-key")  # type: ignore[assignment]
    main._post_modal_json = fake_post_modal_json  # type: ignore[assignment]
    try:
        result = await main._run_proteina(
            target_path=target_path,
            target_input="A1-306,B1-301",
            hotspot_residues=["A41", "A145", "A166"],
            binder_length_min=60,
            binder_length_max=90,
            num_candidates=3,
            run_name="warm_start_sanity",
            warm_start_path=warm_start_path,
            nsteps=20,
        )
    finally:
        main._modal_config = original_modal_config  # type: ignore[assignment]
        main._post_modal_json = original_post_modal_json  # type: ignore[assignment]

    return captured_payload, result


async def main_async() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run the Proteina warm-start payload with sandbox fixtures.",
    )
    parser.add_argument("--warm-start", help="Sandbox-relative or absolute PDB path to use as seed.")
    parser.add_argument("--target", help="Sandbox-relative or absolute CIF path to use as target.")
    args = parser.parse_args()

    main._ensure_dirs()

    if args.warm_start:
        warm_source = Path(args.warm_start).expanduser()
        if not warm_source.is_absolute():
            warm_source = main.SANDBOX_ROOT / args.warm_start
        warm_text = warm_source.read_text(encoding="utf-8", errors="replace")
        source_chain_order = main._extract_pdb_chain_order(warm_text)
        source_sequences = main._extract_pdb_sequences(warm_text)
    else:
        warm_source, source_chain_order, source_sequences = _find_warm_start_pdb()

    if args.target:
        target_source = Path(args.target).expanduser()
        if not target_source.is_absolute():
            target_source = main.SANDBOX_ROOT / args.target
    else:
        target_source = _find_target_cif()

    copied_warm = _copy_fixture(warm_source, f"seed_{warm_source.name}")
    copied_target = _copy_fixture(target_source, f"target_{target_source.name}")
    warm_rel = main._relative_to_sandbox(copied_warm)
    target_rel = main._relative_to_sandbox(copied_target)

    warm_payload = main._warm_start_payload_from_file(copied_warm)
    inferred_chain = warm_payload.get("chain")
    binder_chain = main._select_binder_chain(source_sequences)
    assert inferred_chain == "C", f"expected inferred warm_start.chain C, got {inferred_chain!r}"
    assert binder_chain == "C", f"expected selected binder chain C, got {binder_chain!r}"

    captured_payload, result = await _dry_run(target_rel, warm_rel)
    captured_warm = captured_payload.get("warm_start")
    assert isinstance(captured_warm, Mapping), "run_proteina did not send warm_start"
    assert captured_warm.get("chain") == "C", captured_warm
    assert captured_warm.get("filename") == copied_warm.name, captured_warm
    assert result["candidates"][0]["binder_chain"] == "C", result["candidates"][0]

    summary = {
        "status": "ok",
        "sandbox_run": main.SANDBOX_RUN_ID,
        "source_warm_start": str(warm_source),
        "source_target": str(target_source),
        "copied_warm_start": warm_rel,
        "copied_target": target_rel,
        "source_chain_order": source_chain_order,
        "inferred_warm_start_chain": inferred_chain,
        "selected_binder_chain": binder_chain,
        "payload_preview": _redact_payload(captured_payload),
        "proteina_candidate": result["candidates"][0],
    }
    summary_path = main._sandbox_path("warm_start_sanity/summary.json")
    main._write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nWrote summary: {main._relative_to_sandbox(summary_path)}")


if __name__ == "__main__":
    asyncio.run(main_async())
