from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

KNOWN_ARTIFACT_TOOL_MARKERS = (
    "literature",
    "search",
    "fetch",
    "proteina",
    "chai",
    "scorer",
    "score",
)

PATH_FIELDS = (
    "path",
    "output_path",
    "artifact_path",
    "artifact_paths",
    "file_path",
    "file_paths",
    "paths",
    "files",
    "sandbox_path",
    "response_path",
    "input_fasta_path",
    "cif_path",
    "pdb_path",
    "interaction_response_path",
    "quality_response_path",
    "summary_path",
)


def is_allowed_output_path(path: Path | str, allowed_roots: Iterable[Path | str]) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    for root in allowed_roots:
        allowed_root = Path(root).expanduser().resolve(strict=False)
        if candidate == allowed_root or allowed_root in candidate.parents:
            return True
    return False


def classify_artifact_kind(path: Path | str) -> str:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    name = candidate.name.lower()

    if "paper" in name or "literature" in name or name.endswith(".bib"):
        return "literature"
    if suffix in {".cif", ".pdb", ".mmcif"}:
        return "structure"
    if suffix in {".csv", ".tsv", ".xlsx", ".parquet"}:
        return "table"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if suffix in {".txt", ".md", ".log"}:
        return "text"
    if suffix in {".json", ".jsonl", ".xml", ".yaml", ".yml"}:
        return "data"
    return "file"


def generate_r2_key(run_id: str, path: Path | str) -> str:
    filename = Path(path).name
    return f"runs/{run_id}/artifacts/{filename}"


def scan_allowed_outputs(allowed_roots: Iterable[Path | str]) -> list[Path]:
    files: list[Path] = []
    for root in allowed_roots:
        allowed_root = Path(root)
        if not allowed_root.exists():
            continue
        if allowed_root.is_file():
            files.append(allowed_root)
            continue
        files.extend(path for path in allowed_root.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: (len(path.parts), str(path)))


def artifact_paths_from_tool_result(tool_name: str, result: Any) -> list[Path]:
    if not _is_artifact_tool(tool_name) or not isinstance(result, dict):
        return []

    paths: list[Path] = []
    _collect_known_tool_paths(tool_name, result, paths)
    for field in PATH_FIELDS:
        _collect_paths(result.get(field), paths)
    return _dedupe(paths)


def _is_artifact_tool(tool_name: str) -> bool:
    normalized = tool_name.lower()
    return any(marker in normalized for marker in KNOWN_ARTIFACT_TOOL_MARKERS)


def _collect_paths(value: Any, paths: list[Path]) -> None:
    if isinstance(value, str):
        if _looks_like_local_path(value):
            paths.append(Path(value))
        return
    if isinstance(value, Path):
        paths.append(value)
        return
    if isinstance(value, dict):
        for key in PATH_FIELDS:
            _collect_paths(value.get(key), paths)
        return
    if isinstance(value, list | tuple | set):
        for item in value:
            _collect_paths(item, paths)


def _collect_known_tool_paths(tool_name: str, result: dict[str, Any], paths: list[Path]) -> None:
    normalized = tool_name.lower()
    if "literature" in normalized or "search_pdb" in normalized or "fetch_pdb" in normalized:
        _collect_paths(result.get("sandbox_path"), paths)
    if "proteina" in normalized:
        _collect_paths(result.get("response_path"), paths)
        _collect_paths(result.get("candidates"), paths)
    if "chai" in normalized:
        _collect_paths(result.get("input_fasta_path"), paths)
        _collect_paths(result.get("response_path"), paths)
        _collect_paths(result.get("structures"), paths)
    if "scorer" in normalized or "score" in normalized:
        _collect_paths(result.get("interaction_response_path"), paths)
        _collect_paths(result.get("quality_response_path"), paths)
        _collect_paths(result.get("summary_path"), paths)


def _looks_like_local_path(value: str) -> bool:
    lowered = value.lower()
    return bool(value) and not lowered.startswith(("http://", "https://", "s3://", "r2://"))


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped
