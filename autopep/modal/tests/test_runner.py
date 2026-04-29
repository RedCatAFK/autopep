from __future__ import annotations

from autopep_agent.runner import (
    build_agent_instructions,
    build_autopep_agent,
    build_sandbox_config,
    choose_task_kind,
)


def _tool_names(tools: list[object]) -> set[str]:
    return {str(getattr(tool, "name", "")) for tool in tools}


def test_choose_task_kind_routes_branch_design_prompt() -> None:
    assert (
        choose_task_kind("Generate a protein that binds to 3CL-protease")
        == "branch_design"
    )


def test_choose_task_kind_routes_general_explanation_to_chat() -> None:
    assert choose_task_kind("Explain this residue selection") == "chat"


def test_build_agent_instructions_mentions_workflow_tools_and_recipes() -> None:
    recipe = "Use PDB and bioRxiv first."

    instructions = build_agent_instructions(enabled_recipes=[recipe])

    assert "life-science-research" in instructions
    assert "generate_binder_candidates" in instructions
    assert "fold_sequences_with_chai" in instructions
    assert "score_candidate_interactions" in instructions
    assert recipe in instructions


def test_build_autopep_agent_includes_biology_tools() -> None:
    agent = build_autopep_agent(enabled_recipes=[])

    assert agent.name == "Autopep"
    assert {
        "generate_binder_candidates",
        "fold_sequences_with_chai",
        "score_candidate_interactions",
    }.issubset(_tool_names(agent.tools))


def test_build_sandbox_config_returns_usable_object_without_network() -> None:
    sandbox_config = build_sandbox_config()

    assert sandbox_config is not None
