"""Bind Julia tool functions to a per-run workspace and expose them as Agents-SDK tools.

The tool implementations in `julia_agent.tools` take a `workspace_dir` first
argument so we can run multiple per-run workspaces inside one Modal worker
process. The Agents SDK `function_tool` builder uses each function's typed
signature for the model schema, so we wrap each implementation in a thin
closure that omits `workspace_dir` and binds it via the enclosing scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents import function_tool

from julia_agent import tools


def build_julia_tools(workspace_dir: Path | str) -> list[Any]:
    workspace = Path(workspace_dir)

    async def execute_bash(command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        """Run an arbitrary bash command from the current run workspace directory.

        The command starts with cwd set to a fresh per-run workspace folder for
        this run. Use relative paths for files you create or inspect. The
        default and configured max timeout is 120 seconds unless
        JULIA_MAX_TOOL_TIMEOUT is raised.
        """
        return await tools.execute_bash(workspace, command, timeout_seconds)

    async def execute_python(
        script: str,
        timeout_seconds: int = 120,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Run an arbitrary Python script from the current run workspace directory.

        The script is written under outputs/tool_logs/python_runs in the fresh
        run workspace before execution so it can create or read sibling files
        using relative paths.
        """
        return await tools.execute_python(workspace, script, timeout_seconds, filename)

    async def literature_search(query: str, max_results: int = 8) -> dict[str, Any]:
        """Search the NCBI PMC database for papers and save a compact JSON result."""
        return await tools.literature_search(workspace, query, max_results)

    async def search_pdb(
        query: str,
        top_k: int = 10,
        max_chain_length: int = 500,
        organism: str | None = None,
    ) -> dict[str, Any]:
        """Search RCSB PDB for protein structures and return compact metadata."""
        return await tools.search_pdb(workspace, query, top_k, max_chain_length, organism)

    async def fetch_pdb(pdb_id: str, file_format: str = "cif") -> dict[str, Any]:
        """Download a PDB or mmCIF file from RCSB into the run workspace pdb folder.

        Defaults to CIF/mmCIF because Proteina accepts CIF target structures and
        RCSB CIF files preserve more structural metadata than legacy PDB files.
        Pass file_format="pdb" only when a downstream tool explicitly requires PDB.
        """
        return await tools.fetch_pdb(workspace, pdb_id, file_format)

    async def run_proteina(
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

        target_path and warm_start_path are workspace-relative paths. The tool
        saves the raw JSON response and each generated PDB under proteina_runs
        in the current run workspace.
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
        return await tools.run_proteina(
            workspace,
            target_path,
            target_input,
            hotspot_residues,
            binder_length_min,
            binder_length_max,
            num_candidates,
            run_name,
            warm_start_path,
            warm_start_chain,
            nsteps,
        )

    async def run_chai(
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
        return await tools.run_chai(
            workspace,
            fasta,
            sequence,
            target_sequence,
            binder_sequence,
            target_name,
            binder_name,
            run_name,
            num_diffn_samples,
            num_trunk_recycles,
            num_diffn_timesteps,
            seed,
            include_pdb,
        )

    async def run_scorers(
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

        complex_structure_path is optional. If supplied, it must be a workspace
        path to a PDB or mmCIF complex and enables structure-based PRODIGY
        scoring.
        """
        return await tools.run_scorers(
            workspace,
            target_sequence,
            binder_sequence,
            target_name,
            binder_name,
            complex_structure_path,
            chain_a,
            chain_b,
            run_name,
        )

    return [
        function_tool(execute_bash, name_override="execute_bash", strict_mode=False),
        function_tool(execute_python, name_override="execute_python", strict_mode=False),
        function_tool(literature_search, name_override="literature_search", strict_mode=False),
        function_tool(search_pdb, name_override="search_pdb", strict_mode=False),
        function_tool(fetch_pdb, name_override="fetch_pdb", strict_mode=False),
        function_tool(run_proteina, name_override="run_proteina", strict_mode=False),
        function_tool(run_chai, name_override="run_chai", strict_mode=False),
        function_tool(run_scorers, name_override="run_scorers", strict_mode=False),
    ]
