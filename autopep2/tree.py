from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from agents import (
    Agent,
    ItemHelpers,
    ModelSettings,
    Runner,
    SQLiteSession,
    function_tool,
    set_tracing_disabled,
    trace,
)
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent

import main


MAX_TREE_DEPTH = 3
TREE_TOOL_OUTPUT_CHARS = 1400


def _brief(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _tree_log(message: str) -> None:
    print(f"[tree] {message}", flush=True)


def _compact_tool_payload(name: str, kind: str, payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return _brief(payload, 220)

    if name == "execute_bash":
        if kind == "start":
            return f"cmd={_brief(payload.get('command'), 160)}"
        return (
            f"exit={payload.get('exit_code')} elapsed={payload.get('elapsed_seconds')}s "
            f"stdout={payload.get('stdout_path')} stderr={payload.get('stderr_path')}"
        )

    if name == "execute_python":
        if kind == "start":
            return f"script={payload.get('script_path')} timeout={payload.get('timeout_seconds')}s"
        return (
            f"exit={payload.get('exit_code')} elapsed={payload.get('elapsed_seconds')}s "
            f"stdout={payload.get('stdout_path')} stderr={payload.get('stderr_path')}"
        )

    if name == "literature_search":
        if kind == "start":
            return f"query={_brief(payload.get('query'), 140)}"
        return f"count={payload.get('count')} path={payload.get('sandbox_path')}"

    if name == "search_pdb":
        if kind == "start":
            return f"query={_brief(payload.get('query'), 140)} top_k={payload.get('top_k')}"
        ids = [
            item.get("pdb_id")
            for item in payload.get("results", [])
            if isinstance(item, Mapping) and item.get("pdb_id")
        ]
        return f"hits={len(ids)} ids={','.join(ids[:5])} path={payload.get('sandbox_path')}"

    if name == "fetch_pdb":
        if kind == "start":
            return f"pdb={payload.get('pdb_id')} format={payload.get('file_format')}"
        return f"pdb={payload.get('pdb_id')} path={payload.get('sandbox_path')}"

    if name == "run_proteina":
        if kind == "start":
            target = payload.get("target") if isinstance(payload.get("target"), Mapping) else {}
            warm_start = payload.get("warm_start")
            warm_chain = warm_start.get("chain") if isinstance(warm_start, Mapping) else None
            return (
                f"run={payload.get('run_name')} target={target.get('filename')} "
                f"hotspots={target.get('hotspot_residues')} warm_chain={warm_chain or '-'}"
            )
        candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        return f"run={payload.get('run_name')} candidates={len(candidates)}"

    if name == "run_chai":
        if kind == "start":
            return f"samples={payload.get('num_diffn_samples')} fasta={payload.get('fasta')}"
        structures = payload.get("structures") if isinstance(payload.get("structures"), list) else []
        best = _best_chai_structure(structures)
        best_path = _structure_path(best) if best else None
        return f"run={payload.get('run_name')} structures={len(structures)} best={best_path}"

    if name == "run_scorers":
        if kind == "start":
            return (
                f"target_len={payload.get('target_length')} binder_len={payload.get('binder_length')} "
                f"structure={payload.get('complex_structure_path')}"
            )
        errors = payload.get("errors") or {}
        return (
            f"run={payload.get('run_name')} interaction={payload.get('interaction_response_path')} "
            f"quality={payload.get('quality_response_path')} errors={bool(errors)}"
        )

    rendered = json.dumps(main._jsonable(payload, string_limit=240), sort_keys=True)
    return _brief(rendered, 320)


def _compact_tool_event(kind: str, name: str, payload: Any) -> None:
    print(f"[{kind}] {name}: {_compact_tool_payload(name, kind, payload)}", flush=True)


def _install_compact_logging() -> None:
    main._print_tool_event = _compact_tool_event


def _numeric_score_leaves(value: Any, prefix: str = "") -> list[tuple[str, float]]:
    leaves: list[tuple[str, float]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.extend(_numeric_score_leaves(item, child_prefix))
    elif isinstance(value, list):
        for index, item in enumerate(value[:8]):
            child_prefix = f"{prefix}[{index}]"
            leaves.extend(_numeric_score_leaves(item, child_prefix))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        key = prefix.lower()
        interesting = (
            "score",
            "confidence",
            "prob",
            "plddt",
            "ptm",
            "iptm",
            "pae",
            "ddg",
            "dg",
            "affinity",
            "dscript",
            "prodigy",
            "rank",
        )
        if any(part in key for part in interesting):
            leaves.append((prefix, float(value)))
    return leaves


def _score_excerpt(scoring: Mapping[str, Any]) -> dict[str, Any]:
    interaction = scoring.get("interaction")
    quality = scoring.get("quality")
    leaves = _numeric_score_leaves({"interaction": interaction, "quality": quality})
    return {key: round(value, 5) for key, value in leaves[:16]}


def _best_chai_structure(structures: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not structures:
        return None

    def rank_value(item: Mapping[str, Any]) -> tuple[float, float]:
        aggregate = item.get("aggregate_score")
        plddt = item.get("mean_plddt")
        aggregate_score = float(aggregate) if isinstance(aggregate, (int, float)) else float("-inf")
        plddt_score = float(plddt) if isinstance(plddt, (int, float)) else float("-inf")
        return aggregate_score, plddt_score

    return max(structures, key=rank_value)


def _structure_path(structure: Mapping[str, Any] | None) -> str | None:
    if not structure:
        return None
    pdb_path = structure.get("pdb_path")
    if isinstance(pdb_path, str) and pdb_path:
        return pdb_path
    cif_path = structure.get("cif_path")
    return cif_path if isinstance(cif_path, str) and cif_path else None


def _candidate_id(depth: int, rank: Any) -> str:
    return f"d{depth}_c{rank}"


async def _fold_candidate(
    *,
    run_slug: str,
    depth: int,
    candidate: Mapping[str, Any],
    target_sequence: str | None,
    target_name: str,
    num_diffn_samples: int,
) -> dict[str, Any]:
    rank = candidate.get("rank", "?")
    node_id = _candidate_id(depth, rank)
    binder_sequence = candidate.get("binder_sequence")
    candidate_target_sequence = candidate.get("target_sequence") or target_sequence
    if not isinstance(binder_sequence, str) or not binder_sequence.strip():
        return {"node_id": node_id, "candidate": candidate, "errors": ["missing binder_sequence"]}
    if not isinstance(candidate_target_sequence, str) or not candidate_target_sequence.strip():
        return {"node_id": node_id, "candidate": candidate, "errors": ["missing target_sequence"]}

    chai = await main._run_chai(
        target_sequence=candidate_target_sequence,
        binder_sequence=binder_sequence,
        target_name=target_name,
        binder_name=node_id,
        run_name=f"{run_slug}_{node_id}_chai",
        num_diffn_samples=num_diffn_samples,
        include_pdb=True,
    )
    structures = [
        item for item in chai.get("structures", []) if isinstance(item, Mapping)
    ]
    best_structure = _best_chai_structure(structures)
    return {
        "node_id": node_id,
        "candidate": candidate,
        "target_sequence": candidate_target_sequence,
        "binder_sequence": binder_sequence,
        "chai": {
            "run_name": chai.get("run_name"),
            "input_fasta_path": chai.get("input_fasta_path"),
            "response_path": chai.get("response_path"),
            "count": chai.get("count"),
            "best_structure": best_structure,
            "best_structure_path": _structure_path(best_structure),
        },
        "errors": [],
    }


async def _score_candidate(
    *,
    run_slug: str,
    folded: Mapping[str, Any],
    target_name: str,
) -> dict[str, Any]:
    if folded.get("errors"):
        return dict(folded)
    node_id = str(folded["node_id"])
    scoring = await main._run_scorers(
        target_sequence=str(folded["target_sequence"]),
        binder_sequence=str(folded["binder_sequence"]),
        target_name=target_name,
        binder_name=node_id,
        complex_structure_path=folded.get("chai", {}).get("best_structure_path"),
        run_name=f"{run_slug}_{node_id}_score",
    )
    output = dict(folded)
    output["scoring"] = {
        "run_name": scoring.get("run_name"),
        "interaction_response_path": scoring.get("interaction_response_path"),
        "quality_response_path": scoring.get("quality_response_path"),
        "errors": scoring.get("errors", {}),
        "score_excerpt": _score_excerpt(scoring),
    }
    return output


async def _run_protein_generation(
    target_path: str,
    target_sequence: str | None = None,
    target_input: str | None = None,
    hotspot_residues: list[str] | None = None,
    binder_length_min: int = 60,
    binder_length_max: int = 90,
    run_name: str | None = None,
    warm_start_path: str | None = None,
    warm_start_chain: str | None = None,
    depth: int = 0,
    parent_node_id: str | None = None,
    target_name: str = "target",
    nsteps: int = 20,
    num_diffn_samples: int = 5,
) -> dict[str, Any]:
    """Expand one tree node through Proteina, parallel Chai, and parallel scoring.

    Proteina always generates 3 candidates. Pass warm_start_path after the
    agent has used execute_python to modify the previous best candidate's PDB
    or CIF. If the warm-start file has multiple chains, pass warm_start_chain
    as the seed binder chain. depth must be 0..3. This tool does not choose the
    winner; the agent should inspect the returned candidates, choose the best,
    then create the next warm-start structure with execute_python.
    """
    _install_compact_logging()
    if depth < 0 or depth > MAX_TREE_DEPTH:
        raise ValueError(f"depth must be between 0 and {MAX_TREE_DEPTH}.")

    target_file = main._sandbox_path(target_path)
    target_label = target_name or target_file.stem
    run_slug = main._safe_slug(
        run_name or f"tree_{target_file.stem}_d{depth}_{main._utc_slug()}",
        "tree",
    )
    _tree_log(
        f"expand depth={depth} parent={parent_node_id or '-'} "
        f"target={main._relative_to_sandbox(target_file)} "
        f"warm_start={warm_start_path or '-'} warm_chain={warm_start_chain or '-'}"
    )

    proteina = await main._run_proteina(
        target_path=target_path,
        target_input=target_input,
        hotspot_residues=hotspot_residues,
        binder_length_min=binder_length_min,
        binder_length_max=binder_length_max,
        num_candidates=3,
        run_name=f"{run_slug}_proteina",
        warm_start_path=warm_start_path,
        warm_start_chain=warm_start_chain,
        nsteps=nsteps,
    )
    candidates = [
        item for item in proteina.get("candidates", []) if isinstance(item, Mapping)
    ]
    _tree_log(f"fold {len(candidates)} candidates with chai in parallel")
    folded_results = await asyncio.gather(
        *(
            _fold_candidate(
                run_slug=run_slug,
                depth=depth,
                candidate=candidate,
                target_sequence=target_sequence,
                target_name=target_label,
                num_diffn_samples=num_diffn_samples,
            )
            for candidate in candidates
        ),
        return_exceptions=True,
    )
    folded: list[dict[str, Any]] = []
    for index, result in enumerate(folded_results, start=1):
        if isinstance(result, BaseException):
            folded.append(
                {
                    "node_id": _candidate_id(depth, index),
                    "candidate": candidates[index - 1] if index - 1 < len(candidates) else {},
                    "errors": [f"{result.__class__.__name__}: {result}"],
                },
            )
        else:
            folded.append(result)

    _tree_log(f"score {len(folded)} folded candidates in parallel")
    scored_results = await asyncio.gather(
        *(
            _score_candidate(
                run_slug=run_slug,
                folded=item,
                target_name=target_label,
            )
            for item in folded
        ),
        return_exceptions=True,
    )
    scored: list[dict[str, Any]] = []
    for index, result in enumerate(scored_results, start=1):
        if isinstance(result, BaseException):
            base = folded[index - 1] if index - 1 < len(folded) else {}
            existing_errors = base.get("errors") if isinstance(base.get("errors"), list) else []
            scored.append(
                {
                    **base,
                    "errors": [*existing_errors, f"{result.__class__.__name__}: {result}"],
                },
            )
        else:
            scored.append(result)

    if depth >= MAX_TREE_DEPTH:
        next_step = "Stop tree expansion at max depth and report the best leaf candidate."
    else:
        next_step = (
            "Choose the best candidate, then use execute_python to modify that "
            "candidate's PDB/CIF into tree_edits/ and call run_protein_generation "
            f"again with depth={depth + 1} and warm_start_path."
        )
    summary = {
        "run_name": run_slug,
        "depth": depth,
        "parent_node_id": parent_node_id,
        "target_path": target_path,
        "warm_start_path": warm_start_path,
        "warm_start_chain": warm_start_chain,
        "proteina_response_path": proteina.get("response_path"),
        "candidate_count": len(scored),
        "candidates": scored,
        "next_step": next_step,
    }
    run_dir = main._sandbox_path(f"tree_runs/{run_slug}")
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    main._write_json(summary_path, summary)
    summary["summary_path"] = main._relative_to_sandbox(summary_path)
    _tree_log(f"done depth={depth} summary={summary['summary_path']}")
    return summary


execute_bash = function_tool(main._execute_bash, name_override="execute_bash", strict_mode=False)
execute_python = function_tool(main._execute_python, name_override="execute_python", strict_mode=False)
literature_research = function_tool(
    main._literature_search,
    name_override="literature_research",
    strict_mode=False,
)
search_pdb = function_tool(main._search_pdb, name_override="search_pdb", strict_mode=False)
fetch_pdb = function_tool(main._fetch_pdb, name_override="fetch_pdb", strict_mode=False)
run_protein_generation = function_tool(
    _run_protein_generation,
    name_override="run_protein_generation",
    strict_mode=False,
)


def _agent_instructions() -> str:
    return f"""
You are Autopep2 Tree, a compact terminal agent for iterative binder design.

Operate only inside this fresh per-start sandbox:
{main.SANDBOX_DIR}

Available tools:
- literature_research: search PMC literature.
- search_pdb and fetch_pdb: locate and download target structures and
  target-bound complexes. Prefer fetch_pdb(file_format="cif").
- execute_bash and execute_python: inspect files and create modified warm-start
  PDB/CIF files inside the sandbox.
- run_protein_generation: one tree expansion node that runs Proteina for exactly
  3 candidates, folds all candidates with Chai in parallel, and scores all
  folded candidates in parallel.

Tree workflow for "generate/design a binder for X":
1. Use literature_research, search_pdb, and fetch_pdb to establish the target,
   target structures, target-bound complexes, chains, hotspots, and any
   existing bound protein/peptide binders or partners. The initial PDB search is
   not only for the target; some target structures already include useful
   binders attached.
2. Almost always prefer warm-starting when a suitable existing PDB binder or
   partner is present. Use execute_python to prepare a clean warm-start PDB/CIF
   from that existing binder geometry before depth=0. Cold start exists mostly
   as a fallback so the workflow does not break when no suitable binder is
   present, only small-molecule ligands are available, or warm-start preparation
   fails.
3. Call run_protein_generation at depth=0 with the target CIF, Proteina
   hotspots in format ["A41", "A145"] (never "A:HIS41"), and warm_start_path
   when a prepared existing binder seed is available. When the warm-start file
   contains multiple chains, pass warm_start_chain as the binder or partner
   chain to seed from. For Proteina-generated complexes with target chains A/B
   and binder chain C, pass warm_start_chain="C" unless inspection shows a
   different binder chain.
4. After scorers return, evaluate the three candidates. Give a short rationale
   using scorer outputs, Chai confidence, sequence sanity, and file paths.
5. Select the best candidate. Use execute_python to create a modified PDB/CIF
   under tree_edits/ for the next warm start. Modify the binder candidate, not
   the target, unless the user explicitly asks. Write a small provenance JSON
   next to the modified file.
6. Feed that modified file back into run_protein_generation as warm_start_path
   with warm_start_chain and depth incremented by 1.
7. Continue breadth-at-each-depth generation with beam width 1 until depth
   {MAX_TREE_DEPTH}, then report the best leaf and all relevant paths.

Keep replies compact. Do not dump raw JSON; point to saved summary, Chai, and
scorer files. Do not claim wet-lab validation, clinical efficacy, safety, or
therapeutic readiness.
""".strip()


def build_agent(model: Any, model_settings: ModelSettings | None = None) -> Agent:
    return Agent(
        name="Autopep2 Tree",
        model=model,
        instructions=_agent_instructions(),
        model_settings=model_settings or ModelSettings(parallel_tool_calls=True),
        tools=[
            literature_research,
            search_pdb,
            fetch_pdb,
            execute_bash,
            execute_python,
            run_protein_generation,
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
            return main._trim_text(args, TREE_TOOL_OUTPUT_CHARS)
    return main._jsonable(args, string_limit=240)


def _item_attr(item: Any, name: str) -> Any:
    return getattr(item, name, None) or (item.get(name) if isinstance(item, dict) else None)


def _print_stream_item(event: Any, *, streamed_text: bool, calls: dict[str, str]) -> None:
    item = getattr(event, "item", None)
    if item is None and isinstance(event, dict):
        item = event.get("item")
    if item is None:
        return
    item_type = _item_attr(item, "type")
    if item_type == "tool_call_item":
        raw_item = _item_attr(item, "raw_item")
        name = getattr(raw_item, "name", None) or _item_attr(item, "name") or "tool"
        call_id = getattr(raw_item, "call_id", None) or getattr(raw_item, "id", None)
        if call_id:
            calls[str(call_id)] = str(name)
        args = json.dumps(_compact_tool_args(raw_item), sort_keys=True)
        print(f"[call] {name}: {_brief(args, 360)}", flush=True)
    elif item_type == "tool_call_output_item":
        raw_item = _item_attr(item, "raw_item")
        call_id = getattr(raw_item, "call_id", None) or _item_attr(item, "call_id")
        name = calls.get(str(call_id), "tool")
        output = _item_attr(item, "output")
        rendered = json.dumps(main._jsonable(output, string_limit=320), sort_keys=True)
        print(f"[done] {name}: {_brief(rendered, 420)}", flush=True)
    elif item_type == "message_output_item" and not streamed_text:
        try:
            text = ItemHelpers.text_message_output(item)
        except Exception:
            text = str(item)
        if text:
            print(text, flush=True)


async def run_turn(agent: Agent, session: SQLiteSession, user_input: str) -> None:
    streamed_text = False
    calls: dict[str, str] = {}
    print("[run] start", flush=True)
    with trace("autopep2 tree turn"):
        stream = Runner.run_streamed(
            agent,
            user_input,
            session=session,
            max_turns=main._agent_max_turns(),
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
            if event_type == "run_item_stream_event":
                _print_stream_item(event, streamed_text=streamed_text, calls=calls)
        if not streamed_text and getattr(stream, "final_output", None):
            print(stream.final_output, flush=True)
    print("\n[run] done", flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Autopep2 tree-search terminal agent.")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.5"),
        help="OpenAI model to use. Defaults to OPENAI_DEFAULT_MODEL or gpt-5.5.",
    )
    parser.add_argument(
        "--deepseek",
        action="store_true",
        help="Use DeepSeek V4 Pro through Fireworks AI. Requires FIREWORKS_API_KEY.",
    )
    parser.add_argument(
        "--session-id",
        default=os.getenv("AUTOPEP2_TREE_SESSION_ID", "tree"),
        help="SQLiteSession id for this tree-agent run sandbox.",
    )
    parser.add_argument("--reset-session", action="store_true", help="Clear the session before running.")
    parser.add_argument("--prompt", help="Run one prompt and exit instead of starting the REPL.")
    return parser.parse_args(argv)


async def async_main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(main.ROOT_DIR / ".env")
    args = parse_args(argv)
    _install_compact_logging()
    main._ensure_dirs()

    if args.deepseek:
        if not os.getenv("FIREWORKS_API_KEY"):
            print("Set FIREWORKS_API_KEY in autopep2/.env before using --deepseek.", file=sys.stderr)
            return 2
        if not os.getenv("OPENAI_API_KEY"):
            set_tracing_disabled(True)
        deepseek_model, deepseek_settings, model_label = main._fireworks_deepseek_model()
        model_settings = deepseek_settings.resolve(ModelSettings(parallel_tool_calls=True))
        agent = build_agent(deepseek_model, model_settings)
    else:
        if not os.getenv("OPENAI_API_KEY"):
            print("Set OPENAI_API_KEY in autopep2/.env before running.", file=sys.stderr)
            return 2
        model_label = args.model
        agent = build_agent(args.model)

    session_db = main.SANDBOX_DIR / "tree_sessions.sqlite"
    main._ensure_session_db(session_db)
    session = SQLiteSession(args.session_id, str(session_db))
    if args.reset_session:
        await session.clear_session()

    print(
        "\n".join(
            [
                "Autopep2 tree agent",
                f"model: {model_label}",
                f"max depth: {MAX_TREE_DEPTH}",
                f"sandbox: {main.SANDBOX_DIR}",
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
            user_input = input("tree> ").strip()
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
            print(f"[error] {exc.__class__.__name__}: {exc}", file=sys.stderr, flush=True)
    return 0


def main_cli() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main_cli()
