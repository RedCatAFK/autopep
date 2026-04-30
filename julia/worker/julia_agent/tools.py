from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shlex
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download"
NCBI_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

DEFAULT_HTTP_TIMEOUT_SECONDS = 900
DEFAULT_TOOL_TIMEOUT_SECONDS = 120
MAX_RESULTS_LIMIT = 25
MAX_TOOL_OUTPUT_CHARS = 6000

DEFAULT_MODAL_URLS = {
    "MODAL_CHAI_URL": "https://autopep--chai-1-inference-fastapi-app.modal.run",
    "MODAL_PROTEINA_URL": "https://autopep--proteina-complexa-fastapi-app.modal.run",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL": (
        "https://autopep--protein-interaction-scoring-proteinscoringservice-api.modal.run"
    ),
    "MODAL_QUALITY_SCORERS_URL": (
        "https://autopep--quality-scorers-inference-fastapi-app.modal.run"
    ),
}

OUTPUT_DIRS = (
    "literature",
    "pdb",
    "proteina_runs",
    "chai_runs",
    "scoring_runs",
    "tool_logs",
)

THREE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def output_roots(workspace_dir: Path | str) -> list[Path]:
    return [safe_workspace_path(workspace_dir, "outputs")]


def ensure_workspace_layout(workspace_dir: Path | str) -> None:
    safe_workspace_path(workspace_dir, "inputs").mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_DIRS:
        tool_path(workspace_dir, name, "").mkdir(parents=True, exist_ok=True)


def safe_slug(value: str, default: str = "run") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())[:80].strip("._-")
    return cleaned or default


def safe_workspace_path(
    workspace_dir: Path | str,
    path: str | Path | None,
    *,
    default_name: str | None = None,
) -> Path:
    workspace = Path(workspace_dir).expanduser().resolve(strict=False)
    if path is None or not str(path).strip():
        if default_name is None:
            raise ValueError("A workspace path is required.")
        path = default_name
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != workspace and workspace not in resolved.parents:
        raise ValueError(f"Path must stay inside workspace: {path}")
    return resolved


def tool_path(workspace_dir: Path | str, output_dir: str, name: str | Path) -> Path:
    if output_dir not in OUTPUT_DIRS:
        raise ValueError(f"Unknown output directory: {output_dir}")
    root = safe_workspace_path(workspace_dir, Path("outputs") / output_dir)
    candidate = root / Path(name)
    resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Path must stay inside outputs/{output_dir}: {name}")
    return resolved


def relative_to_workspace(path: Path | str, workspace_dir: Path | str) -> str:
    return str(Path(path).resolve(strict=False).relative_to(Path(workspace_dir).resolve(strict=False)))


def trim_text(text: str, limit: int | None = None) -> str:
    max_chars = limit or int(os.getenv("JULIA_TOOL_OUTPUT_CHARS", str(MAX_TOOL_OUTPUT_CHARS)))
    if len(text) <= max_chars:
        return text
    hidden = len(text) - max_chars
    return f"{text[:max_chars]}\n... <truncated {hidden} chars>"


def jsonable(value: Any, *, string_limit: int = 1200) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(secret in key_text.lower() for secret in ("key", "token", "secret", "password")):
                output[key_text] = "<redacted>" if item else ""
            else:
                output[key_text] = jsonable(item, string_limit=string_limit)
        return output
    if isinstance(value, list | tuple):
        return [jsonable(item, string_limit=string_limit) for item in value[:20]]
    if isinstance(value, str):
        return trim_text(value, string_limit)
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)


async def execute_bash(
    workspace_dir: Path | str,
    command: str,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    ensure_workspace_layout(workspace_dir)
    timeout = _clamp_timeout(timeout_seconds)
    run_id = f"bash_{_utc_slug()}_{uuid.uuid4().hex[:8]}"
    start = time.monotonic()
    workspace = safe_workspace_path(workspace_dir, ".")
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=workspace,
        executable="/bin/bash",
        env={**os.environ, "JULIA_WORKSPACE_DIR": str(workspace)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    stdout_path = tool_path(workspace, "tool_logs", f"{run_id}.stdout.txt")
    stderr_path = tool_path(workspace, "tool_logs", f"{run_id}.stderr.txt")
    _write_text(stdout_path, stdout)
    _write_text(stderr_path, stderr)
    return {
        "command": command,
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "stdout": trim_text(stdout),
        "stderr": trim_text(stderr),
        "stdout_path": relative_to_workspace(stdout_path, workspace),
        "stderr_path": relative_to_workspace(stderr_path, workspace),
    }


async def execute_python(
    workspace_dir: Path | str,
    script: str,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
    filename: str | None = None,
) -> dict[str, Any]:
    ensure_workspace_layout(workspace_dir)
    workspace = safe_workspace_path(workspace_dir, ".")
    timeout = _clamp_timeout(timeout_seconds)
    script_name = safe_slug(filename or f"script_{_utc_slug()}_{uuid.uuid4().hex[:8]}", "script")
    if not script_name.endswith(".py"):
        script_name += ".py"
    script_path = tool_path(workspace, "tool_logs", Path("python_runs") / script_name)
    _write_text(script_path, script)
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        cwd=workspace,
        env={**os.environ, "JULIA_WORKSPACE_DIR": str(workspace)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    stdout_path = tool_path(workspace, "tool_logs", f"{script_path.stem}.stdout.txt")
    stderr_path = tool_path(workspace, "tool_logs", f"{script_path.stem}.stderr.txt")
    _write_text(stdout_path, stdout)
    _write_text(stderr_path, stderr)
    return {
        "script_path": relative_to_workspace(script_path, workspace),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "stdout": trim_text(stdout),
        "stderr": trim_text(stderr),
        "stdout_path": relative_to_workspace(stdout_path, workspace),
        "stderr_path": relative_to_workspace(stderr_path, workspace),
    }


async def literature_search(
    workspace_dir: Path | str,
    query: str,
    max_results: int = 8,
) -> dict[str, Any]:
    limit = _clamp_count(max_results, default=8)
    params: dict[str, Any] = {"db": "pmc", "retmode": "json", "retmax": limit, "term": query}
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    if os.getenv("NCBI_TOOL_EMAIL"):
        params["email"] = os.environ["NCBI_TOOL_EMAIL"]
        params["tool"] = "julia-worker"

    search_payload = await _get_json(NCBI_SEARCH_URL, params=params)
    ids = [
        item
        for item in search_payload.get("esearchresult", {}).get("idlist", [])
        if isinstance(item, str)
    ]
    records: list[dict[str, Any]] = []
    if ids:
        summary_params = {"db": "pmc", "retmode": "json", "id": ",".join(ids)}
        if os.getenv("NCBI_API_KEY"):
            summary_params["api_key"] = os.environ["NCBI_API_KEY"]
        summary_payload = await _get_json(NCBI_SUMMARY_URL, params=summary_params)
        result_block = summary_payload.get("result", {})
        for uid in result_block.get("uids", ids):
            record = result_block.get(uid)
            if not isinstance(record, Mapping):
                continue
            pmcid = _article_id(record, "pmcid") or f"PMC{uid}"
            records.append(
                {
                    "pmc_uid": uid,
                    "pmcid": pmcid,
                    "title": record.get("title"),
                    "journal": record.get("fulljournalname") or record.get("source"),
                    "published": record.get("pubdate"),
                    "doi": _article_id(record, "doi"),
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                }
            )

    output = {"query": query, "count": len(records), "results": records}
    output_path = tool_path(
        workspace_dir,
        "literature",
        f"pmc_{safe_slug(query)}_{_utc_slug()}.json",
    )
    _write_json(output_path, output)
    output["sandbox_path"] = relative_to_workspace(output_path, workspace_dir)
    return output


async def search_pdb(
    workspace_dir: Path | str,
    query: str,
    top_k: int = 10,
    max_chain_length: int = 500,
    organism: str | None = None,
) -> dict[str, Any]:
    limit = _clamp_count(top_k, default=10)
    nodes: list[dict[str, Any]] = [
        {"type": "terminal", "service": "full_text", "parameters": {"value": query}},
        {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "entity_poly.rcsb_sample_sequence_length",
                "operator": "less",
                "value": int(max_chain_length),
            },
        },
    ]
    if organism:
        nodes.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entity_source_organism.ncbi_scientific_name",
                    "operator": "exact_match",
                    "value": organism,
                },
            }
        )
    payload = {
        "query": {"type": "group", "logical_operator": "and", "nodes": nodes},
        "return_type": "entry",
        "request_options": {"paginate": {"start": 0, "rows": limit}},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(RCSB_SEARCH_URL, json=payload)
        response.raise_for_status()
        search_payload = response.json() if response.content else {}
        identifiers = [
            str(row.get("identifier"))
            for row in search_payload.get("result_set") or []
            if isinstance(row, Mapping) and row.get("identifier")
        ]
        meta_responses = await asyncio.gather(
            *(client.get(f"{RCSB_DATA_URL}/{pdb_id}") for pdb_id in identifiers),
            return_exceptions=True,
        )

    results: list[dict[str, Any]] = []
    for pdb_id, meta_response in zip(identifiers, meta_responses, strict=False):
        if isinstance(meta_response, BaseException) or meta_response.status_code >= 400:
            results.append({"pdb_id": pdb_id, "url": f"https://www.rcsb.org/structure/{pdb_id}"})
            continue
        meta = meta_response.json()
        resolutions = (meta.get("rcsb_entry_info") or {}).get("resolution_combined") or []
        method = next(
            (
                item["method"]
                for item in meta.get("exptl") or []
                if isinstance(item, Mapping) and item.get("method")
            ),
            None,
        )
        chain_lengths: dict[str, int] = {}
        for entity in meta.get("polymer_entities") or []:
            ids = ((entity or {}).get("rcsb_polymer_entity_container_identifiers") or {}).get(
                "asym_ids"
            ) or []
            length = ((entity or {}).get("entity_poly") or {}).get("rcsb_sample_sequence_length")
            if isinstance(length, int):
                for chain_id in ids:
                    if isinstance(chain_id, str):
                        chain_lengths[chain_id] = length
        results.append(
            {
                "pdb_id": pdb_id,
                "title": (meta.get("struct") or {}).get("title"),
                "resolution": resolutions[0] if resolutions else None,
                "method": method,
                "chain_lengths_by_id": chain_lengths,
                "url": f"https://www.rcsb.org/structure/{pdb_id}",
            }
        )
    output = {"query": query, "total_count": search_payload.get("total_count"), "results": results}
    output_path = tool_path(workspace_dir, "pdb", f"search_{safe_slug(query)}_{_utc_slug()}.json")
    _write_json(output_path, output)
    output["sandbox_path"] = relative_to_workspace(output_path, workspace_dir)
    return output


async def fetch_pdb(workspace_dir: Path | str, pdb_id: str, file_format: str = "cif") -> dict[str, Any]:
    fmt = file_format.lower().lstrip(".")
    if fmt in {"mmcif", "cif"}:
        fmt = "cif"
    elif fmt != "pdb":
        raise ValueError("file_format must be 'pdb' or 'cif'.")
    pdb = re.sub(r"[^A-Za-z0-9]", "", pdb_id).upper()
    if not pdb:
        raise ValueError("pdb_id is required.")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.get(f"{RCSB_DOWNLOAD_URL}/{pdb}.{fmt}")
    response.raise_for_status()
    text = response.text
    if fmt == "pdb" and "ATOM" not in text:
        raise RuntimeError(f"Downloaded {pdb}.pdb did not contain ATOM records.")
    if fmt == "cif" and not text.lstrip().startswith("data_"):
        raise RuntimeError(f"Downloaded {pdb}.cif did not look like mmCIF text.")
    output_path = tool_path(workspace_dir, "pdb", f"{pdb}.{fmt}")
    _write_text(output_path, text)
    return {
        "pdb_id": pdb,
        "file_format": fmt,
        "sandbox_path": relative_to_workspace(output_path, workspace_dir),
        "absolute_path": str(output_path),
        "source_url": f"{RCSB_DOWNLOAD_URL}/{pdb}.{fmt}",
        "chain_order": extract_structure_chain_order(text),
        "chain_sequences": extract_structure_sequences(text),
    }


async def run_proteina(
    workspace_dir: Path | str,
    target_path: str,
    target_chains: str | None = None,
    target_input: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length_min: int = 60,
    binder_length_max: int = 90,
    num_candidates: int = 5,
    run_name: str | None = None,
    warm_start_path: str | None = None,
    warm_start_chain: str | None = None,
    nsteps: int = 20,
) -> dict[str, Any]:
    target_file = safe_workspace_path(workspace_dir, target_path)
    if not target_file.exists():
        raise FileNotFoundError(f"Target structure not found: {target_path}")
    target_structure = target_file.read_text(encoding="utf-8")
    _validate_target_input(target_input)
    target_chain_order = extract_structure_chain_order(target_structure)
    normalized_hotspots = _normalize_hotspot_residues(hotspot_residues)
    _validate_target_selectors(
        target_chains=target_chains,
        target_input=target_input,
        hotspot_residues=normalized_hotspots,
        available_chains=target_chain_order,
    )
    warm_start: dict[str, Any] | None = None
    if warm_start_path:
        warm_file = safe_workspace_path(workspace_dir, warm_start_path)
        if not warm_file.exists():
            raise FileNotFoundError(f"Warm-start structure not found: {warm_start_path}")
        warm_start = _warm_start_payload_from_file(warm_file, warm_start_chain)
    run_slug = safe_slug(run_name or f"proteina_{target_file.stem}_{_utc_slug()}", "proteina")
    count = _clamp_count(num_candidates, default=5, upper=20)
    base_url, api_key = _modal_config("MODAL_PROTEINA_URL", "MODAL_PROTEINA_API_KEY")
    target_payload: dict[str, Any] = {
        "structure": target_structure,
        "filename": target_file.name,
        "name": target_file.stem,
        "target_input": target_input,
        "hotspot_residues": normalized_hotspots,
        "binder_length": [int(binder_length_min), int(binder_length_max)],
    }
    if target_chains is not None and str(target_chains).strip():
        target_payload["chains"] = target_chains
    payload: dict[str, Any] = {
        "action": "design-cif",
        "run_name": run_slug,
        "design_steps": ["generate"],
        "overrides": [
            "++generation.search.algorithm=single-pass",
            "++generation.reward_model=null",
            f"++generation.dataloader.batch_size={count}",
            f"++generation.dataloader.dataset.nres.nsamples={count}",
            f"++generation.args.nsteps={int(nsteps)}",
        ],
        "target": target_payload,
    }
    if warm_start is not None:
        payload["warm_start"] = warm_start
    response = await _post_modal_json(
        base_url=base_url,
        api_key=api_key,
        path="/design",
        payload=payload,
    )
    run_dir = tool_path(workspace_dir, "proteina_runs", run_slug)
    run_dir.mkdir(parents=True, exist_ok=True)
    response_path = run_dir / "response.json"
    _write_json(response_path, response)
    candidates: list[dict[str, Any]] = []
    for index, record in enumerate(_extract_proteina_pdb_records(response), start=1):
        filename = safe_slug(record["filename"], f"candidate_{index}.pdb")
        if not filename.endswith(".pdb"):
            filename += ".pdb"
        candidate_path = run_dir / filename
        _write_text(candidate_path, record["pdb"])
        sequences = extract_pdb_sequences(record["pdb"])
        binder_chain = _select_binder_chain(sequences)
        target_chain = "A" if sequences.get("A") else next(iter(sequences), None)
        candidates.append(
            {
                "rank": index,
                "filename": filename,
                "sandbox_path": relative_to_workspace(candidate_path, workspace_dir),
                "chain_sequences": sequences,
                "binder_chain": binder_chain,
                "target_chain": target_chain,
                "binder_sequence": sequences.get(binder_chain, "") if binder_chain else "",
                "target_sequence": sequences.get(target_chain) if target_chain else None,
            }
        )
    return {
        "run_name": run_slug,
        "response_path": relative_to_workspace(response_path, workspace_dir),
        "count": len(candidates),
        "candidates": candidates,
        "raw_response_keys": sorted(response.keys()) if isinstance(response, Mapping) else [],
    }


async def run_chai(
    workspace_dir: Path | str,
    fasta: str | None = None,
    sequence: str | None = None,
    target_sequence: str | None = None,
    binder_sequence: str | None = None,
    target_name: str = "target",
    binder_name: str = "binder",
    run_name: str | None = None,
    num_diffn_samples: int = 5,
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    seed: int = 42,
    include_pdb: bool = True,
) -> dict[str, Any]:
    if fasta is None:
        if target_sequence and binder_sequence:
            fasta = _complex_fasta(
                target_name=target_name,
                target_sequence=target_sequence,
                binder_name=binder_name,
                binder_sequence=binder_sequence,
            )
        elif sequence:
            fasta = _fasta_record(binder_name, sequence)
        else:
            raise ValueError("Provide fasta, sequence, or target_sequence + binder_sequence.")
    run_slug = safe_slug(run_name or f"chai_{_utc_slug()}", "chai")
    base_url, api_key = _modal_config("MODAL_CHAI_URL", "MODAL_CHAI_API_KEY")
    payload = {
        "fasta": fasta,
        "num_trunk_recycles": int(num_trunk_recycles),
        "num_diffn_timesteps": int(num_diffn_timesteps),
        "num_diffn_samples": _clamp_count(num_diffn_samples, default=5, upper=10),
        "seed": int(seed),
        "include_pdb": bool(include_pdb),
        "include_viewer_html": False,
    }
    response = await _post_modal_json(
        base_url=base_url,
        api_key=api_key,
        path="/predict",
        payload=payload,
    )
    run_dir = tool_path(workspace_dir, "chai_runs", run_slug)
    run_dir.mkdir(parents=True, exist_ok=True)
    response_path = run_dir / "response.json"
    fasta_path = run_dir / "input.fasta"
    _write_text(fasta_path, fasta)
    _write_json(response_path, response)
    structures: list[dict[str, Any]] = []
    if isinstance(response, Mapping):
        for index, item in enumerate(response.get("cifs") or [], start=1):
            if not isinstance(item, Mapping):
                continue
            filename = safe_slug(str(item.get("filename") or f"rank_{index}.cif"), f"rank_{index}.cif")
            if not filename.endswith(".cif"):
                filename += ".cif"
            cif_path = run_dir / filename
            if isinstance(item.get("cif"), str):
                _write_text(cif_path, item["cif"])
            pdb_path: Path | None = None
            if isinstance(item.get("pdb"), str):
                pdb_name = safe_slug(str(item.get("pdb_filename") or cif_path.with_suffix(".pdb").name))
                if not pdb_name.endswith(".pdb"):
                    pdb_name += ".pdb"
                pdb_path = run_dir / pdb_name
                _write_text(pdb_path, item["pdb"])
            structures.append(
                {
                    "rank": item.get("rank", index),
                    "cif_path": relative_to_workspace(cif_path, workspace_dir),
                    "pdb_path": relative_to_workspace(pdb_path, workspace_dir) if pdb_path else None,
                    "aggregate_score": item.get("aggregate_score"),
                    "mean_plddt": item.get("mean_plddt"),
                }
            )
    return {
        "run_name": run_slug,
        "input_fasta_path": relative_to_workspace(fasta_path, workspace_dir),
        "response_path": relative_to_workspace(response_path, workspace_dir),
        "count": len(structures),
        "structures": structures,
    }


async def run_scorers(
    workspace_dir: Path | str,
    target_sequence: str,
    binder_sequence: str,
    target_name: str = "target",
    binder_name: str = "binder",
    complex_structure_path: str | None = None,
    chain_a: str = "A",
    chain_b: str = "B",
    run_name: str | None = None,
) -> dict[str, Any]:
    run_slug = safe_slug(run_name or f"scoring_{_utc_slug()}", "scoring")
    target_seq = _clean_sequence(target_sequence)
    binder_seq = _clean_sequence(binder_sequence)
    structure_payload: dict[str, Any] | None = None
    if complex_structure_path:
        structure_file = safe_workspace_path(workspace_dir, complex_structure_path)
        if not structure_file.exists():
            raise FileNotFoundError(f"Complex structure not found: {complex_structure_path}")
        structure_payload = {
            "format": _structure_format(structure_file),
            "content_base64": base64.b64encode(structure_file.read_bytes()).decode("ascii"),
            "chain_a": chain_a,
            "chain_b": chain_b,
        }
    scoring_url, scoring_key = _modal_config(
        "MODAL_PROTEIN_INTERACTION_SCORING_URL",
        "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY",
    )
    quality_url, quality_key = _modal_config(
        "MODAL_QUALITY_SCORERS_URL",
        "MODAL_QUALITY_SCORERS_API_KEY",
    )
    item: dict[str, Any] = {
        "id": run_slug,
        "protein_a": {"name": target_name, "sequence": target_seq},
        "protein_b": {"name": binder_name, "sequence": binder_seq},
    }
    if structure_payload is not None:
        item["structure"] = structure_payload
    interaction_task = _post_modal_json(
        base_url=scoring_url,
        api_key=scoring_key,
        path="/score_batch",
        payload={
            "items": [item],
            "options": {
                "run_dscript": True,
                "run_prodigy": True,
                "temperature_celsius": 25.0,
                "fail_fast": False,
            },
        },
    )
    quality_task = _post_modal_json(
        base_url=quality_url,
        api_key=quality_key,
        path="/predict",
        payload={"fasta": _fasta_record(binder_name, binder_seq)},
    )
    interaction_result, quality_result = await asyncio.gather(
        interaction_task,
        quality_task,
        return_exceptions=True,
    )
    run_dir = tool_path(workspace_dir, "scoring_runs", run_slug)
    run_dir.mkdir(parents=True, exist_ok=True)
    interaction_path = run_dir / "interaction_response.json"
    quality_path = run_dir / "quality_response.json"
    summary_path = run_dir / "summary.json"
    errors: dict[str, str] = {}
    if isinstance(interaction_result, BaseException):
        errors["interaction"] = str(interaction_result)
        interaction_json: Any = {"error": str(interaction_result)}
    else:
        interaction_json = interaction_result
    if isinstance(quality_result, BaseException):
        errors["quality"] = str(quality_result)
        quality_json: Any = {"error": str(quality_result)}
    else:
        quality_json = quality_result
    _write_json(interaction_path, interaction_json)
    _write_json(quality_path, quality_json)
    summary = {
        "run_name": run_slug,
        "interaction_response_path": relative_to_workspace(interaction_path, workspace_dir),
        "quality_response_path": relative_to_workspace(quality_path, workspace_dir),
        "summary_path": relative_to_workspace(summary_path, workspace_dir),
        "interaction": interaction_json,
        "quality": quality_json,
        "errors": errors,
    }
    _write_json(summary_path, summary)
    return summary


def extract_pdb_sequences(pdb_text: str) -> dict[str, str]:
    residues_by_chain: dict[str, dict[tuple[int, str], str]] = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        padded = line.ljust(27)
        chain_id = padded[21].strip() or " "
        residue_number_text = padded[22:26].strip()
        insertion_code = padded[26].strip()
        residue_name = padded[17:20].strip().upper()
        if not residue_number_text.lstrip("-").isdigit():
            continue
        residues_by_chain.setdefault(chain_id, {}).setdefault(
            (int(residue_number_text), insertion_code),
            residue_name,
        )
    return {
        chain: "".join(
            THREE_TO_ONE.get(residue_name, "X")
            for _, residue_name in sorted(residues.items(), key=lambda item: item[0])
        )
        for chain, residues in residues_by_chain.items()
    }


def extract_pdb_chain_order(pdb_text: str) -> list[str]:
    chain_order: list[str] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        chain_id = line.ljust(22)[21].strip()
        if chain_id and chain_id not in chain_order:
            chain_order.append(chain_id)
    return chain_order


def extract_structure_chain_order(structure_text: str) -> list[str]:
    if "_atom_site." in structure_text:
        return _extract_cif_chain_order(structure_text)
    return extract_pdb_chain_order(structure_text)


def extract_structure_sequences(structure_text: str) -> dict[str, str]:
    if "_atom_site." in structure_text:
        return _extract_cif_sequences(structure_text)
    return extract_pdb_sequences(structure_text)


def _utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _clamp_count(value: int, *, default: int = 8, upper: int = MAX_RESULTS_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(upper, parsed))


def _clamp_timeout(timeout_seconds: int | None, *, default: int = DEFAULT_TOOL_TIMEOUT_SECONDS) -> int:
    configured_max = int(os.getenv("JULIA_MAX_TOOL_TIMEOUT", str(default)))
    requested = default if timeout_seconds is None else int(timeout_seconds)
    return max(1, min(configured_max, requested))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _modal_config(url_var: str, key_var: str) -> tuple[str, str]:
    url = os.getenv(url_var, DEFAULT_MODAL_URLS.get(url_var, "")).strip()
    if not url:
        raise RuntimeError(f"Missing required environment variable: {url_var}")
    return url.rstrip("/"), _require_env(key_var)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


async def _post_modal_json(
    *,
    base_url: str,
    api_key: str,
    path: str,
    payload: Mapping[str, Any],
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_retries: int = 4,
) -> Any:
    """POST JSON to a Modal endpoint with retry-on-cold-start.

    Modal endpoints often return 502/503 for the first request after the
    function scales to zero. We retry transient gateway/timeout errors with
    exponential backoff so the agent can wait through a cold start without
    burning a tool call.
    """
    request_path = path if path.startswith("/") else f"/{path}"
    url = f"{base_url}{request_path}"
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.post(
                    url,
                    headers=_auth_headers(api_key),
                    json=payload,
                )
            if response.status_code in {502, 503, 504} and attempt < max_retries:
                last_error = httpx.HTTPStatusError(
                    f"transient {response.status_code} from {url}",
                    request=response.request,
                    response=response,
                )
                await asyncio.sleep(min(60.0, 2.0 * (2**attempt)))
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as error:
            last_error = error
            if attempt >= max_retries:
                raise
            await asyncio.sleep(min(60.0, 2.0 * (2**attempt)))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to POST to {url} after {max_retries + 1} attempts")


async def _get_json(url: str, *, params: Mapping[str, Any] | None = None, timeout: int = 60) -> Any:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _article_id(record: Mapping[str, Any], kind: str) -> str | None:
    ids = record.get("articleids")
    if not isinstance(ids, list):
        return None
    for item in ids:
        if isinstance(item, Mapping) and str(item.get("idtype", "")).lower() == kind:
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _clean_cif_missing_value(value: str | None) -> str:
    if value is None or value in {"", ".", "?"}:
        return ""
    return value


def _first_nonempty(row: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = _clean_cif_missing_value(row.get(key))
        if value:
            return value
    return ""


def _iter_cif_atom_site_records(cif_text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    lines = cif_text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue
        index += 1
        headers: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("_"):
            headers.append(lines[index].strip())
            index += 1
        if not headers or not all(header.startswith("_atom_site.") for header in headers):
            continue
        fields = [header.split(".", 1)[1] for header in headers]
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped == "#":
                index += 1
                break
            if stripped == "loop_" or stripped.startswith("data_") or stripped.startswith("_"):
                break
            values = shlex.split(stripped, posix=True)
            index += 1
            if len(values) < len(fields):
                continue
            row = dict(zip(fields, values, strict=False))
            if row.get("group_PDB", "ATOM").upper() != "ATOM":
                continue
            chain_id = _first_nonempty(row, "auth_asym_id", "label_asym_id")
            residue_name = _first_nonempty(row, "auth_comp_id", "label_comp_id").upper()
            residue_number = _first_nonempty(row, "auth_seq_id", "label_seq_id")
            atom_name = _first_nonempty(row, "auth_atom_id", "label_atom_id")
            if not chain_id or not residue_name or not residue_number or not atom_name:
                continue
            records.append(
                {
                    "chain_id": chain_id,
                    "residue_name": residue_name,
                    "residue_number": residue_number,
                    "insertion_code": _clean_cif_missing_value(row.get("pdbx_PDB_ins_code")),
                    "atom_name": atom_name,
                }
            )
    return records


def _extract_cif_chain_order(cif_text: str) -> list[str]:
    chain_order: list[str] = []
    for record in _iter_cif_atom_site_records(cif_text):
        chain_id = record["chain_id"]
        if chain_id not in chain_order:
            chain_order.append(chain_id)
    return chain_order


def _extract_cif_sequences(cif_text: str) -> dict[str, str]:
    residues_by_chain: dict[str, dict[tuple[int, str], str]] = {}
    for record in _iter_cif_atom_site_records(cif_text):
        residue_number_text = record["residue_number"]
        if not residue_number_text.lstrip("-").replace(".", "", 1).isdigit():
            continue
        residues_by_chain.setdefault(record["chain_id"], {}).setdefault(
            (int(float(residue_number_text)), record["insertion_code"]),
            record["residue_name"],
        )
    return {
        chain: "".join(
            THREE_TO_ONE.get(residue_name, "X")
            for _, residue_name in sorted(residues.items(), key=lambda item: item[0])
        )
        for chain, residues in residues_by_chain.items()
    }


def _infer_structure_text_format(path: Path, structure_text: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".cif", ".mmcif"}:
        return "cif"
    if suffix == ".pdb":
        return "pdb"
    stripped = structure_text.lstrip()
    if stripped.startswith(("data_", "loop_")) or "_atom_site." in structure_text:
        return "cif"
    return "pdb"


def _select_binder_chain(sequences: Mapping[str, str]) -> str | None:
    for chain_id in ("C", "B"):
        sequence = sequences.get(chain_id)
        if isinstance(sequence, str) and sequence:
            return chain_id
    for chain_id, sequence in sequences.items():
        if isinstance(sequence, str) and sequence:
            return str(chain_id)
    return None


def _warm_start_payload_from_file(warm_file: Path, warm_start_chain: str | None = None) -> dict[str, Any]:
    structure = warm_file.read_text(encoding="utf-8")
    structure_format = _infer_structure_text_format(warm_file, structure)
    chain_order = extract_structure_chain_order(structure)
    requested_chain = (warm_start_chain or "").strip() or None
    chain: str | None = None
    if requested_chain:
        if not chain_order:
            raise ValueError(f"Could not parse warm-start chain IDs from {warm_file.name}.")
        if requested_chain not in chain_order:
            raise ValueError(
                f"warm_start_chain {requested_chain!r} was not found in "
                f"{warm_file.name}; available chains are {chain_order}."
            )
        chain = requested_chain
    elif structure_format == "cif" and len(chain_order) > 1:
        raise ValueError(
            f"warm_start_chain is required for multi-chain CIF/mmCIF warm starts; "
            f"available chains are {chain_order}."
        )
    elif structure_format == "pdb" and len(chain_order) > 1:
        chain = chain_order[-1]
    payload: dict[str, Any] = {"structure": structure, "filename": warm_file.name}
    if chain:
        payload["chain"] = chain
    return payload


def _validate_target_input(target_input: str | None) -> None:
    if not target_input:
        return
    value = target_input.strip().upper()
    looks_like_sequence = len(value) > 20 and re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYX]+", value)
    if looks_like_sequence:
        raise ValueError(
            "target_input must be residue ranges like 'A1-306', not an amino-acid sequence."
        )


def _parse_chain_filter(chains: str | None) -> list[str]:
    if not chains:
        return []
    return [item.strip() for item in chains.split(",") if item.strip()]


def _target_input_chain_ids(target_input: str | None) -> list[str]:
    chain_ids: list[str] = []
    for item in (target_input or "").replace('"', "").split(","):
        item = item.strip()
        if not item:
            continue
        match = re.match(r"([A-Za-z0-9])[-+]?\d", item)
        if match and match.group(1) not in chain_ids:
            chain_ids.append(match.group(1))
    return chain_ids


def _validate_target_selectors(
    *,
    target_chains: str | None,
    target_input: str | None,
    hotspot_residues: list[str],
    available_chains: Sequence[str],
) -> None:
    if not available_chains:
        return
    available = set(available_chains)
    requested = _parse_chain_filter(target_chains)
    requested.extend(_target_input_chain_ids(target_input))
    requested.extend(hotspot[0] for hotspot in hotspot_residues if hotspot)
    missing = sorted({chain for chain in requested if chain not in available})
    if missing:
        raise ValueError(
            f"Requested target chain(s) {', '.join(missing)} were not found in "
            f"{list(available_chains)}."
        )


def _clean_sequence(sequence: str) -> str:
    cleaned = re.sub(r"[^A-Za-z]", "", sequence or "").upper()
    if not cleaned:
        raise ValueError("Protein sequence is empty after cleaning.")
    return cleaned


def _fasta_record(name: str, sequence: str) -> str:
    return f">protein|name={safe_slug(name, 'protein')}\n{_clean_sequence(sequence)}\n"


def _complex_fasta(
    *,
    target_name: str,
    target_sequence: str,
    binder_name: str,
    binder_sequence: str,
) -> str:
    return _fasta_record(target_name, target_sequence) + _fasta_record(
        binder_name,
        binder_sequence,
    )


def _extract_proteina_pdb_records(response: Any) -> list[dict[str, str]]:
    if not isinstance(response, Mapping):
        return []
    records: list[dict[str, str]] = []
    for item in response.get("pdbs") or []:
        if isinstance(item, Mapping) and isinstance(item.get("pdb"), str):
            records.append(
                {
                    "filename": str(item.get("filename") or f"candidate_{len(records) + 1}.pdb"),
                    "pdb": item["pdb"],
                }
            )
    if not records and isinstance(response.get("pdb"), str):
        records.append(
            {
                "filename": str(response.get("pdb_filename") or "candidate_1.pdb"),
                "pdb": response["pdb"],
            }
        )
    return records


def _structure_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"cif", "mmcif"}:
        return "cif"
    return "pdb"


def _normalize_hotspot_residues(hotspot_residues: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in hotspot_residues or []:
        value = str(raw).strip()
        if not value:
            continue
        direct = re.fullmatch(r"([A-Za-z])(\d+)", value)
        if direct:
            normalized.append(f"{direct.group(1).upper()}{direct.group(2)}")
            continue
        named = re.fullmatch(r"([A-Za-z]):?[A-Za-z]{3}(\d+)", value)
        if named:
            normalized.append(f"{named.group(1).upper()}{named.group(2)}")
            continue
        raise ValueError(
            "hotspot_residues must use Proteina format, e.g. 'A41' or 'A145'."
        )
    return normalized
