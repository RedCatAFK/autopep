from __future__ import annotations

from autopep_agent import demo_pipeline


def test_demo_pipeline_exposes_constants() -> None:
    assert demo_pipeline.HOTSPOT_RESIDUES == ["A41", "A145", "A163", "A166", "A189"]
    assert demo_pipeline.TARGET_PDB_ID == "6LU7"
    assert demo_pipeline.TARGET_CHAIN_ID == "A"
