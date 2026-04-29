from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .constants import VALID_AA


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def normalize_sequence(sequence: str) -> str:
    return "".join(str(sequence).split()).upper()


def invalid_tokens(sequence: str) -> set[str]:
    return set(normalize_sequence(sequence)) - set(VALID_AA)


def is_valid_sequence(sequence: str) -> bool:
    normalized = normalize_sequence(sequence)
    return bool(normalized) and set(normalized).issubset(VALID_AA)


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def compact_counts(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return dict(sorted(counts.items()))

