from __future__ import annotations

from autopep_agent import demo_pipeline


def test_demo_pipeline_uses_proteina_target_contract() -> None:
    assert demo_pipeline.HOTSPOT_RESIDUES == ["A41", "A145", "A163", "A166", "A189"]
    assert demo_pipeline._target_input_for_sequence("ACDE") == "A1-4"
