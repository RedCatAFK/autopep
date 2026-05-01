"""Tests covering target_input auto-inference/correction and hotspot validation.

These mirror the autopep2 helpers (`_normalize_target_input_for_structure` and
`_validate_hotspots_for_structure`) so the julia worker keeps feature parity
with the local CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from julia_agent.tools import (
    _normalize_hotspot_residues,
    _normalize_target_input_for_structure,
    _validate_hotspots_for_structure,
    _warm_start_payload_from_file,
)


def _two_chain_pdb() -> str:
    """A minimal PDB with two chains: A residues 10-12 and B residues 5-6."""
    lines = [
        "ATOM      1  N   ALA A  10      0.000   0.000   0.000  1.00  0.00           N",
        "ATOM      2  CA  ALA A  11      0.000   0.000   0.000  1.00  0.00           C",
        "ATOM      3  CA  ALA A  12      0.000   0.000   0.000  1.00  0.00           C",
        "ATOM      4  CA  GLY B   5      0.000   0.000   0.000  1.00  0.00           C",
        "ATOM      5  CA  GLY B   6      0.000   0.000   0.000  1.00  0.00           C",
    ]
    return "\n".join(lines) + "\n"


def test_normalize_target_input_infers_when_missing(tmp_path: Path) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    inferred, guard = _normalize_target_input_for_structure(None, target, structure)

    assert inferred == "A10-12,B5-6"
    assert guard["status"] == "inferred"
    assert guard["available_ranges"] == {"A": "10-12", "B": "5-6"}


def test_normalize_target_input_passes_valid_ranges_through(tmp_path: Path) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    normalized, guard = _normalize_target_input_for_structure(
        "A10-12", target, structure
    )

    assert normalized == "A10-12"
    assert guard["status"] == "valid"


def test_normalize_target_input_corrects_missing_residues(tmp_path: Path) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    # Asking for A8-15 — only A10-12 actually exist; expect correction.
    normalized, guard = _normalize_target_input_for_structure(
        "A8-15", target, structure
    )

    assert normalized == "A10-12"
    assert guard["status"] == "corrected"
    assert guard["missing_residues"]["A"] == [8, 9, 13, 14, 15]


def test_normalize_target_input_rejects_unknown_chain(tmp_path: Path) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    with pytest.raises(ValueError, match="chain 'Z'"):
        _normalize_target_input_for_structure("Z1-10", target, structure)


def test_normalize_target_input_rejects_no_overlap(tmp_path: Path) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    with pytest.raises(ValueError, match="no available residues"):
        _normalize_target_input_for_structure("A100-200", target, structure)


def test_validate_hotspots_against_structure_accepts_present_residues(
    tmp_path: Path,
) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    normalized = _validate_hotspots_for_structure(["A11", "B6"], target, structure)

    assert normalized == ["A11", "B6"]


def test_validate_hotspots_against_structure_rejects_missing_residue(
    tmp_path: Path,
) -> None:
    structure = _two_chain_pdb()
    target = tmp_path / "target.pdb"
    target.write_text(structure, encoding="utf-8")

    with pytest.raises(ValueError, match="not present in the target"):
        _validate_hotspots_for_structure(["A99"], target, structure)


def test_normalize_hotspot_residues_accepts_named_format() -> None:
    assert _normalize_hotspot_residues(["A:HIS41", "A145"]) == ["A41", "A145"]


def test_normalize_hotspot_residues_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Proteina format"):
        _normalize_hotspot_residues(["nonsense"])


def test_warm_start_payload_requires_chain_for_multi_chain_cif(tmp_path: Path) -> None:
    cif_path = tmp_path / "complex.cif"
    cif_path.write_text(
        "data_complex\n"
        "loop_\n"
        "_atom_site.group_PDB\n"
        "_atom_site.label_asym_id\n"
        "_atom_site.auth_asym_id\n"
        "_atom_site.label_comp_id\n"
        "_atom_site.auth_comp_id\n"
        "_atom_site.label_seq_id\n"
        "_atom_site.auth_seq_id\n"
        "_atom_site.label_atom_id\n"
        "_atom_site.auth_atom_id\n"
        "_atom_site.pdbx_PDB_ins_code\n"
        "ATOM A A ALA ALA 1 1 CA CA .\n"
        "ATOM B B ALA ALA 1 1 CA CA .\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="multiple chains"):
        _warm_start_payload_from_file(cif_path, None)


def test_warm_start_payload_defaults_to_last_chain_for_pdb(tmp_path: Path) -> None:
    pdb_path = tmp_path / "complex.pdb"
    pdb_path.write_text(_two_chain_pdb(), encoding="utf-8")

    payload = _warm_start_payload_from_file(pdb_path, None)

    # Two-chain PDB without an explicit chain → fall back to the last chain (B).
    assert payload["chain"] == "B"
    assert payload["filename"] == "complex.pdb"


def test_warm_start_payload_validates_requested_chain(tmp_path: Path) -> None:
    pdb_path = tmp_path / "complex.pdb"
    pdb_path.write_text(_two_chain_pdb(), encoding="utf-8")

    with pytest.raises(ValueError, match="not found"):
        _warm_start_payload_from_file(pdb_path, "Z")
