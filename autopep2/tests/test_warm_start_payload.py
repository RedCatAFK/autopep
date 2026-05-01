from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


SINGLE_CHAIN_CIF = """\
data_seed
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.auth_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
ATOM 1 C CA SER A 1 ? 0.000 0.000 0.000 CA SER A 1
#
"""

MULTI_CHAIN_CIF = """\
data_seed
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.auth_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
ATOM 1 C CA SER A 1 ? 0.000 0.000 0.000 CA SER A 1
ATOM 2 C CA GLY B 1 ? 1.000 0.000 0.000 CA GLY B 1
#
"""


def _atom_line(serial: int, residue: str, chain: str, number: int) -> str:
    return (
        f"ATOM  {serial:5d}  CA  {residue:>3} {chain}{number:4d}"
        "      11.104  13.207  14.329  1.00 20.00           C"
    )


def test_single_chain_cif_omits_inferred_warm_start_chain(tmp_path) -> None:
    seed = tmp_path / "7VFA_nanobody_A.cif"
    seed.write_text(SINGLE_CHAIN_CIF, encoding="utf-8")

    payload = main._warm_start_payload_from_file(seed)

    assert payload["filename"] == "7VFA_nanobody_A.cif"
    assert "chain" not in payload


def test_single_chain_cif_allows_explicit_valid_chain(tmp_path) -> None:
    seed = tmp_path / "seed.cif"
    seed.write_text(SINGLE_CHAIN_CIF, encoding="utf-8")

    payload = main._warm_start_payload_from_file(seed, "A")

    assert payload["chain"] == "A"


def test_single_chain_cif_rejects_explicit_invalid_chain(tmp_path) -> None:
    seed = tmp_path / "seed.cif"
    seed.write_text(SINGLE_CHAIN_CIF, encoding="utf-8")

    with pytest.raises(ValueError, match=r"warm_start_chain 'S'.*Available chains: \['A'\]"):
        main._warm_start_payload_from_file(seed, "S")


def test_multi_chain_cif_requires_explicit_chain(tmp_path) -> None:
    seed = tmp_path / "seed.cif"
    seed.write_text(MULTI_CHAIN_CIF, encoding="utf-8")

    with pytest.raises(ValueError, match=r"multiple chains \['A', 'B'\]"):
        main._warm_start_payload_from_file(seed)


def test_multi_chain_cif_sends_explicit_chain(tmp_path) -> None:
    seed = tmp_path / "seed.cif"
    seed.write_text(MULTI_CHAIN_CIF, encoding="utf-8")

    payload = main._warm_start_payload_from_file(seed, "B")

    assert payload["chain"] == "B"


def test_multi_chain_pdb_keeps_last_chain_fallback(tmp_path) -> None:
    seed = tmp_path / "seed.pdb"
    seed.write_text(
        "\n".join(
            [
                _atom_line(1, "ALA", "A", 1),
                _atom_line(2, "GLY", "B", 1),
                _atom_line(3, "SER", "C", 1),
            ]
        ),
        encoding="utf-8",
    )

    payload = main._warm_start_payload_from_file(seed)

    assert payload["chain"] == "C"


def test_target_input_inference_splits_gappy_pdb_ranges(tmp_path) -> None:
    target = tmp_path / "target.pdb"
    structure = "\n".join(
        [
            _atom_line(1, "ALA", "A", 1),
            _atom_line(2, "ALA", "A", 2),
            _atom_line(3, "ALA", "A", 4),
        ]
    )
    target.write_text(structure, encoding="utf-8")

    target_input, guard = main._normalize_target_input_for_structure(
        None,
        target,
        structure,
    )

    assert target_input == "A1-2,A4-4"
    assert guard["status"] == "inferred"


def test_target_input_correction_intersects_requested_range_with_available_residues(tmp_path) -> None:
    target = tmp_path / "target.pdb"
    structure = "\n".join(
        [
            _atom_line(1, "ALA", "A", 3),
            _atom_line(2, "ALA", "A", 4),
            _atom_line(3, "ALA", "A", 6),
        ]
    )
    target.write_text(structure, encoding="utf-8")

    target_input, guard = main._normalize_target_input_for_structure(
        "A1-6",
        target,
        structure,
    )

    assert target_input == "A3-4,A6-6"
    assert guard["status"] == "corrected"
    assert guard["missing_residues"] == {"A": [1, 2, 5]}


def test_hotspot_validation_rejects_absent_target_residue(tmp_path) -> None:
    target = tmp_path / "target.pdb"
    structure = _atom_line(1, "ALA", "A", 3)
    target.write_text(structure, encoding="utf-8")

    with pytest.raises(ValueError, match="hotspot_residue 'A1' is not present"):
        main._validate_hotspots_for_structure(["A1"], target, structure)
