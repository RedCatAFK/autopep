from __future__ import annotations

import base64

from autopep_agent import structure_utils
from autopep_agent.structure_utils import (
    build_fasta,
    encode_structure_base64,
    extract_cif_chain_order,
    extract_pdb_sequences,
    extract_structure_chain_order,
)


SAMPLE_CIF = """\
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


def _atom_line(
    serial: int,
    atom: str,
    residue: str,
    chain: str,
    number: int,
    insertion_code: str = " ",
) -> str:
    return (
        f"ATOM  {serial:5d} {atom:<4} {residue:>3} {chain}{number:4d}{insertion_code:1s}"
        "      11.104  13.207  14.329  1.00 20.00           C"
    )


def test_extract_pdb_sequences_dedupes_atoms_by_chain_and_residue() -> None:
    pdb_text = "\n".join(
        [
            _atom_line(1, "N", "ALA", "A", 1),
            _atom_line(2, "CA", "ALA", "A", 1),
            _atom_line(3, "N", "GLY", "B", 2),
            _atom_line(4, "CA", "GLY", "B", 2),
        ],
    )

    assert extract_pdb_sequences(pdb_text) == {"A": "A", "B": "G"}


def test_extract_pdb_sequences_keeps_insertion_code_residues() -> None:
    pdb_text = "\n".join(
        [
            _atom_line(1, "N", "ALA", "A", 42),
            _atom_line(2, "CA", "ALA", "A", 42),
            _atom_line(3, "N", "GLY", "A", 42, "A"),
            _atom_line(4, "CA", "GLY", "A", 42, "A"),
        ],
    )

    assert extract_pdb_sequences(pdb_text) == {"A": "AG"}


def test_extract_cif_chain_order_reads_atom_site_auth_chain_ids() -> None:
    assert extract_cif_chain_order(SAMPLE_CIF) == ["A", "B"]


def test_extract_structure_chain_order_uses_cif_parser_for_cif_filename() -> None:
    structure_format, chains = extract_structure_chain_order(
        SAMPLE_CIF,
        filename="7VFA_nanobody_A.cif",
    )

    assert structure_format == "cif"
    assert chains == ["A", "B"]
    assert "S" not in chains


def test_build_fasta_formats_candidate_ids_and_sequences() -> None:
    assert build_fasta([{"id": "candidate-1", "sequence": "ACDE"}]) == (
        ">protein|name=candidate-1\nACDE\n"
    )


def test_build_complex_fasta_formats_target_then_binder() -> None:
    assert hasattr(structure_utils, "build_complex_fasta")
    assert structure_utils.build_complex_fasta(
        target_id="target",
        target_sequence=" aa ",
        binder_id="candidate-1",
        binder_sequence=" gg ",
    ) == ">protein|name=target\nAA\n>protein|name=candidate-1\nGG\n"


def test_encode_structure_base64_encodes_utf8_text() -> None:
    encoded = encode_structure_base64("ATOM\n")

    assert base64.b64decode(encoded.encode("ascii")) == b"ATOM\n"
