from __future__ import annotations

import base64

from autopep_agent.structure_utils import (
    build_fasta,
    encode_structure_base64,
    extract_pdb_sequences,
)


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


def test_build_fasta_formats_candidate_ids_and_sequences() -> None:
    assert build_fasta([{"id": "candidate-1", "sequence": "ACDE"}]) == (
        ">protein|name=candidate-1\nACDE\n"
    )


def test_encode_structure_base64_encodes_utf8_text() -> None:
    encoded = encode_structure_base64("ATOM\n")

    assert base64.b64decode(encoded.encode("ascii")) == b"ATOM\n"
