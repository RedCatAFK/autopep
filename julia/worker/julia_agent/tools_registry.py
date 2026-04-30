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
        """Run a bash command inside the run workspace and capture stdout/stderr.

        Use sparingly. The command runs from the workspace root with
        $JULIA_WORKSPACE_DIR set; only write under outputs/ subdirectories.
        """
        return await tools.execute_bash(workspace, command, timeout_seconds)

    async def execute_python(
        script: str,
        timeout_seconds: int = 120,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Run a Python script inside the run workspace and capture stdout/stderr.

        The script is saved under outputs/tool_logs and executed from the
        workspace root. Use this to inspect or transform structures and
        prepare warm-start inputs.
        """
        return await tools.execute_python(workspace, script, timeout_seconds, filename)

    async def literature_search(query: str, max_results: int = 8) -> dict[str, Any]:
        """Search PMC for relevant papers and write results under outputs/literature.

        Use early in the workflow to ground the target's binding biology and
        identify hotspot residues or known partners.
        """
        return await tools.literature_search(workspace, query, max_results)

    async def search_pdb(
        query: str,
        top_k: int = 10,
        max_chain_length: int = 500,
        organism: str | None = None,
    ) -> dict[str, Any]:
        """Search RCSB for target structures and write a JSON result under outputs/pdb.

        Prefer entries that contain bound binder/partner chains, which can seed
        Proteina warm starts.
        """
        return await tools.search_pdb(workspace, query, top_k, max_chain_length, organism)

    async def fetch_pdb(pdb_id: str, file_format: str = "cif") -> dict[str, Any]:
        """Download a PDB or mmCIF file from RCSB into outputs/pdb.

        Defaults to CIF/mmCIF because Proteina accepts CIF target structures.
        Pass file_format="pdb" only when a downstream tool explicitly requires it.
        """
        return await tools.fetch_pdb(workspace, pdb_id, file_format)

    async def run_proteina(
        target_path: str,
        target_chains: str | None = None,
        target_input: str | None = None,
        hotspot_residues: list[str] | None = None,
        binder_length_min: int = 60,
        binder_length_max: int = 90,
        num_candidates: int = 3,
        run_name: str | None = None,
        warm_start_path: str | None = None,
        warm_start_chain: str | None = None,
        nsteps: int = 20,
    ) -> dict[str, Any]:
        """Generate candidate binders with the Proteina-Complexa Modal endpoint.

        target_path and warm_start_path are workspace-relative. The tool writes
        the raw response and each generated PDB under outputs/proteina_runs.
        hotspot_residues use Proteina format: chain ID immediately followed by
        residue number, e.g. ["A41", "A145", "A166"].
        """
        return await tools.run_proteina(
            workspace,
            target_path,
            target_chains,
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
        """Fold a sequence or target+binder complex with Chai-1 and write results
        under outputs/chai_runs. Pass target_sequence + binder_sequence to fold
        a complex. Prefer using Proteina output sequences when available.
        """
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
        """Score a target+binder pair with the interaction and quality scorers.

        Pass complex_structure_path (workspace-relative) when a folded complex is
        available; the scorers will use it for structural features. Results are
        written under outputs/scoring_runs.
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
