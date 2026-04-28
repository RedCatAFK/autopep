from __future__ import annotations

import unittest

from preprocessing import preprocess_cif_text, sanitize_name


SAMPLE_CIF = """\
data_sample
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
ATOM 1 N N MET A 1 ? 11.104 13.207 9.417 N MET A 1
ATOM 2 C CA MET A 1 ? 12.560 13.371 9.397 CA MET A 1
ATOM 3 C C MET A 1 ? 13.051 14.517 10.287 C MET A 1
ATOM 4 N N GLY A 2 ? 14.365 14.666 10.337 N GLY A 2
ATOM 5 C CA GLY A 2 ? 14.955 15.735 11.137 CA GLY A 2
ATOM 6 N N LYS B 5 ? 18.001 10.002 5.003 N LYS B 5
ATOM 7 C CA LYS B 5 ? 19.111 10.222 5.333 CA LYS B 5
#
"""


class PreprocessingTests(unittest.TestCase):
    def test_extracts_sequences_and_features_from_cif(self) -> None:
        result = preprocess_cif_text(SAMPLE_CIF, structure_id="sample")
        self.assertEqual(result.sequence, "MG:K")
        self.assertEqual(result.chain_sequences, {"A": "MG", "B": "K"})
        self.assertEqual(result.target_input, "A1-2,B5-5")

        features = result.model_feature_dict()
        self.assertEqual(features["residue_type"], [12, 7, 11])
        self.assertEqual(features["ca_coords_nm"][0], [1.256, 1.3371, 0.9397])
        self.assertEqual(features["coord_mask"], [True, True, True])
        self.assertEqual(len(features["sequence_one_hot"][0]), 20)

    def test_chain_filter(self) -> None:
        result = preprocess_cif_text(SAMPLE_CIF, structure_id="sample", chains="B")
        self.assertEqual(result.sequence, "K")
        self.assertEqual(result.target_input, "B5-5")

    def test_sanitize_name(self) -> None:
        self.assertEqual(sanitize_name("6m0j target.cif"), "target_6m0j_target_cif")


if __name__ == "__main__":
    unittest.main()
