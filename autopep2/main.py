from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shlex
import sqlite3
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from agents import (
    Agent,
    AsyncOpenAI,
    ItemHelpers,
    ModelSettings,
    OpenAIChatCompletionsModel,
    Runner,
    SQLiteSession,
    function_tool,
    set_tracing_disabled,
    trace,
)
from dotenv import load_dotenv
from openai.types.shared import Reasoning
from openai.types.responses import ResponseTextDeltaEvent


ROOT_DIR = Path(__file__).resolve().parent
SANDBOX_ROOT = ROOT_DIR / "sandbox"
SANDBOX_RUN_ID = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
SANDBOX_DIR = SANDBOX_ROOT / "runs" / SANDBOX_RUN_ID
TOOL_LOG_DIR = SANDBOX_DIR / "tool_logs"
DEFAULT_BASH_TIMEOUT_SECONDS = 120
DEFAULT_HTTP_TIMEOUT_SECONDS = 900
MAX_RESULTS_LIMIT = 25
MAX_TOOL_OUTPUT_CHARS = 6000
DEFAULT_AGENT_MAX_TURNS = sys.maxsize
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
FIREWORKS_DEEPSEEK_MODEL = "accounts/fireworks/models/deepseek-v4-pro"
FIREWORKS_REASONING_EFFORT = "high"
FIREWORKS_MODEL_TIMEOUT_SECONDS = 4 * 60 * 60

RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_URL = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download"
NCBI_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

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


def _ensure_dirs() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    TOOL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _utc_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_slug(value: str, default: str = "run") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())[:80].strip("._-")
    return cleaned or default


def _sandbox_path(path: str | None, *, default_name: str | None = None) -> Path:
    _ensure_dirs()
    if path is None or not str(path).strip():
        if default_name is None:
            raise ValueError("A sandbox path is required.")
        path = default_name
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = SANDBOX_DIR / candidate
    resolved = candidate.resolve()
    sandbox_root = SANDBOX_DIR.resolve()
    if not resolved.is_relative_to(sandbox_root):
        raise ValueError(f"Path must stay inside sandbox: {path}")
    return resolved


def _relative_to_sandbox(path: Path) -> str:
    return str(path.resolve().relative_to(SANDBOX_DIR.resolve()))


def _trim_text(text: str, limit: int | None = None) -> str:
    max_chars = limit or int(os.getenv("AUTOPEP2_TOOL_OUTPUT_CHARS", MAX_TOOL_OUTPUT_CHARS))
    if len(text) <= max_chars:
        return text
    hidden = len(text) - max_chars
    return f"{text[:max_chars]}\n... <truncated {hidden} chars>"


def _jsonable(value: Any, *, string_limit: int = 1200) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(secret in key_text.lower() for secret in ("key", "token", "secret", "password")):
                output[key_text] = "<redacted>" if item else ""
            else:
                output[key_text] = _jsonable(item, string_limit=string_limit)
        return output
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, string_limit=string_limit) for item in value[:20]]
    if isinstance(value, str):
        return _trim_text(value, string_limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _print_tool_event(kind: str, name: str, payload: Any) -> None:
    rendered = json.dumps(_jsonable(payload), indent=2, sort_keys=True)
    print(f"\n[tool:{kind}] {name}\n{rendered}\n", flush=True)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ensure_session_db(path: Path) -> None:
    """Create or repair the SQLiteSession tables before the SDK uses them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES agent_sessions (session_id)
                    ON DELETE CASCADE
            )
            """,
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_messages_session_id
            ON agent_messages (session_id, id)
            """,
        )
        conn.commit()


def _clamp_count(value: int, *, default: int = 8, upper: int = MAX_RESULTS_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(upper, parsed))


def _clamp_timeout(timeout_seconds: int | None, *, default: int = DEFAULT_BASH_TIMEOUT_SECONDS) -> int:
    configured_max = int(os.getenv("AUTOPEP2_MAX_TOOL_TIMEOUT", str(default)))
    requested = default if timeout_seconds is None else int(timeout_seconds)
    return max(1, min(configured_max, requested))


def _agent_max_turns() -> int:
    configured = os.getenv("AUTOPEP2_MAX_AGENT_TURNS", "").strip()
    if not configured:
        return DEFAULT_AGENT_MAX_TURNS
    parsed = int(configured)
    return DEFAULT_AGENT_MAX_TURNS if parsed <= 0 else parsed


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def _fireworks_deepseek_model() -> tuple[OpenAIChatCompletionsModel, ModelSettings, str]:
    api_key = _require_env("FIREWORKS_API_KEY")
    base_url = (os.getenv("FIREWORKS_BASE_URL") or FIREWORKS_BASE_URL).strip().rstrip("/")
    model_name = (os.getenv("FIREWORKS_DEEPSEEK_MODEL") or FIREWORKS_DEEPSEEK_MODEL).strip()
    reasoning_effort = (
        os.getenv("FIREWORKS_REASONING_EFFORT") or FIREWORKS_REASONING_EFFORT
    ).strip()
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=httpx.Timeout(timeout=FIREWORKS_MODEL_TIMEOUT_SECONDS, connect=30.0),
    )
    model = OpenAIChatCompletionsModel(model=model_name, openai_client=client)
    settings = ModelSettings(
        reasoning=Reasoning(effort=reasoning_effort),  # type: ignore[arg-type]
    )
    label = f"{model_name} via Fireworks"
    return model, settings, label


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
) -> Any:
    request_path = path if path.startswith("/") else f"/{path}"
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            f"{base_url}{request_path}",
            headers=_auth_headers(api_key),
            json=payload,
        )
    response.raise_for_status()
    return response.json()


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


def _extract_pdb_sequences(pdb_text: str) -> dict[str, str]:
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
        chain_residues = residues_by_chain.setdefault(chain_id, {})
        chain_residues.setdefault((int(residue_number_text), insertion_code), residue_name)
    return {
        chain: "".join(
            THREE_TO_ONE.get(residue_name, "X")
            for _, residue_name in sorted(residues.items(), key=lambda item: item[0])
        )
        for chain, residues in residues_by_chain.items()
    }


def _extract_pdb_chain_order(pdb_text: str) -> list[str]:
    chain_order: list[str] = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        chain_id = line.ljust(22)[21].strip()
        if chain_id and chain_id not in chain_order:
            chain_order.append(chain_id)
    return chain_order


def _clean_cif_value(value: str | None) -> str:
    text = (value or "").strip()
    return "" if text in {"", ".", "?"} else text


def _infer_structure_format(path: Path, structure: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".cif", ".mmcif"}:
        return "cif"
    if suffix == ".pdb":
        return "pdb"
    for line in structure.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data_") or stripped == "loop_" or stripped.startswith("_atom_site."):
            return "cif"
        if line.startswith(("ATOM", "HETATM", "HEADER")):
            return "pdb"
    return "cif"


def _extract_cif_chain_order(cif_text: str) -> list[str]:
    chain_order: list[str] = []
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
            if stripped == "loop_" or stripped.startswith(("data_", "_")):
                break

            try:
                values = shlex.split(stripped, posix=True)
            except ValueError:
                index += 1
                continue
            index += 1
            if len(values) < len(fields):
                continue
            row = dict(zip(fields, values, strict=False))
            group = _clean_cif_value(row.get("group_PDB")).upper() or "ATOM"
            if group not in {"ATOM", "HETATM"}:
                continue
            chain_id = _clean_cif_value(row.get("auth_asym_id")) or _clean_cif_value(
                row.get("label_asym_id")
            )
            if chain_id and chain_id not in chain_order:
                chain_order.append(chain_id)
    return chain_order


def _extract_structure_chain_order(path: Path, structure: str) -> tuple[str, list[str]]:
    structure_format = _infer_structure_format(path, structure)
    if structure_format == "cif":
        return structure_format, _extract_cif_chain_order(structure)
    return structure_format, _extract_pdb_chain_order(structure)


def _select_binder_chain(sequences: Mapping[str, str]) -> str | None:
    for chain_id in ("C", "B"):
        sequence = sequences.get(chain_id)
        if isinstance(sequence, str) and sequence:
            return chain_id
    for chain_id, sequence in sequences.items():
        if isinstance(sequence, str) and sequence:
            return str(chain_id)
    return None


def _warm_start_payload_from_file(
    warm_file: Path,
    warm_start_chain: str | None = None,
) -> dict[str, Any]:
    structure = warm_file.read_text(encoding="utf-8")
    requested_chain = (warm_start_chain or "").strip() or None
    structure_format, chain_order = _extract_structure_chain_order(warm_file, structure)
    chain: str | None = None
    if requested_chain is not None:
        if chain_order and requested_chain not in chain_order:
            raise ValueError(
                f"warm_start_chain {requested_chain!r} was not found in {warm_file.name}. "
                f"Available chains: {chain_order}."
            )
        chain = requested_chain
    elif len(chain_order) > 1:
        if structure_format == "cif":
            raise ValueError(
                f"Warm-start CIF {warm_file.name} has multiple chains {chain_order}. "
                "Pass warm_start_chain with the seed binder chain."
            )
        chain = chain_order[-1]

    payload: dict[str, Any] = {
        "structure": structure,
        "filename": warm_file.name,
    }
    if chain:
        payload["chain"] = chain
    return payload


def _clean_sequence(sequence: str) -> str:
    cleaned = re.sub(r"[^A-Za-z]", "", sequence or "").upper()
    if not cleaned:
        raise ValueError("Protein sequence is empty after cleaning.")
    return cleaned


def _fasta_record(name: str, sequence: str) -> str:
    return f">protein|name={_safe_slug(name, 'protein')}\n{_clean_sequence(sequence)}\n"


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
                },
            )
    if not records and isinstance(response.get("pdb"), str):
        records.append(
            {
                "filename": str(response.get("pdb_filename") or "candidate_1.pdb"),
                "pdb": response["pdb"],
            },
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
            "hotspot_residues must use Proteina format: chain ID immediately "
            "followed by residue number, e.g. 'A41' or 'A145'. Do not include "
            f"residue names or separators like {value!r}."
        )
    return normalized


async def _execute_bash(command: str, timeout_seconds: int = DEFAULT_BASH_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run an arbitrary bash command from the current run sandbox directory.

    The command starts with cwd set to a fresh autopep2/sandbox/runs/<run_id>
    folder for this CLI process. Use relative paths for files you create or
    inspect. The default and configured max timeout is 120 seconds unless
    AUTOPEP2_MAX_TOOL_TIMEOUT is raised.
    """
    _ensure_dirs()
    timeout = _clamp_timeout(timeout_seconds)
    run_id = f"bash_{_utc_slug()}_{uuid.uuid4().hex[:8]}"
    _print_tool_event("start", "execute_bash", {"command": command, "timeout_seconds": timeout})
    start = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=SANDBOX_DIR,
        executable="/bin/bash",
        env={
            **os.environ,
            "SANDBOX_DIR": str(SANDBOX_DIR),
            "SANDBOX_ROOT": str(SANDBOX_ROOT),
            "SANDBOX_RUN_ID": SANDBOX_RUN_ID,
        },
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
    elapsed = round(time.monotonic() - start, 3)
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    stdout_path = TOOL_LOG_DIR / f"{run_id}.stdout.txt"
    stderr_path = TOOL_LOG_DIR / f"{run_id}.stderr.txt"
    _write_text(stdout_path, stdout)
    _write_text(stderr_path, stderr)
    result = {
        "command": command,
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "stdout": _trim_text(stdout),
        "stderr": _trim_text(stderr),
        "stdout_path": _relative_to_sandbox(stdout_path),
        "stderr_path": _relative_to_sandbox(stderr_path),
    }
    _print_tool_event("end", "execute_bash", result)
    return result


async def _execute_python(
    script: str,
    timeout_seconds: int = DEFAULT_BASH_TIMEOUT_SECONDS,
    filename: str | None = None,
) -> dict[str, Any]:
    """Run an arbitrary Python script from the current run sandbox directory.

    The script is written under python_runs in the fresh run sandbox before
    execution so it can create or read sibling files using relative paths.
    """
    _ensure_dirs()
    timeout = _clamp_timeout(timeout_seconds)
    script_name = _safe_slug(filename or f"script_{_utc_slug()}_{uuid.uuid4().hex[:8]}", "script")
    if not script_name.endswith(".py"):
        script_name += ".py"
    script_path = _sandbox_path(f"python_runs/{script_name}")
    _write_text(script_path, script)
    _print_tool_event(
        "start",
        "execute_python",
        {"script_path": _relative_to_sandbox(script_path), "timeout_seconds": timeout},
    )
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        cwd=SANDBOX_DIR,
        env={
            **os.environ,
            "SANDBOX_DIR": str(SANDBOX_DIR),
            "SANDBOX_ROOT": str(SANDBOX_ROOT),
            "SANDBOX_RUN_ID": SANDBOX_RUN_ID,
        },
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
    elapsed = round(time.monotonic() - start, 3)
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    stdout_path = TOOL_LOG_DIR / f"{script_path.stem}.stdout.txt"
    stderr_path = TOOL_LOG_DIR / f"{script_path.stem}.stderr.txt"
    _write_text(stdout_path, stdout)
    _write_text(stderr_path, stderr)
    result = {
        "script_path": _relative_to_sandbox(script_path),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "stdout": _trim_text(stdout),
        "stderr": _trim_text(stderr),
        "stdout_path": _relative_to_sandbox(stdout_path),
        "stderr_path": _relative_to_sandbox(stderr_path),
    }
    _print_tool_event("end", "execute_python", result)
    return result


async def _literature_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """Search the NCBI PMC database for papers and save a compact JSON result."""
    limit = _clamp_count(max_results, default=8)
    _print_tool_event("start", "literature_search", {"query": query, "max_results": limit})
    params: dict[str, Any] = {
        "db": "pmc",
        "retmode": "json",
        "retmax": limit,
        "term": query,
    }
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    if os.getenv("NCBI_TOOL_EMAIL"):
        params["email"] = os.environ["NCBI_TOOL_EMAIL"]
        params["tool"] = "autopep2-agent"

    search_payload = await _get_json(NCBI_SEARCH_URL, params=params)
    ids = [
        item
        for item in search_payload.get("esearchresult", {}).get("idlist", [])
        if isinstance(item, str)
    ]
    records: list[dict[str, Any]] = []
    if ids:
        summary_params = {
            "db": "pmc",
            "retmode": "json",
            "id": ",".join(ids),
        }
        if os.getenv("NCBI_API_KEY"):
            summary_params["api_key"] = os.environ["NCBI_API_KEY"]
        summary_payload = await _get_json(NCBI_SUMMARY_URL, params=summary_params)
        result_block = summary_payload.get("result", {})
        for uid in result_block.get("uids", ids):
            record = result_block.get(uid)
            if not isinstance(record, Mapping):
                continue
            pmcid = _article_id(record, "pmcid") or f"PMC{uid}"
            doi = _article_id(record, "doi")
            records.append(
                {
                    "pmc_uid": uid,
                    "pmcid": pmcid,
                    "title": record.get("title"),
                    "journal": record.get("fulljournalname") or record.get("source"),
                    "published": record.get("pubdate"),
                    "doi": doi,
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                },
            )

    output = {
        "query": query,
        "count": len(records),
        "results": records,
    }
    output_path = _sandbox_path(f"literature/pmc_{_safe_slug(query)}_{_utc_slug()}.json")
    _write_json(output_path, output)
    output["sandbox_path"] = _relative_to_sandbox(output_path)
    _print_tool_event("end", "literature_search", output)
    return output


async def _search_pdb(
    query: str,
    top_k: int = 10,
    max_chain_length: int = 500,
    organism: str | None = None,
) -> dict[str, Any]:
    """Search RCSB PDB for protein structures and return compact metadata."""
    limit = _clamp_count(top_k, default=10)
    _print_tool_event(
        "start",
        "search_pdb",
        {
            "query": query,
            "top_k": limit,
            "max_chain_length": max_chain_length,
            "organism": organism,
        },
    )
    nodes: list[dict[str, Any]] = [
        {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
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
            },
        )
    payload = {
        "query": {"type": "group", "logical_operator": "and", "nodes": nodes},
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": limit},
        },
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
        method = None
        for item in meta.get("exptl") or []:
            if isinstance(item, Mapping) and item.get("method"):
                method = item["method"]
                break
        chain_lengths: dict[str, int] = {}
        for entity in meta.get("polymer_entities") or []:
            ids = (
                (entity or {}).get("rcsb_polymer_entity_container_identifiers") or {}
            ).get("asym_ids") or []
            length = ((entity or {}).get("entity_poly") or {}).get(
                "rcsb_sample_sequence_length",
            )
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
            },
        )
    output = {
        "query": query,
        "total_count": search_payload.get("total_count"),
        "results": results,
    }
    output_path = _sandbox_path(f"pdb/search_{_safe_slug(query)}_{_utc_slug()}.json")
    _write_json(output_path, output)
    output["sandbox_path"] = _relative_to_sandbox(output_path)
    _print_tool_event("end", "search_pdb", output)
    return output


async def _fetch_pdb(pdb_id: str, file_format: str = "cif") -> dict[str, Any]:
    """Download a PDB or mmCIF file from RCSB into the run sandbox pdb folder.

    Defaults to CIF/mmCIF because Proteina accepts CIF target structures and
    RCSB CIF files preserve more structural metadata than legacy PDB files.
    Pass file_format="pdb" only when a downstream tool explicitly requires PDB.
    """
    fmt = file_format.lower().lstrip(".")
    if fmt in {"mmcif", "cif"}:
        fmt = "cif"
    elif fmt != "pdb":
        raise ValueError("file_format must be 'pdb' or 'cif'.")
    pdb = re.sub(r"[^A-Za-z0-9]", "", pdb_id).upper()
    if not pdb:
        raise ValueError("pdb_id is required.")
    _print_tool_event("start", "fetch_pdb", {"pdb_id": pdb, "file_format": fmt})
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.get(f"{RCSB_DOWNLOAD_URL}/{pdb}.{fmt}")
    response.raise_for_status()
    text = response.text
    if fmt == "pdb" and "ATOM" not in text:
        raise RuntimeError(f"Downloaded {pdb}.pdb did not contain ATOM records.")
    if fmt == "cif" and not text.lstrip().startswith("data_"):
        raise RuntimeError(f"Downloaded {pdb}.cif did not look like mmCIF text.")
    output_path = _sandbox_path(f"pdb/{pdb}.{fmt}")
    _write_text(output_path, text)
    sequences = _extract_pdb_sequences(text) if fmt == "pdb" else {}
    result = {
        "pdb_id": pdb,
        "file_format": fmt,
        "sandbox_path": _relative_to_sandbox(output_path),
        "absolute_path": str(output_path),
        "source_url": f"{RCSB_DOWNLOAD_URL}/{pdb}.{fmt}",
        "chain_sequences": sequences,
    }
    _print_tool_event("end", "fetch_pdb", result)
    return result


async def _run_proteina(
    target_path: str,
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
    """Generate candidate binders with the Proteina-Complexa Modal endpoint.

    target_path and warm_start_path are sandbox-relative paths. The tool saves
    the raw JSON response and each generated PDB under proteina_runs in the
    current run sandbox.
    hotspot_residues must use Proteina format: chain ID followed immediately
    by residue number, e.g. ["A41", "A145", "A166"]. Do not pass values like
    "A:HIS41" or "A:CYS145".
    For clean binder-only CIF/mmCIF seeds, omit warm_start_chain. If
    warm_start_path contains a multi-chain target+binder complex, pass
    warm_start_chain as the seed binder chain, e.g. "C" for Proteina outputs
    where target chains are A/B and the binder chain is C. When omitted for a
    multi-chain PDB seed, the last chain in the file is used for compatibility;
    multi-chain CIF/mmCIF seeds require an explicit warm_start_chain.
    """
    target_file = _sandbox_path(target_path)
    if not target_file.exists():
        raise FileNotFoundError(f"Target structure not found: {target_path}")
    target_structure = target_file.read_text(encoding="utf-8")
    warm_start: dict[str, Any] | None = None
    if warm_start_path:
        warm_file = _sandbox_path(warm_start_path)
        if not warm_file.exists():
            raise FileNotFoundError(f"Warm-start structure not found: {warm_start_path}")
        warm_start = _warm_start_payload_from_file(warm_file, warm_start_chain)
    run_slug = _safe_slug(run_name or f"proteina_{target_file.stem}_{_utc_slug()}", "proteina")
    count = _clamp_count(num_candidates, default=5, upper=20)
    normalized_hotspots = _normalize_hotspot_residues(hotspot_residues)
    base_url, api_key = _modal_config("MODAL_PROTEINA_URL", "MODAL_PROTEINA_API_KEY")
    overrides = [
        "++generation.search.algorithm=single-pass",
        "++generation.reward_model=null",
        f"++generation.dataloader.batch_size={count}",
        f"++generation.dataloader.dataset.nres.nsamples={count}",
        f"++generation.args.nsteps={int(nsteps)}",
    ]
    payload: dict[str, Any] = {
        "action": "design-cif",
        "run_name": run_slug,
        "design_steps": ["generate"],
        "overrides": overrides,
        "target": {
            "structure": target_structure,
            "filename": target_file.name,
            "name": target_file.stem,
            "target_input": target_input,
            "hotspot_residues": normalized_hotspots,
            "binder_length": [int(binder_length_min), int(binder_length_max)],
        },
    }
    if warm_start is not None:
        payload["warm_start"] = warm_start

    request_log = {
        **payload,
        "target": {**payload["target"], "structure": f"<{len(target_structure)} chars>"},
    }
    if warm_start is not None:
        request_log["warm_start"] = {
            "filename": warm_start["filename"],
            "chain": warm_start.get("chain"),
            "structure": f"<{len(warm_start['structure'])} chars>",
        }
    _print_tool_event("start", "run_proteina", request_log)
    response = await _post_modal_json(
        base_url=base_url,
        api_key=api_key,
        path="/design",
        payload=payload,
    )

    run_dir = _sandbox_path(f"proteina_runs/{run_slug}")
    run_dir.mkdir(parents=True, exist_ok=True)
    response_path = run_dir / "response.json"
    _write_json(response_path, response)
    candidates: list[dict[str, Any]] = []
    for index, record in enumerate(_extract_proteina_pdb_records(response), start=1):
        filename = _safe_slug(record["filename"], f"candidate_{index}.pdb")
        if not filename.endswith(".pdb"):
            filename += ".pdb"
        candidate_path = run_dir / filename
        _write_text(candidate_path, record["pdb"])
        sequences = _extract_pdb_sequences(record["pdb"])
        binder_chain = _select_binder_chain(sequences)
        target_chain = "A" if sequences.get("A") else next(iter(sequences), None)
        candidates.append(
            {
                "rank": index,
                "filename": filename,
                "sandbox_path": _relative_to_sandbox(candidate_path),
                "chain_sequences": sequences,
                "binder_chain": binder_chain,
                "target_chain": target_chain,
                "binder_sequence": sequences.get(binder_chain, "") if binder_chain else "",
                "target_sequence": sequences.get(target_chain) if target_chain else None,
            },
        )
    result = {
        "run_name": run_slug,
        "response_path": _relative_to_sandbox(response_path),
        "count": len(candidates),
        "candidates": candidates,
        "raw_response_keys": sorted(response.keys()) if isinstance(response, Mapping) else [],
    }
    _print_tool_event("end", "run_proteina", result)
    return result


async def _run_chai(
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
    """Fold one sequence or a target+binder complex with the Chai-1 endpoint."""
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
    run_slug = _safe_slug(run_name or f"chai_{_utc_slug()}", "chai")
    samples = _clamp_count(num_diffn_samples, default=5, upper=10)
    base_url, api_key = _modal_config("MODAL_CHAI_URL", "MODAL_CHAI_API_KEY")
    payload = {
        "fasta": fasta,
        "num_trunk_recycles": int(num_trunk_recycles),
        "num_diffn_timesteps": int(num_diffn_timesteps),
        "num_diffn_samples": samples,
        "seed": int(seed),
        "include_pdb": bool(include_pdb),
        "include_viewer_html": False,
    }
    _print_tool_event(
        "start",
        "run_chai",
        {**payload, "fasta": f"<{len(fasta)} chars, {fasta.count('>')} FASTA records>"},
    )
    response = await _post_modal_json(
        base_url=base_url,
        api_key=api_key,
        path="/predict",
        payload=payload,
    )
    run_dir = _sandbox_path(f"chai_runs/{run_slug}")
    run_dir.mkdir(parents=True, exist_ok=True)
    response_path = run_dir / "response.json"
    fasta_path = run_dir / "input.fasta"
    _write_text(fasta_path, fasta)
    _write_json(response_path, response)
    structures: list[dict[str, Any]] = []
    # TODO: When adding Mol* viewer metadata, color target chains blue and binder chains orange.
    if isinstance(response, Mapping):
        for index, item in enumerate(response.get("cifs") or [], start=1):
            if not isinstance(item, Mapping):
                continue
            filename = _safe_slug(str(item.get("filename") or f"rank_{index}.cif"), f"rank_{index}.cif")
            if not filename.endswith(".cif"):
                filename += ".cif"
            cif_path = run_dir / filename
            if isinstance(item.get("cif"), str):
                _write_text(cif_path, item["cif"])
            pdb_path: Path | None = None
            if isinstance(item.get("pdb"), str):
                pdb_name = _safe_slug(str(item.get("pdb_filename") or cif_path.with_suffix(".pdb").name))
                if not pdb_name.endswith(".pdb"):
                    pdb_name += ".pdb"
                pdb_path = run_dir / pdb_name
                _write_text(pdb_path, item["pdb"])
            structures.append(
                {
                    "rank": item.get("rank", index),
                    "cif_path": _relative_to_sandbox(cif_path),
                    "pdb_path": _relative_to_sandbox(pdb_path) if pdb_path else None,
                    "aggregate_score": item.get("aggregate_score"),
                    "mean_plddt": item.get("mean_plddt"),
                },
            )
    result = {
        "run_name": run_slug,
        "input_fasta_path": _relative_to_sandbox(fasta_path),
        "response_path": _relative_to_sandbox(response_path),
        "count": len(structures),
        "structures": structures,
    }
    _print_tool_event("end", "run_chai", result)
    return result


async def _run_scorers(
    target_sequence: str,
    binder_sequence: str,
    target_name: str = "target",
    binder_name: str = "binder",
    complex_structure_path: str | None = None,
    chain_a: str = "A",
    chain_b: str = "B",
    run_name: str | None = None,
) -> dict[str, Any]:
    """Run interaction scoring and binder quality scoring in parallel.

    complex_structure_path is optional. If supplied, it must be a sandbox path
    to a PDB or mmCIF complex and enables structure-based PRODIGY scoring.
    """
    run_slug = _safe_slug(run_name or f"scoring_{_utc_slug()}", "scoring")
    target_seq = _clean_sequence(target_sequence)
    binder_seq = _clean_sequence(binder_sequence)
    structure_payload: dict[str, Any] | None = None
    if complex_structure_path:
        structure_file = _sandbox_path(complex_structure_path)
        if not structure_file.exists():
            raise FileNotFoundError(f"Complex structure not found: {complex_structure_path}")
        structure_bytes = structure_file.read_bytes()
        structure_payload = {
            "format": _structure_format(structure_file),
            "content_base64": base64.b64encode(structure_bytes).decode("ascii"),
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
    interaction_payload = {
        "items": [item],
        "options": {
            "run_dscript": True,
            "run_prodigy": True,
            "temperature_celsius": 25.0,
            "fail_fast": False,
        },
    }
    quality_payload = {"fasta": _fasta_record(binder_name, binder_seq)}
    log_payload = {
        "target_name": target_name,
        "binder_name": binder_name,
        "target_length": len(target_seq),
        "binder_length": len(binder_seq),
        "complex_structure_path": complex_structure_path,
        "chain_a": chain_a,
        "chain_b": chain_b,
    }
    _print_tool_event("start", "run_scorers", log_payload)

    interaction_task = _post_modal_json(
        base_url=scoring_url,
        api_key=scoring_key,
        path="/score_batch",
        payload=interaction_payload,
    )
    quality_task = _post_modal_json(
        base_url=quality_url,
        api_key=quality_key,
        path="/predict",
        payload=quality_payload,
    )
    interaction_result, quality_result = await asyncio.gather(
        interaction_task,
        quality_task,
        return_exceptions=True,
    )
    run_dir = _sandbox_path(f"scoring_runs/{run_slug}")
    run_dir.mkdir(parents=True, exist_ok=True)
    interaction_path = run_dir / "interaction_response.json"
    quality_path = run_dir / "quality_response.json"
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
        "interaction_response_path": _relative_to_sandbox(interaction_path),
        "quality_response_path": _relative_to_sandbox(quality_path),
        "interaction": interaction_json,
        "quality": quality_json,
        "errors": errors,
    }
    _write_json(run_dir / "summary.json", summary)
    _print_tool_event("end", "run_scorers", summary)
    return summary


execute_bash = function_tool(_execute_bash, name_override="execute_bash", strict_mode=False)
execute_python = function_tool(_execute_python, name_override="execute_python", strict_mode=False)
literature_search = function_tool(_literature_search, name_override="literature_search", strict_mode=False)
search_pdb = function_tool(_search_pdb, name_override="search_pdb", strict_mode=False)
fetch_pdb = function_tool(_fetch_pdb, name_override="fetch_pdb", strict_mode=False)
run_proteina = function_tool(_run_proteina, name_override="run_proteina", strict_mode=False)
run_chai = function_tool(_run_chai, name_override="run_chai", strict_mode=False)
run_scorers = function_tool(_run_scorers, name_override="run_scorers", strict_mode=False)


def _agent_instructions() -> str:
    return f"""
You are Autopep2, a terminal protein-design assistant running through the
OpenAI Agents SDK.

Operate only inside this local sandbox folder:
{SANDBOX_DIR}

This sandbox is a fresh per-CLI-start run folder under autopep2/sandbox/runs.
Do not assume files from previous CLI starts exist unless the user gives an
explicit path.

You can create files, run bash/Python, search PMC, search/fetch RCSB PDB
structures, call Proteina-Complexa, fold sequences or target+binder complexes
with Chai-1, and score candidates with the interaction and quality scorers.

Use this workflow whenever the user requests binder protein generation, e.g.
"generate a protein that binds to X" or "design binders for X":
1. Run literature_search to identify the target, relevant binding/interface
   biology, known ligands/complexes, and any useful hotspot residues.
2. Run search_pdb for target structures and target-bound complexes, not only
   apo target structures. Some PDB entries already have bound protein or
   peptide binders/partners; prefer relevant structures with attached binders
   because an existing binder can seed Proteina warm-start generation.
3. Choose promising structures or chains using the literature context,
   structural relevance, method, resolution, chain lengths, and bound
   partners/ligands when available.
4. Fetch the selected PDB target or target-complex structure with fetch_pdb using
   file_format="cif". Use CIF/mmCIF for fetched target structures unless a
   downstream tool explicitly requires PDB.
5. Inspect files with execute_bash or execute_python to confirm chains, target
   sequence, residue numbering, candidate inputs, and whether a bound binder or
   partner chain is present.
6. Almost always prefer a warm start when PDB search finds an existing bound
   binder/partner for the target. Use execute_python to prepare a clean
   warm_start_path from the existing binder geometry. Cold start is mainly a
   fallback so the workflow still runs when no suitable binder exists, the PDB
   only has small-molecule ligands, or warm-start preparation fails. For clean
   binder-only CIF/mmCIF seeds, omit warm_start_chain. When the warm-start file
   has multiple chains, pass warm_start_chain as the binder or partner chain to
   seed from. Do not infer mmCIF chain IDs with fixed-width PDB columns. For
   Proteina-generated complexes with target chains A/B and binder chain C, pass
   warm_start_chain="C" unless inspection shows a different binder chain.
7. Run run_proteina with num_candidates=3. Pass warm_start_path whenever a
   suitable prepared existing binder seed is available. For hotspot_residues,
   use Proteina format only: chain ID immediately followed by residue number, e.g.
   ["A41", "A145", "A166"]. Do not include residue names or separators;
   wrong examples are "A:HIS41", "A:CYS145", and "A:GLU166".
8. Fold each of the 3 Proteina candidates with run_chai as target+binder
   complexes. Use target_sequence and binder_sequence from run_proteina
   outputs when available. Run the 3 Chai folds in parallel when the tool
   runner permits parallel calls.
9. Run run_scorers on each folded candidate, using the best Chai complex
   structure path for each candidate when available. Run the 3 scoring jobs in
   parallel when the tool runner permits parallel calls.
10. Report ranked results with candidate file paths, Chai output paths, scorer
   output paths, and a clear split between literature/PDB evidence and
   computed model/scoring output.

Use concrete file paths from tool outputs. Prefer CIF/mmCIF files for Proteina
target inputs and Chai CIF/PDB outputs for scoring. Do not claim wet-lab
validation, clinical efficacy, safety, or therapeutic readiness.

Keep terminal replies concise, but show enough detail that the user can see the
next useful command or output file.
""".strip()


def build_agent(model: Any, model_settings: ModelSettings | None = None) -> Agent:
    return Agent(
        name="Autopep2",
        model=model,
        instructions=_agent_instructions(),
        model_settings=model_settings or ModelSettings(),
        tools=[
            execute_bash,
            execute_python,
            literature_search,
            search_pdb,
            fetch_pdb,
            run_proteina,
            run_chai,
            run_scorers,
        ],
    )


def _event_type(event: Any) -> str | None:
    return getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)


def _event_data(event: Any) -> Any:
    return getattr(event, "data", None) or (event.get("data") if isinstance(event, dict) else None)


def _compact_tool_args(raw_item: Any) -> Any:
    args = getattr(raw_item, "arguments", None)
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return _trim_text(args, 1200)
    return _jsonable(args)


def _print_stream_item(event: Any, *, streamed_text: bool) -> None:
    item = getattr(event, "item", None)
    if item is None and isinstance(event, dict):
        item = event.get("item")
    if item is None:
        return
    item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
    if item_type == "tool_call_item":
        raw_item = getattr(item, "raw_item", None)
        name = getattr(raw_item, "name", None) or getattr(item, "name", None) or "tool"
        print(
            f"\n[agent:tool_call] {name}\n"
            f"{json.dumps(_jsonable(_compact_tool_args(raw_item)), indent=2, sort_keys=True)}\n",
            flush=True,
        )
    elif item_type == "tool_call_output_item":
        output = getattr(item, "output", None) or (item.get("output") if isinstance(item, dict) else None)
        print(
            f"\n[agent:tool_output]\n{json.dumps(_jsonable(output), indent=2, sort_keys=True)}\n",
            flush=True,
        )
    elif item_type == "message_output_item" and not streamed_text:
        try:
            text = ItemHelpers.text_message_output(item)
        except Exception:
            text = str(item)
        if text:
            print(text, flush=True)


async def run_turn(agent: Agent, session: SQLiteSession, user_input: str) -> None:
    streamed_text = False
    print("\n[run:start]\n", flush=True)
    with trace("autopep2 terminal turn"):
        stream = Runner.run_streamed(
            agent,
            user_input,
            session=session,
            max_turns=_agent_max_turns(),
        )
        async for event in stream.stream_events():
            event_type = _event_type(event)
            if event_type == "raw_response_event":
                data = _event_data(event)
                data_type = getattr(data, "type", None) or (
                    data.get("type") if isinstance(data, dict) else None
                )
                if isinstance(data, ResponseTextDeltaEvent) or data_type == "response.output_text.delta":
                    delta = getattr(data, "delta", None) or (
                        data.get("delta") if isinstance(data, dict) else ""
                    )
                    if delta:
                        streamed_text = True
                        print(delta, end="", flush=True)
                continue
            if event_type == "agent_updated_stream_event":
                new_agent = getattr(event, "new_agent", None)
                name = getattr(new_agent, "name", None) or "agent"
                print(f"\n[agent:update] {name}\n", flush=True)
                continue
            if event_type == "run_item_stream_event":
                _print_stream_item(event, streamed_text=streamed_text)
                continue
        if not streamed_text and getattr(stream, "final_output", None):
            print(stream.final_output, flush=True)
    print("\n[run:done]\n", flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Autopep2 terminal agent.")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.5"),
        help="OpenAI model to use. Defaults to OPENAI_DEFAULT_MODEL or gpt-5.5.",
    )
    parser.add_argument(
        "--deepseek",
        action="store_true",
        help=(
            "Use DeepSeek V4 Pro through Fireworks AI. "
            "This overrides --model and requires FIREWORKS_API_KEY."
        ),
    )
    parser.add_argument(
        "--session-id",
        default=os.getenv("AUTOPEP2_SESSION_ID", "default"),
        help="SQLiteSession id for conversation memory.",
    )
    parser.add_argument("--reset-session", action="store_true", help="Clear the session before running.")
    parser.add_argument("--prompt", help="Run one prompt and exit instead of starting the REPL.")
    return parser.parse_args(argv)


async def async_main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(ROOT_DIR / ".env")
    args = parse_args(argv)
    _ensure_dirs()
    if args.deepseek:
        if not os.getenv("FIREWORKS_API_KEY"):
            print("Set FIREWORKS_API_KEY in autopep2/.env before using --deepseek.", file=sys.stderr)
            return 2
        if not os.getenv("OPENAI_API_KEY"):
            set_tracing_disabled(True)
    elif not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY in autopep2/.env before running.", file=sys.stderr)
        return 2

    model_label = args.model
    if args.deepseek:
        deepseek_model, deepseek_settings, model_label = _fireworks_deepseek_model()
        agent = build_agent(deepseek_model, deepseek_settings)
    else:
        agent = build_agent(args.model)
    session_db = SANDBOX_DIR / "sessions.sqlite"
    _ensure_session_db(session_db)
    session = SQLiteSession(args.session_id, str(session_db))
    if args.reset_session:
        await session.clear_session()
    print(
        "\n".join(
            [
                "Autopep2 terminal agent",
                f"model: {model_label}",
                f"session: {args.session_id}",
                f"sandbox run: {SANDBOX_RUN_ID}",
                f"sandbox: {SANDBOX_DIR}",
                "commands: :reset, :exit",
                "",
            ],
        ),
        flush=True,
    )

    if args.prompt:
        await run_turn(agent, session, args.prompt)
        return 0

    while True:
        try:
            user_input = input("autopep2> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_input:
            continue
        if user_input in {":exit", ":quit", "exit", "quit"}:
            return 0
        if user_input == ":reset":
            await session.clear_session()
            print("[session] cleared")
            continue
        try:
            await run_turn(agent, session, user_input)
        except Exception as exc:
            print(f"\n[run:error] {exc.__class__.__name__}: {exc}\n", file=sys.stderr, flush=True)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
