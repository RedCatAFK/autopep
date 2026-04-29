from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import shutil
from pathlib import Path


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
AMBIGUOUS_AA = set("XUBZ")
ALLOWED_AA = STANDARD_AA | AMBIGUOUS_AA
DEFAULT_MAX_SEQUENCE_LENGTH = int(os.getenv("MAX_SEQUENCE_LENGTH", "10000"))
DEFAULT_MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "8"))
MAX_STRUCTURE_BYTES = int(os.getenv("MAX_STRUCTURE_BYTES", str(25 * 1024 * 1024)))
MAX_STRUCTURE_BASE64_CHARS = math.ceil(MAX_STRUCTURE_BYTES * 4 / 3) + 8

PROTEIN_RESIDUES_3 = {
    "ALA",
    "ARG",
    "ASN",
    "ASP",
    "CYS",
    "GLN",
    "GLU",
    "GLY",
    "HIS",
    "ILE",
    "LEU",
    "LYS",
    "MET",
    "PHE",
    "PRO",
    "SER",
    "THR",
    "TRP",
    "TYR",
    "VAL",
    "SEC",
    "PYL",
    "ASX",
    "GLX",
}


class StructureDecodeError(ValueError):
    pass


class StructureTooLargeError(ValueError):
    pass


def normalize_sequence(
    sequence: str,
    *,
    max_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
) -> tuple[str, list[str]]:
    normalized = "".join(sequence.split()).upper()
    if not normalized:
        raise ValueError("sequence cannot be empty")
    if len(normalized) > max_length:
        raise ValueError(f"sequence length exceeds {max_length} residues")

    invalid = sorted(set(normalized) - ALLOWED_AA)
    if invalid:
        raise ValueError(f"sequence contains unsupported amino-acid codes: {''.join(invalid)}")

    warnings = sequence_warnings(normalized)
    return normalized, warnings


def sequence_warnings(sequence: str | None) -> list[str]:
    if not sequence:
        return []
    ambiguous = sorted(set(sequence.upper()) & AMBIGUOUS_AA)
    if not ambiguous:
        return []
    return [
        "Sequence contains accepted ambiguous or uncommon amino-acid codes: "
        + ", ".join(ambiguous)
    ]


def structure_extension(format_name: str) -> str:
    normalized = format_name.lower()
    if normalized == "pdb":
        return ".pdb"
    if normalized in {"cif", "mmcif"}:
        return ".cif"
    raise ValueError(f"unsupported structure format: {format_name}")


def decode_structure_base64(content_base64: str) -> bytes:
    if len(content_base64) > MAX_STRUCTURE_BASE64_CHARS:
        raise StructureTooLargeError(
            f"structure payload exceeds {MAX_STRUCTURE_BYTES} decoded bytes"
        )
    try:
        decoded = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise StructureDecodeError("structure.content_base64 is not valid base64") from exc
    if len(decoded) > MAX_STRUCTURE_BYTES:
        raise StructureTooLargeError(
            f"structure payload exceeds {MAX_STRUCTURE_BYTES} decoded bytes"
        )
    if not decoded.strip():
        raise StructureDecodeError("structure content is empty")
    return decoded


def safe_item_token(item_id: str, *, max_length: int = 80) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", item_id).strip("._-")
    if not token:
        token = "item"
    return token[:max_length]


def write_structure_file(
    work_dir: Path,
    *,
    item_index: int,
    item_id: str,
    format_name: str,
    content_base64: str,
) -> Path:
    payload = decode_structure_base64(content_base64)
    extension = structure_extension(format_name)
    filename = f"{item_index:03d}_{safe_item_token(item_id)}{extension}"
    path = work_dir / filename
    path.write_bytes(payload)
    return path


def write_fasta(path: Path, records: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for name, sequence in records.items():
            handle.write(f">{name}\n")
            for start in range(0, len(sequence), 80):
                handle.write(sequence[start : start + 80] + "\n")


def write_pairs_tsv(path: Path, pairs: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for left, right in pairs:
            handle.write(f"{left}\t{right}\n")


def parse_dscript_predictions(output_prefix: Path) -> dict[tuple[str, str], float]:
    candidates = [output_prefix]
    if output_prefix.suffix:
        candidates.append(output_prefix.with_suffix(output_prefix.suffix + ".tsv"))
    candidates.append(Path(f"{output_prefix}.tsv"))

    prediction_file = next((path for path in candidates if path.exists()), None)
    if prediction_file is None:
        raise FileNotFoundError(
            f"D-SCRIPT prediction output was not found at {output_prefix} or {output_prefix}.tsv"
        )

    predictions: dict[tuple[str, str], float] = {}
    with prediction_file.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            columns = stripped.split("\t")
            if len(columns) < 3:
                columns = stripped.split()
            if len(columns) < 3:
                raise ValueError(
                    f"could not parse D-SCRIPT output line {line_number}: {stripped}"
                )
            try:
                score = float(columns[2])
            except ValueError as exc:
                if line_number == 1 and columns[2].lower() in {"score", "probability"}:
                    continue
                raise ValueError(
                    f"could not parse D-SCRIPT score on line {line_number}: {columns[2]}"
                ) from exc
            predictions[(columns[0], columns[1])] = score
    return predictions


def infer_protein_chains(path: Path, format_name: str) -> list[str]:
    chains = _infer_chains_with_biopython(path, format_name)
    if chains:
        return chains
    if format_name.lower() == "pdb":
        return _infer_chains_from_pdb_text(path)
    return []


def _infer_chains_with_biopython(path: Path, format_name: str) -> list[str]:
    try:
        if format_name.lower() == "pdb":
            from Bio.PDB import PDBParser

            parser = PDBParser(QUIET=True)
        else:
            from Bio.PDB import MMCIFParser

            parser = MMCIFParser(QUIET=True)
        structure = parser.get_structure("complex", str(path))
    except Exception:
        return []

    chain_ids: list[str] = []
    for chain in structure.get_chains():
        has_protein_residue = any(
            residue.id[0] == " " and residue.get_resname().upper() in PROTEIN_RESIDUES_3
            for residue in chain.get_residues()
        )
        if has_protein_residue:
            chain_ids.append(chain.id)
    return chain_ids


def _infer_chains_from_pdb_text(path: Path) -> list[str]:
    chain_ids: list[str] = []
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 22:
                    continue
                residue = line[17:20].strip().upper()
                if residue not in PROTEIN_RESIDUES_3:
                    continue
                chain_id = line[21].strip()
                if chain_id and chain_id not in seen:
                    seen.add(chain_id)
                    chain_ids.append(chain_id)
    except OSError:
        return []
    return chain_ids


def command_available(command: str) -> bool:
    return shutil.which(command) is not None


def short_hash(value: str | bytes | None) -> str:
    if value is None:
        return "none"
    if isinstance(value, str):
        value = value.encode("utf-8", errors="replace")
    return hashlib.sha256(value).hexdigest()[:12]
