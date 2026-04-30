from __future__ import annotations

import json
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

import modal

from training.constants import (
    ANUPP_DATASETS_URL,
    DATA_VOLUME_NAME,
    DEFAULT_ESM2_MODEL_ID,
    EMBEDDING_DIR,
    HF_HOME,
    MANIFEST_DIR,
    MODEL_VOLUME_NAME,
    NETMHCII_TARBALL_URL,
    NETMHCPAN_TARBALL_URL,
    NORMALIZED_DIR,
    RAW_DIR,
    SOLUBILITY_DATASET_ID,
    embedding_model_dir,
    esm2_local_dir,
)
from training.datasets import (
    add_hla_el_stats,
    build_pseudosequence_aliases,
    empty_hla_el_stats,
    extract_anupp_download_links,
    iter_hla_el_row_batches,
    mhci_el_split,
    mhcii_el_split,
    parse_allelelist_text,
    parse_fasta,
    parse_labeled_hex_fasta,
    parse_pseudosequence_text,
)
from training.embedding import embed_sequences
from training.io_utils import (
    compact_counts,
    ensure_dirs,
    is_valid_sequence,
    normalize_sequence,
    read_json,
    sequence_hash,
    sha256_path,
    write_json,
)

APP_NAME = "quality-scorers-esm2-embed"
HEAVY_GPU = "L40S"
TIMEOUT_SECONDS = 18 * 60 * 60
DOWNLOAD_LOG_BYTES = 64 * 1024 * 1024
DOWNLOAD_LOG_SECONDS = 30

data_volume = modal.Volume.from_name(DATA_VOLUME_NAME, create_if_missing=True)
model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-runtime-ubuntu24.04",
        add_python="3.11",
    )
    .apt_install("ca-certificates", "curl")
    .pip_install(
        "datasets==3.5.0",
        "huggingface_hub==0.34.4",
        "numpy==2.2.4",
        "pandas==2.2.3",
        "pyarrow==19.0.1",
        "requests==2.32.3",
        "safetensors==0.5.3",
        "torch==2.6.0",
        "transformers==4.51.3",
    )
    .env(
        {
            "HF_HOME": str(HF_HOME),
            "TRANSFORMERS_CACHE": str(HF_HOME / "transformers"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    .add_local_python_source("training")
)

app = modal.App(APP_NAME, image=image)


def _log(message: str) -> None:
    print(f"[quality-scorers] {message}", flush=True)


def _training_dirs() -> list[Path]:
    return [
        RAW_DIR,
        RAW_DIR / "anupp",
        RAW_DIR / "hla",
        NORMALIZED_DIR,
        EMBEDDING_DIR,
        MANIFEST_DIR,
        HF_HOME,
    ]


def _limit_by_split(df, limit: int):
    if limit <= 0 or "split" not in df.columns:
        return df
    import pandas as pd

    label_column = "label" if "label" in df.columns else "target_binary" if "target_binary" in df.columns else None
    if label_column:
        pieces = []
        for _split, group in df.groupby("split", sort=False):
            labels = list(group[label_column].dropna().unique())
            if len(labels) <= 1:
                pieces.append(group.head(limit))
                continue
            per_label = max(1, limit // len(labels))
            stratified = group.groupby(label_column, group_keys=False, sort=False).head(per_label)
            if stratified.shape[0] < limit:
                remainder = group.drop(index=stratified.index).head(limit - int(stratified.shape[0]))
                stratified = pd.concat([stratified, remainder], ignore_index=False)
            pieces.append(stratified.head(limit))
        return pd.concat(pieces, ignore_index=True) if pieces else df.iloc[0:0].copy()
    return df.groupby("split", group_keys=False).head(limit).reset_index(drop=True)


def _download_file(
    url: str,
    destination: Path,
    *,
    force: bool = False,
    min_bytes: int = 1,
) -> dict[str, Any]:
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        size = destination.stat().st_size
        if size < min_bytes:
            raise RuntimeError(
                f"Existing download is too small for {url}: {destination} has {size} bytes"
            )
        _log(f"using cached download {destination} ({size / (1024 ** 2):.1f} MiB)")
        return {
            "url": url,
            "path": str(destination),
            "bytes": size,
            "sha256": sha256_path(destination),
            "downloaded": False,
        }

    started_at = time.perf_counter()
    _log(f"downloading {url} -> {destination}")
    temp_path: Path | None = None
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        expected_bytes = int(response.headers.get("content-length") or 0)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(destination.parent)) as handle:
            temp_path = Path(handle.name)
            downloaded = 0
            next_log_bytes = DOWNLOAD_LOG_BYTES
            next_log_time = time.perf_counter() + DOWNLOAD_LOG_SECONDS
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
                    downloaded += len(chunk)
                    now = time.perf_counter()
                    if downloaded >= next_log_bytes or now >= next_log_time:
                        suffix = f" / {expected_bytes / (1024 ** 2):.1f} MiB" if expected_bytes else ""
                        _log(f"downloaded {downloaded / (1024 ** 2):.1f} MiB{suffix} from {url}")
                        next_log_bytes = downloaded + DOWNLOAD_LOG_BYTES
                        next_log_time = now + DOWNLOAD_LOG_SECONDS
    if temp_path is None:
        raise RuntimeError(f"Download did not create a temporary file for {url}")
    size = temp_path.stat().st_size
    if size < min_bytes:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded file is too small for {url}: {size} bytes")
    if expected_bytes and size != expected_bytes:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded byte count mismatch for {url}: expected {expected_bytes}, got {size}"
        )
    temp_path.replace(destination)
    _log(f"finished download {destination} ({size / (1024 ** 2):.1f} MiB) in {time.perf_counter() - started_at:.1f}s")
    return {
        "url": url,
        "path": str(destination),
        "bytes": size,
        "sha256": sha256_path(destination),
        "downloaded": True,
    }


def _safe_extract_tarball(tarball: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    _log(f"validating tarball {tarball}")
    with tarfile.open(tarball, "r:*") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError(f"Tarball is empty: {tarball}")
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe tar member type: {member.name}")
            member_path = (destination / member.name).resolve()
            if member_path != destination_root and destination_root not in member_path.parents:
                raise ValueError(f"Unsafe tar member path: {member.name}")
        _log(f"extracting {len(members)} tar members from {tarball} -> {destination}")
        for member in members:
            archive.extract(member, destination)
    _log(f"finished extracting {tarball}")


def _ensure_esm2_snapshot(model_id: str, *, force: bool = False) -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    target_dir = esm2_local_dir(model_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    expected = [
        target_dir / "config.json",
        target_dir / "model.safetensors",
        target_dir / "special_tokens_map.json",
        target_dir / "tokenizer_config.json",
        target_dir / "vocab.txt",
    ]
    if all(path.exists() for path in expected) and not force:
        return {
            "model_id": model_id,
            "path": str(target_dir),
            "downloaded": False,
            "files": [str(path.relative_to(target_dir)) for path in expected],
        }

    snapshot_download(
        repo_id=model_id,
        local_dir=str(target_dir),
        allow_patterns=[
            "config.json",
            "model.safetensors",
            "special_tokens_map.json",
            "tokenizer_config.json",
            "vocab.txt",
        ],
    )
    return {
        "model_id": model_id,
        "path": str(target_dir),
        "downloaded": True,
        "files": [
            str(path.relative_to(target_dir))
            for path in sorted(target_dir.iterdir())
            if path.is_file()
        ],
    }


def _load_esm2(model_id: str, device: str):
    from transformers import AutoModel, AutoTokenizer

    local_dir = esm2_local_dir(model_id)
    source = str(local_dir) if local_dir.exists() else model_id
    tokenizer = AutoTokenizer.from_pretrained(source)
    model = AutoModel.from_pretrained(source, use_safetensors=True).to(device)
    model.eval()
    return tokenizer, model


def _ingest_solubility_impl(*, dataset_id: str, limit: int) -> dict[str, Any]:
    import pandas as pd
    from datasets import load_dataset

    started_at = time.perf_counter()
    _log("starting solubility ingest")
    ds = load_dataset(dataset_id, cache_dir=str(RAW_DIR / "hf_datasets"))
    frames = []
    if hasattr(ds, "items"):
        for split_name, split_ds in ds.items():
            frame = split_ds.to_pandas()
            if "stage" not in frame.columns:
                frame["stage"] = split_name
            frames.append(frame)
    else:
        frames.append(ds.to_pandas())
    raw = pd.concat(frames, ignore_index=True)

    required = {"protein", "label", "stage"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Solubility dataset is missing required columns: {sorted(missing)}")

    normalized = raw[["protein", "label", "stage"]].rename(
        columns={"protein": "sequence", "stage": "split"}
    )
    normalized["sequence"] = normalized["sequence"].map(normalize_sequence)
    normalized["label"] = normalized["label"].astype(int)
    normalized["split"] = normalized["split"].astype(str).str.lower().replace({"validation": "valid"})
    normalized["sequence_hash"] = normalized["sequence"].map(sequence_hash)
    normalized["length"] = normalized["sequence"].str.len()
    normalized["is_valid"] = normalized["sequence"].map(is_valid_sequence)

    raw_rows = int(normalized.shape[0])
    invalid_rows = int((~normalized["is_valid"]).sum())
    normalized = normalized[normalized["is_valid"]].copy()

    label_nunique = normalized.groupby("sequence")["label"].nunique()
    conflicting = set(label_nunique[label_nunique > 1].index)
    conflicting_rows = int(normalized["sequence"].isin(conflicting).sum())
    normalized = normalized[~normalized["sequence"].isin(conflicting)].copy()

    split_rank = {"test": 0, "valid": 1, "train": 2}
    normalized["split_rank"] = normalized["split"].map(split_rank).fillna(3).astype(int)
    before_dedup = int(normalized.shape[0])
    normalized = (
        normalized.sort_values(["split_rank", "sequence_hash"])
        .drop_duplicates("sequence", keep="first")
        .drop(columns=["split_rank", "is_valid"])
        .reset_index(drop=True)
    )
    deduped_rows = int(normalized.shape[0])
    normalized = _limit_by_split(normalized, limit)
    normalized["row_idx"] = range(int(normalized.shape[0]))

    output_path = NORMALIZED_DIR / "solubility.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(output_path, index=False)

    manifest = {
        "dataset": "solubility",
        "source": dataset_id,
        "split_policy": "Use the source stage column; validation is normalized to valid.",
        "dedup_policy": "Drop invalid sequences and conflicting-label duplicates; preserve test then valid then train on exact duplicate sequences.",
        "raw_rows": raw_rows,
        "invalid_rows_dropped": invalid_rows,
        "conflicting_label_rows_dropped": conflicting_rows,
        "duplicate_rows_dropped": before_dedup - deduped_rows,
        "limit_per_split": limit if limit > 0 else None,
        "rows": int(normalized.shape[0]),
        "split_counts": compact_counts(normalized["split"].tolist()),
        "label_counts": {str(key): int(value) for key, value in normalized["label"].value_counts().sort_index().items()},
        "path": str(output_path),
        "elapsed_seconds": time.perf_counter() - started_at,
    }
    write_json(MANIFEST_DIR / "solubility_ingest.json", manifest)
    _log(f"finished solubility ingest: {manifest['rows']} rows")
    return manifest


def _download_anupp_sources(*, force: bool) -> dict[str, Any]:
    import requests

    response = requests.get(ANUPP_DATASETS_URL, timeout=60)
    response.raise_for_status()
    links = extract_anupp_download_links(response.text, ANUPP_DATASETS_URL)
    expected = {"hex1279", "hex142", "amy17", "amy37"}
    missing = expected - set(links)
    if missing:
        raise RuntimeError(
            f"Could not discover ANuPP download links for {sorted(missing)} from {ANUPP_DATASETS_URL}"
        )

    results = {}
    for name, url in links.items():
        results[name] = _download_file(
            url,
            RAW_DIR / "anupp" / f"{name}.fasta",
            force=force,
            min_bytes=100,
        )
    return {"source_page": ANUPP_DATASETS_URL, "links": links, "downloads": results}


def _ingest_apr_impl(*, limit: int, force_download: bool) -> dict[str, Any]:
    import pandas as pd

    started_at = time.perf_counter()
    _log("starting APR ingest")
    download_manifest = _download_anupp_sources(force=force_download)
    manual_path = RAW_DIR / "anupp" / "manual_label_map.json"
    manual_map = read_json(manual_path) if manual_path.exists() else {}

    all_hex_rows: list[dict] = []
    unresolved_by_dataset: dict[str, list[str]] = {}
    for name, split in (("hex1279", "train"), ("hex142", "test")):
        text = (RAW_DIR / "anupp" / f"{name}.fasta").read_text(errors="replace")
        rows, unresolved = parse_labeled_hex_fasta(
            text,
            dataset=name,
            manual_labels=manual_map.get(name, manual_map),
        )
        if unresolved:
            unresolved_by_dataset[name] = unresolved[:50]
        for row in rows:
            row["split"] = split
        all_hex_rows.extend(rows)

    if unresolved_by_dataset:
        needs_manual = {
            "error": "Could not infer binary APR labels for every ANuPP hexapeptide FASTA header.",
            "manual_label_map_path": str(manual_path),
            "format": {
                "hex1279": {"exact FASTA header or peptide sequence": 0},
                "hex142": {"exact FASTA header or peptide sequence": 1},
            },
            "sample_unresolved_headers": unresolved_by_dataset,
        }
        write_json(RAW_DIR / "anupp" / "needs_manual_label_map.json", needs_manual)
        raise ValueError(
            "ANuPP labels were not fully recoverable from FASTA headers. "
            f"Write labels to {manual_path} and rerun."
        )

    hex_df = pd.DataFrame(all_hex_rows)
    raw_hex_rows = int(hex_df.shape[0])
    hex_df = hex_df[(hex_df["is_valid"]) & (hex_df["length"] == 6)].copy()
    split_rank = {"test": 0, "train": 1}
    before_dedup = int(hex_df.shape[0])
    hex_df["split_rank"] = hex_df["split"].map(split_rank).fillna(2).astype(int)
    hex_df = (
        hex_df.sort_values(["split_rank", "sequence_hash"])
        .drop_duplicates("sequence", keep="first")
        .drop(columns=["split_rank", "is_valid"])
        .reset_index(drop=True)
    )
    deduped_rows = int(hex_df.shape[0])
    hex_df = _limit_by_split(hex_df, limit)
    hex_df["row_idx"] = range(int(hex_df.shape[0]))

    apr_path = NORMALIZED_DIR / "apr_hex.parquet"
    hex_df.to_parquet(apr_path, index=False)

    sanity_rows: list[dict[str, Any]] = []
    for name in ("amy17", "amy37"):
        text = (RAW_DIR / "anupp" / f"{name}.fasta").read_text(errors="replace")
        for record in parse_fasta(text):
            sanity_rows.append(
                {
                    "dataset": name,
                    "header": record.header,
                    "sequence": record.sequence,
                    "sequence_hash": sequence_hash(record.sequence),
                    "length": len(record.sequence),
                    "is_valid": is_valid_sequence(record.sequence),
                }
            )
    sanity_df = pd.DataFrame(sanity_rows)
    sanity_path = NORMALIZED_DIR / "apr_protein_sanity.parquet"
    sanity_df.to_parquet(sanity_path, index=False)

    manifest = {
        "dataset": "apr",
        "source": ANUPP_DATASETS_URL,
        "split_policy": "Hex1279=train, Hex142=test; Amy17/Amy37 are stored only for protein-level sanity checks.",
        "dedup_policy": "Drop invalid/non-6-mer peptides; preserve Hex142 over Hex1279 on exact duplicate peptides.",
        "downloads": download_manifest,
        "raw_hex_rows": raw_hex_rows,
        "invalid_or_non_hex_rows_dropped": raw_hex_rows - before_dedup,
        "duplicate_rows_dropped": before_dedup - deduped_rows,
        "limit_per_split": limit if limit > 0 else None,
        "rows": int(hex_df.shape[0]),
        "split_counts": compact_counts(hex_df["split"].tolist()),
        "label_counts": {str(key): int(value) for key, value in hex_df["label"].value_counts().sort_index().items()},
        "hex_path": str(apr_path),
        "sanity_path": str(sanity_path),
        "elapsed_seconds": time.perf_counter() - started_at,
    }
    write_json(MANIFEST_DIR / "apr_ingest.json", manifest)
    _log(f"finished APR ingest: {manifest['rows']} hex rows")
    return manifest


def _find_first(root: Path, filenames: set[str]) -> Path:
    lower_names = {name.lower() for name in filenames}
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() in lower_names:
            return path
    raise FileNotFoundError(f"Could not find any of {sorted(filenames)} under {root}")


def _has_any_file(path: Path) -> bool:
    return path.exists() and any(child.is_file() for child in path.rglob("*"))


def _iter_hla_el_files(root: Path, *, hla_raw: Path, mhc_class: str):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if mhc_class == "MHC-I":
            if lower.startswith("c00") and lower.endswith("_el"):
                yield path, mhci_el_split(path), str(path.relative_to(hla_raw))
        elif lower.startswith("train_el") or lower.startswith("test_el"):
            yield path, mhcii_el_split(path), str(path.relative_to(hla_raw))


def _write_hla_el_batches(
    *,
    jobs,
    output_path: Path,
    limit: int,
) -> tuple[dict[str, dict[str, int]], dict[str, int], int]:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    writer = None
    file_stats: dict[str, dict[str, int]] = {}
    aggregate_stats = empty_hla_el_stats()
    written_rows = 0
    kept_by_split: dict[str, int] = {}

    try:
        for path, split, source_file, mhc_class, pseudosequence_aliases, allelelist in jobs:
            if limit > 0 and kept_by_split.get(split, 0) >= limit:
                file_stats[source_file] = empty_hla_el_stats()
                _log(f"skipping {source_file}: limit already reached for split={split}")
                continue
            _log(f"parsing HLA EL file {source_file}")
            stats_for_file = empty_hla_el_stats()
            with path.open("rt", errors="replace") as handle:
                for rows, stats in iter_hla_el_row_batches(
                    handle,
                    mhc_class=mhc_class,
                    split=split,
                    source_file=source_file,
                    pseudosequence_aliases=pseudosequence_aliases,
                    allelelist=allelelist,
                ):
                    add_hla_el_stats(stats_for_file, stats)
                    add_hla_el_stats(aggregate_stats, stats)
                    if not rows:
                        continue
                    frame = pd.DataFrame(rows)
                    if limit > 0:
                        already_kept = kept_by_split.get(split, 0)
                        remaining = limit - already_kept
                        if remaining <= 0:
                            break
                        frame = frame.head(remaining)
                        kept_by_split[split] = already_kept + int(frame.shape[0])
                    if frame.empty:
                        continue
                    frame["row_idx"] = range(written_rows, written_rows + int(frame.shape[0]))
                    table = pa.Table.from_pandas(frame, preserve_index=False)
                    if writer is None:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        writer = pq.ParquetWriter(output_path, table.schema)
                    writer.write_table(table)
                    written_rows += int(frame.shape[0])
                    if written_rows and written_rows % 250000 == 0:
                        _log(f"wrote {written_rows} HLA EL rows so far")
            file_stats[source_file] = stats_for_file
            _log(
                f"finished {source_file}: included={stats_for_file['included']} raw={stats_for_file['raw_rows']}"
            )
    finally:
        if writer is not None:
            writer.close()

    return file_stats, aggregate_stats, written_rows


def _ingest_hla_el_impl(*, limit: int, force_download: bool) -> dict[str, Any]:
    import pandas as pd

    started_at = time.perf_counter()
    _log("starting HLA EL ingest")
    hla_raw = RAW_DIR / "hla"
    mhci_tar = hla_raw / "NetMHCpan_train.tar.gz"
    mhcii_tar = hla_raw / "NetMHCIIpan_train.tar.gz"
    downloads = {
        "mhci": _download_file(NETMHCPAN_TARBALL_URL, mhci_tar, force=force_download, min_bytes=1024 * 1024),
        "mhcii": _download_file(NETMHCII_TARBALL_URL, mhcii_tar, force=force_download, min_bytes=1024 * 1024),
    }

    mhci_extract = hla_raw / "mhci"
    mhcii_extract = hla_raw / "mhcii"
    if force_download or not _has_any_file(mhci_extract):
        _safe_extract_tarball(mhci_tar, mhci_extract)
    if force_download or not _has_any_file(mhcii_extract):
        _safe_extract_tarball(mhcii_tar, mhcii_extract)

    mhci_pseudo_path = _find_first(mhci_extract, {"MHC_pseudo.dat"})
    mhcii_pseudo_path = _find_first(mhcii_extract, {"pseudosequence.2016.all.x.dat"})
    mhci_allelelist_path = _find_first(mhci_extract, {"allelelist", "allelelist.txt"})
    mhcii_allelelist_path = _find_first(mhcii_extract, {"allelelist", "allelelist.txt"})
    _log(
        "found HLA support files: "
        f"{mhci_pseudo_path.name}, {mhcii_pseudo_path.name}, "
        f"{mhci_allelelist_path.name}, {mhcii_allelelist_path.name}"
    )

    mhci_pseudo = parse_pseudosequence_text(mhci_pseudo_path.read_text(errors="replace"))
    mhcii_pseudo = parse_pseudosequence_text(
        mhcii_pseudo_path.read_text(errors="replace")
    )
    if not mhci_pseudo:
        raise ValueError(f"No MHC-I pseudo-sequences parsed from {mhci_pseudo_path}")
    if not mhcii_pseudo:
        raise ValueError(f"No MHC-II pseudo-sequences parsed from {mhcii_pseudo_path}")
    mhci_aliases = build_pseudosequence_aliases(mhci_pseudo)
    mhcii_aliases = build_pseudosequence_aliases(mhcii_pseudo)
    mhci_allelelist = parse_allelelist_text(mhci_allelelist_path.read_text(errors="replace"))
    mhcii_allelelist = parse_allelelist_text(mhcii_allelelist_path.read_text(errors="replace"))

    mhci_files = list(_iter_hla_el_files(mhci_extract, hla_raw=hla_raw, mhc_class="MHC-I"))
    mhcii_files = list(_iter_hla_el_files(mhcii_extract, hla_raw=hla_raw, mhc_class="MHC-II"))
    if not mhci_files:
        raise FileNotFoundError(f"No MHC-I EL partition files found under {mhci_extract}")
    if not mhcii_files:
        raise FileNotFoundError(f"No MHC-II EL partition files found under {mhcii_extract}")

    output_path = NORMALIZED_DIR / "hla_el_pairs.parquet"
    output_path.unlink(missing_ok=True)
    jobs = [
        (*job, "MHC-I", mhci_aliases, mhci_allelelist)
        for job in mhci_files
    ] + [
        (*job, "MHC-II", mhcii_aliases, mhcii_allelelist)
        for job in mhcii_files
    ]
    file_stats, aggregate_stats, written_rows = _write_hla_el_batches(
        jobs=jobs,
        output_path=output_path,
        limit=limit,
    )
    if written_rows <= 0:
        raise ValueError("No HLA EL rows were parsed from the DTU training tarballs")

    pairs_for_counts = pd.read_parquet(
        output_path,
        columns=["split", "mhc_class", "resolution"],
    )

    manifest = {
        "dataset": "hla_el",
        "sources": {
            "mhci": NETMHCPAN_TARBALL_URL,
            "mhcii": NETMHCII_TARBALL_URL,
        },
        "split_policy": "MHC-I c000_el=test, c001_el=valid, c002-c004_el=train; MHC-II test_EL*=test, train_EL4=valid, other train_EL*=train.",
        "resolution_policy": "Use direct pseudo-sequence matches and single-allele cell-line mappings; skip unresolved or multi-allelic cell-line rows.",
        "downloads": downloads,
        "limit_per_split": limit if limit > 0 else None,
        "rows": int(pairs_for_counts.shape[0]),
        "split_counts": compact_counts(pairs_for_counts["split"].tolist()),
        "mhc_class_counts": compact_counts(pairs_for_counts["mhc_class"].tolist()),
        "resolution_counts": compact_counts(pairs_for_counts["resolution"].tolist()),
        "aggregate_parse_stats": aggregate_stats,
        "file_stats": file_stats,
        "path": str(output_path),
        "elapsed_seconds": time.perf_counter() - started_at,
    }
    write_json(MANIFEST_DIR / "hla_el_ingest.json", manifest)
    _log(f"finished HLA EL ingest: {manifest['rows']} rows")
    return manifest


def _embed_table_impl(
    *,
    model_id: str,
    dataset_name: str,
    table_path: Path,
    sequence_column: str,
    output_table_name: str,
    output_matrix_name: str,
    batch_size: int,
    limit: int,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import torch

    started_at = time.perf_counter()
    frame = pd.read_parquet(table_path)
    if limit > 0:
        frame = _limit_by_split(frame, limit).copy()
    frame["embedding_idx"] = range(int(frame.shape[0]))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer, model = _load_esm2(model_id, device)
    embeddings = embed_sequences(
        frame[sequence_column].tolist(),
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=batch_size,
    )

    output_dir = embedding_model_dir(model_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_table = output_dir / output_table_name
    output_matrix = output_dir / output_matrix_name
    frame.to_parquet(output_table, index=False)
    np.save(output_matrix, embeddings)

    manifest = {
        "dataset": dataset_name,
        "model_id": model_id,
        "table_path": str(output_table),
        "matrix_path": str(output_matrix),
        "rows": int(frame.shape[0]),
        "embedding_shape": list(embeddings.shape),
        "device": device,
        "elapsed_seconds": time.perf_counter() - started_at,
    }
    write_json(MANIFEST_DIR / f"{dataset_name}_embeddings.json", manifest)
    return manifest


def _embed_hla_impl(*, model_id: str, batch_size: int, limit: int) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import torch

    started_at = time.perf_counter()
    pairs = pd.read_parquet(NORMALIZED_DIR / "hla_el_pairs.parquet")
    if limit > 0:
        pairs = _limit_by_split(pairs, limit).copy()

    peptides = (
        pairs[["peptide", "peptide_hash"]]
        .drop_duplicates("peptide_hash")
        .sort_values("peptide_hash")
        .reset_index(drop=True)
    )
    peptides["peptide_idx"] = range(int(peptides.shape[0]))
    hlas = (
        pairs[["hla_pseudosequence", "hla_hash", "allele"]]
        .drop_duplicates("hla_hash")
        .sort_values("hla_hash")
        .reset_index(drop=True)
    )
    hlas["hla_idx"] = range(int(hlas.shape[0]))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer, model = _load_esm2(model_id, device)
    peptide_embeddings = embed_sequences(
        peptides["peptide"].tolist(),
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=batch_size,
    )
    hla_embeddings = embed_sequences(
        hlas["hla_pseudosequence"].tolist(),
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=batch_size,
    )

    output_dir = embedding_model_dir(model_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    peptide_table = output_dir / "hla_peptides.parquet"
    peptide_matrix = output_dir / "hla_peptides.npy"
    hla_table = output_dir / "hla_pseudosequences.parquet"
    hla_matrix = output_dir / "hla_pseudosequences.npy"
    pair_table = output_dir / "hla_el_pairs.parquet"

    pairs = pairs.merge(peptides[["peptide_hash", "peptide_idx"]], on="peptide_hash", how="left")
    pairs = pairs.merge(hlas[["hla_hash", "hla_idx"]], on="hla_hash", how="left")
    pairs.to_parquet(pair_table, index=False)
    peptides.to_parquet(peptide_table, index=False)
    hlas.to_parquet(hla_table, index=False)
    np.save(peptide_matrix, peptide_embeddings)
    np.save(hla_matrix, hla_embeddings)

    manifest = {
        "dataset": "hla_el",
        "model_id": model_id,
        "pair_table_path": str(pair_table),
        "peptide_table_path": str(peptide_table),
        "peptide_matrix_path": str(peptide_matrix),
        "hla_table_path": str(hla_table),
        "hla_matrix_path": str(hla_matrix),
        "pair_rows": int(pairs.shape[0]),
        "unique_peptides": int(peptides.shape[0]),
        "unique_hla_pseudosequences": int(hlas.shape[0]),
        "peptide_embedding_shape": list(peptide_embeddings.shape),
        "hla_embedding_shape": list(hla_embeddings.shape),
        "device": device,
        "elapsed_seconds": time.perf_counter() - started_at,
    }
    write_json(MANIFEST_DIR / "hla_el_embeddings.json", manifest)
    return manifest


@app.function(
    volumes={"/models": model_volume},
    timeout=60 * 60,
)
def download_esm2(model_id: str = DEFAULT_ESM2_MODEL_ID, force: bool = False) -> dict[str, Any]:
    model_volume.reload()
    ensure_dirs([esm2_local_dir(model_id), HF_HOME])
    result = _ensure_esm2_snapshot(model_id, force=force)
    model_volume.commit()
    return result


@app.function(
    volumes={"/data": data_volume},
    timeout=2 * 60 * 60,
)
def ingest_solubility(
    dataset_id: str = SOLUBILITY_DATASET_ID,
    limit: int = 0,
) -> dict[str, Any]:
    data_volume.reload()
    ensure_dirs(_training_dirs())
    try:
        result = _ingest_solubility_impl(dataset_id=dataset_id, limit=limit)
    finally:
        data_volume.commit()
    return result


@app.function(
    volumes={"/data": data_volume},
    timeout=60 * 60,
)
def ingest_apr(limit: int = 0, force_download: bool = False) -> dict[str, Any]:
    data_volume.reload()
    ensure_dirs(_training_dirs())
    try:
        result = _ingest_apr_impl(limit=limit, force_download=force_download)
    finally:
        data_volume.commit()
    return result


@app.function(
    volumes={"/data": data_volume},
    timeout=3 * 60 * 60,
)
def ingest_hla_el(limit: int = 0, force_download: bool = False) -> dict[str, Any]:
    data_volume.reload()
    ensure_dirs(_training_dirs())
    try:
        result = _ingest_hla_el_impl(limit=limit, force_download=force_download)
    finally:
        data_volume.commit()
    return result


@app.function(
    volumes={"/data": data_volume},
    timeout=4 * 60 * 60,
)
def ingest_all(limit: int = 0, force_download: bool = False) -> dict[str, Any]:
    data_volume.reload()
    ensure_dirs(_training_dirs())
    try:
        _log("ingest_all step 1/3: solubility")
        solubility = _ingest_solubility_impl(dataset_id=SOLUBILITY_DATASET_ID, limit=limit)
        _log("ingest_all step 2/3: APR")
        apr = _ingest_apr_impl(limit=limit, force_download=force_download)
        _log("ingest_all step 3/3: HLA EL")
        hla_el = _ingest_hla_el_impl(limit=limit, force_download=force_download)
        results = {
            "solubility": solubility,
            "apr": apr,
            "hla_el": hla_el,
        }
    finally:
        data_volume.commit()
    return results


@app.function(
    gpu=HEAVY_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def embed_solubility(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    batch_size: int = 64,
    limit: int = 0,
    force_model_download: bool = False,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs(_training_dirs())
    _ensure_esm2_snapshot(model_id, force=force_model_download)
    if not (NORMALIZED_DIR / "solubility.parquet").exists():
        _ingest_solubility_impl(dataset_id=SOLUBILITY_DATASET_ID, limit=0)
    result = _embed_table_impl(
        model_id=model_id,
        dataset_name="solubility",
        table_path=NORMALIZED_DIR / "solubility.parquet",
        sequence_column="sequence",
        output_table_name="solubility.parquet",
        output_matrix_name="solubility.npy",
        batch_size=batch_size,
        limit=limit,
    )
    data_volume.commit()
    model_volume.commit()
    return result


@app.function(
    gpu=HEAVY_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def embed_apr(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    batch_size: int = 256,
    limit: int = 0,
    force_model_download: bool = False,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs(_training_dirs())
    _ensure_esm2_snapshot(model_id, force=force_model_download)
    if not (NORMALIZED_DIR / "apr_hex.parquet").exists():
        _ingest_apr_impl(limit=0, force_download=False)
    result = _embed_table_impl(
        model_id=model_id,
        dataset_name="apr",
        table_path=NORMALIZED_DIR / "apr_hex.parquet",
        sequence_column="sequence",
        output_table_name="apr_hex.parquet",
        output_matrix_name="apr_hex.npy",
        batch_size=batch_size,
        limit=limit,
    )
    data_volume.commit()
    model_volume.commit()
    return result


@app.function(
    gpu=HEAVY_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def embed_hla_el(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    batch_size: int = 256,
    limit: int = 0,
    force_model_download: bool = False,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs(_training_dirs())
    _ensure_esm2_snapshot(model_id, force=force_model_download)
    if not (NORMALIZED_DIR / "hla_el_pairs.parquet").exists():
        _ingest_hla_el_impl(limit=0, force_download=False)
    result = _embed_hla_impl(model_id=model_id, batch_size=batch_size, limit=limit)
    data_volume.commit()
    model_volume.commit()
    return result


@app.function(
    gpu=HEAVY_GPU,
    volumes={"/data": data_volume, "/models": model_volume},
    timeout=TIMEOUT_SECONDS,
)
def embed_all(
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    batch_size: int = 64,
    hla_batch_size: int = 256,
    limit: int = 0,
    force_model_download: bool = False,
) -> dict[str, Any]:
    data_volume.reload()
    model_volume.reload()
    ensure_dirs(_training_dirs())
    _ensure_esm2_snapshot(model_id, force=force_model_download)
    if not (NORMALIZED_DIR / "solubility.parquet").exists():
        _ingest_solubility_impl(dataset_id=SOLUBILITY_DATASET_ID, limit=0)
    if not (NORMALIZED_DIR / "apr_hex.parquet").exists():
        _ingest_apr_impl(limit=0, force_download=False)
    if not (NORMALIZED_DIR / "hla_el_pairs.parquet").exists():
        _ingest_hla_el_impl(limit=0, force_download=False)

    results = {
        "solubility": _embed_table_impl(
            model_id=model_id,
            dataset_name="solubility",
            table_path=NORMALIZED_DIR / "solubility.parquet",
            sequence_column="sequence",
            output_table_name="solubility.parquet",
            output_matrix_name="solubility.npy",
            batch_size=batch_size,
            limit=limit,
        ),
        "apr": _embed_table_impl(
            model_id=model_id,
            dataset_name="apr",
            table_path=NORMALIZED_DIR / "apr_hex.parquet",
            sequence_column="sequence",
            output_table_name="apr_hex.parquet",
            output_matrix_name="apr_hex.npy",
            batch_size=max(batch_size, 256),
            limit=limit,
        ),
        "hla_el": _embed_hla_impl(model_id=model_id, batch_size=hla_batch_size, limit=limit),
    }
    data_volume.commit()
    model_volume.commit()
    return results


@app.local_entrypoint()
def main(
    action: str = "embed-all",
    model_id: str = DEFAULT_ESM2_MODEL_ID,
    batch_size: int = 64,
    hla_batch_size: int = 256,
    limit: int = 0,
    force: bool = False,
) -> None:
    if action == "download-esm2":
        result = download_esm2.remote(model_id=model_id, force=force)
    elif action == "ingest-solubility":
        result = ingest_solubility.remote(limit=limit)
    elif action == "ingest-apr":
        result = ingest_apr.remote(limit=limit, force_download=force)
    elif action == "ingest-hla-el":
        result = ingest_hla_el.remote(limit=limit, force_download=force)
    elif action == "ingest-all":
        result = ingest_all.remote(limit=limit, force_download=force)
    elif action == "embed-solubility":
        result = embed_solubility.remote(
            model_id=model_id,
            batch_size=batch_size,
            limit=limit,
            force_model_download=force,
        )
    elif action == "embed-apr":
        result = embed_apr.remote(
            model_id=model_id,
            batch_size=max(batch_size, 256),
            limit=limit,
            force_model_download=force,
        )
    elif action == "embed-hla-el":
        result = embed_hla_el.remote(
            model_id=model_id,
            batch_size=hla_batch_size,
            limit=limit,
            force_model_download=force,
        )
    elif action == "embed-all":
        result = embed_all.remote(
            model_id=model_id,
            batch_size=batch_size,
            hla_batch_size=hla_batch_size,
            limit=limit,
            force_model_download=force,
        )
    else:
        raise ValueError(f"Unknown action: {action}")
    print(json.dumps(result, indent=2))
