from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from .io_utils import is_valid_sequence, normalize_sequence, sequence_hash


@dataclass(frozen=True)
class FastaRecord:
    header: str
    sequence: str


def parse_fasta(text: str) -> list[FastaRecord]:
    records: list[FastaRecord] = []
    header: str | None = None
    chunks: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append(FastaRecord(header=header, sequence=normalize_sequence("".join(chunks))))
            header = line[1:].strip()
            chunks = []
        else:
            chunks.append(line)

    if header is not None:
        records.append(FastaRecord(header=header, sequence=normalize_sequence("".join(chunks))))
    return records


def infer_binary_label(header: str) -> int | None:
    lowered = header.lower()
    padded = f" {re.sub(r'[^a-z0-9]+', ' ', lowered)} "

    negative_patterns = (
        r"\bnon\s*amyloidogenic\b",
        r"\bnon\s*amyloid\b",
        r"\bnonamyloid\b",
        r"\bnegative\b",
        r"\bneg\b",
        r"\bnon\s*apr\b",
    )
    for pattern in negative_patterns:
        if re.search(pattern, padded):
            return 0

    positive_patterns = (
        r"\bamyloidogenic\b",
        r"\bamyloid\b",
        r"\bpositive\b",
        r"\bpos\b",
    )
    for pattern in positive_patterns:
        if re.search(pattern, padded):
            return 1

    explicit_patterns = (
        r"(?:^|[|,;\s])label\s*[:=_-]?\s*([01])(?:$|[|,;\s])",
        r"(?:^|[|,;\s])class\s*[:=_-]?\s*([01])(?:$|[|,;\s])",
        r"(?:^|[|,;\s])target\s*[:=_-]?\s*([01])(?:$|[|,;\s])",
        r"(?:^|[|,;\s])([01])(?:$|[|,;\s])",
    )
    for pattern in explicit_patterns:
        match = re.search(pattern, header, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_labeled_hex_fasta(
    text: str,
    *,
    dataset: str,
    manual_labels: dict[str, int] | None = None,
) -> tuple[list[dict], list[str]]:
    manual_labels = manual_labels or {}
    rows: list[dict] = []
    unresolved: list[str] = []

    for record in parse_fasta(text):
        label = manual_labels.get(record.header)
        if label is None:
            label = manual_labels.get(record.sequence)
        if label is None:
            label = infer_binary_label(record.header)
        if label is None:
            unresolved.append(record.header)
            continue
        rows.append(
            {
                "dataset": dataset,
                "header": record.header,
                "sequence": record.sequence,
                "sequence_hash": sequence_hash(record.sequence),
                "label": int(label),
                "is_valid": is_valid_sequence(record.sequence),
                "length": len(record.sequence),
            }
        )
    return rows, unresolved


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._href: str | None = None
        self._text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {name.lower(): value for name, value in attrs}
        self._href = attrs_dict.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.anchors.append((text, self._href))
            self._href = None
            self._text = []


def extract_anupp_download_links(html: str, base_url: str) -> dict[str, str]:
    parser = _AnchorCollector()
    parser.feed(html)
    download_hrefs = [
        urljoin(base_url, href)
        for text, href in parser.anchors
        if href and "download" in text.lower()
    ]
    names = ["hex1279", "hex142", "amy17", "amy37"]
    return {name: href for name, href in zip(names, download_hrefs, strict=False)}


def parse_pseudosequence_text(text: str) -> dict[str, str]:
    pseudosequences: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        allele, sequence = parts[0], normalize_sequence(parts[1])
        if is_valid_sequence(sequence):
            pseudosequences[allele] = sequence
    return pseudosequences


def allele_alias_key(allele: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", allele.upper())


def build_pseudosequence_aliases(pseudosequences: dict[str, str]) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for allele, sequence in pseudosequences.items():
        aliases[allele_alias_key(allele)] = (allele, sequence)
    return aliases


def parse_allelelist_text(text: str) -> dict[str, list[str]]:
    allelelist: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[\s,;]+", line)
        if len(parts) < 2:
            continue
        key = parts[0]
        alleles = [part for part in parts[1:] if part and part != "-"]
        allelelist[key] = alleles
    return allelelist


def resolve_hla_pseudosequence(
    allele_or_cell_line: str,
    *,
    pseudosequence_aliases: dict[str, tuple[str, str]],
    allelelist: dict[str, list[str]],
) -> tuple[str | None, str | None, str]:
    direct = pseudosequence_aliases.get(allele_alias_key(allele_or_cell_line))
    if direct:
        allele, sequence = direct
        return allele, sequence, "direct"

    expressed = allelelist.get(allele_or_cell_line, [])
    resolved = [
        pseudosequence_aliases[allele_alias_key(allele)]
        for allele in expressed
        if allele_alias_key(allele) in pseudosequence_aliases
    ]
    unique_resolved = sorted(set(resolved))
    if len(unique_resolved) == 1:
        allele, sequence = unique_resolved[0]
        return allele, sequence, "cell_line_single"
    if len(unique_resolved) > 1:
        return None, None, "cell_line_ambiguous"
    return None, None, "unresolved"


def mhci_el_split(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("c000_"):
        return "test"
    if name.startswith("c001_"):
        return "valid"
    return "train"


def mhcii_el_split(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("test_el"):
        return "test"
    if name.startswith("train_el4"):
        return "valid"
    return "train"


def parse_hla_el_rows(
    text: str,
    *,
    mhc_class: str,
    split: str,
    source_file: str,
    pseudosequence_aliases: dict[str, tuple[str, str]],
    allelelist: dict[str, list[str]],
) -> tuple[list[dict], dict[str, int]]:
    rows: list[dict] = []
    stats = {
        "raw_rows": 0,
        "included": 0,
        "invalid_peptide": 0,
        "invalid_target": 0,
        "unresolved_hla": 0,
        "ambiguous_cell_line": 0,
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        stats["raw_rows"] += 1
        peptide = normalize_sequence(parts[0])
        if not is_valid_sequence(peptide):
            stats["invalid_peptide"] += 1
            continue
        try:
            target = float(parts[1])
        except ValueError:
            stats["invalid_target"] += 1
            continue

        allele, hla_sequence, status = resolve_hla_pseudosequence(
            parts[2],
            pseudosequence_aliases=pseudosequence_aliases,
            allelelist=allelelist,
        )
        if allele is None or hla_sequence is None:
            if status == "cell_line_ambiguous":
                stats["ambiguous_cell_line"] += 1
            else:
                stats["unresolved_hla"] += 1
            continue

        rows.append(
            {
                "mhc_class": mhc_class,
                "split": split,
                "source_file": source_file,
                "peptide": peptide,
                "peptide_hash": sequence_hash(peptide),
                "target": target,
                "target_binary": int(target >= 0.5),
                "source_hla": parts[2],
                "allele": allele,
                "hla_pseudosequence": hla_sequence,
                "hla_hash": sequence_hash(hla_sequence),
                "resolution": status,
            }
        )
        stats["included"] += 1

    return rows, stats


def empty_hla_el_stats() -> dict[str, int]:
    return {
        "raw_rows": 0,
        "included": 0,
        "invalid_peptide": 0,
        "invalid_target": 0,
        "unresolved_hla": 0,
        "ambiguous_cell_line": 0,
    }


def add_hla_el_stats(total: dict[str, int], update: dict[str, int]) -> None:
    for key, value in update.items():
        total[key] = total.get(key, 0) + int(value)


def iter_hla_el_row_batches(
    lines,
    *,
    mhc_class: str,
    split: str,
    source_file: str,
    pseudosequence_aliases: dict[str, tuple[str, str]],
    allelelist: dict[str, list[str]],
    batch_size: int = 50000,
):
    rows: list[dict] = []
    stats = empty_hla_el_stats()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        stats["raw_rows"] += 1
        peptide = normalize_sequence(parts[0])
        if not is_valid_sequence(peptide):
            stats["invalid_peptide"] += 1
            continue
        try:
            target = float(parts[1])
        except ValueError:
            stats["invalid_target"] += 1
            continue

        allele, hla_sequence, status = resolve_hla_pseudosequence(
            parts[2],
            pseudosequence_aliases=pseudosequence_aliases,
            allelelist=allelelist,
        )
        if allele is None or hla_sequence is None:
            if status == "cell_line_ambiguous":
                stats["ambiguous_cell_line"] += 1
            else:
                stats["unresolved_hla"] += 1
            continue

        rows.append(
            {
                "mhc_class": mhc_class,
                "split": split,
                "source_file": source_file,
                "peptide": peptide,
                "peptide_hash": sequence_hash(peptide),
                "target": target,
                "target_binary": int(target >= 0.5),
                "source_hla": parts[2],
                "allele": allele,
                "hla_pseudosequence": hla_sequence,
                "hla_hash": sequence_hash(hla_sequence),
                "resolution": status,
            }
        )
        stats["included"] += 1
        if len(rows) >= batch_size:
            yield rows, stats
            rows = []
            stats = empty_hla_el_stats()

    if rows or any(stats.values()):
        yield rows, stats
