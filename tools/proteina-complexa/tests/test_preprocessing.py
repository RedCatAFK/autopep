from __future__ import annotations

import unittest

from preprocessing import preprocess_pdb_text, sanitize_name


SAMPLE_PDB = """\
ATOM      1  N   MET A   1      11.104  13.207   9.417  1.00 20.00           N
ATOM      2  CA  MET A   1      12.560  13.371   9.397  1.00 20.00           C
ATOM      3  C   MET A   1      13.051  14.517  10.287  1.00 20.00           C
ATOM      4  N   GLY A   2      14.365  14.666  10.337  1.00 20.00           N
ATOM      5  CA  GLY A   2      14.955  15.735  11.137  1.00 20.00           C
ATOM      6  N   LYS B   5      18.001  10.002   5.003  1.00 20.00           N
ATOM      7  CA  LYS B   5      19.111  10.222   5.333  1.00 20.00           C
TER
END
"""


class PreprocessingTests(unittest.TestCase):
    def test_extracts_sequences_and_features(self) -> None:
        result = preprocess_pdb_text(SAMPLE_PDB, pdb_id="sample")
        self.assertEqual(result.sequence, "MG:K")
        self.assertEqual(result.chain_sequences, {"A": "MG", "B": "K"})
        self.assertEqual(result.target_input, "A1-2,B5-5")

        features = result.model_feature_dict()
        self.assertEqual(features["residue_type"], [12, 7, 11])
        self.assertEqual(features["ca_coords_nm"][0], [1.256, 1.3371, 0.9397])
        self.assertEqual(features["coord_mask"], [True, True, True])
        self.assertEqual(len(features["sequence_one_hot"][0]), 20)

    def test_chain_filter(self) -> None:
        result = preprocess_pdb_text(SAMPLE_PDB, pdb_id="sample", chains="B")
        self.assertEqual(result.sequence, "K")
        self.assertEqual(result.target_input, "B5-5")

    def test_sanitize_name(self) -> None:
        self.assertEqual(sanitize_name("6m0j target.pdb"), "target_6m0j_target_pdb")


if __name__ == "__main__":
    unittest.main()
