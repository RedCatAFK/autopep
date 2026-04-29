from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from proteina_complexa.http_smoke_payload import build_http_smoke_payload
from proteina_complexa.preprocess_structure import preprocess_structure_summary
from proteina_complexa.preprocessing import preprocess_cif_text, sanitize_name


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

    def test_preprocess_structure_summary_preserves_script_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cif_path = tmp_path / "102L.cif"
            output_dir = tmp_path / "preprocessed"
            cif_path.write_text(SAMPLE_CIF)

            summary = preprocess_structure_summary(
                cif_path,
                target_name="target_102L",
                target_input="A1-2",
                output_dir=output_dir,
            )

            self.assertEqual(summary["target_name"], "target_102L")
            self.assertEqual(summary["length"], 3)
            self.assertEqual(summary["target_input"], "A1-2")
            self.assertIn("++generation.task_name=target_102L", summary["hydra_overrides"])
            self.assertTrue(Path(summary["outputs"]["json"]).is_file())
            self.assertTrue(Path(summary["outputs"]["fasta"]).is_file())

    def test_http_smoke_payload_reads_target_and_gzipped_seed_binders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target_path = tmp_path / "target.cif"
            seed_path = tmp_path / "seed.cif.gz"
            target_path.write_text(SAMPLE_CIF)
            with gzip.open(seed_path, "wt") as handle:
                handle.write(SAMPLE_CIF)

            payload = build_http_smoke_payload(
                target_cif=target_path,
                seed_binders=[seed_path],
                target_name="target_102L",
                target_input="A1-162",
                binder_length=[60, 120],
                hotspot_residues=[],
                seed_binder_chain="B",
                seed_binder_noise_level=0.5,
                run_name="target_102L_http_warm_test",
            )

        self.assertEqual(payload["action"], "smoke-cif")
        self.assertEqual(payload["target"]["filename"], "target.cif")
        self.assertEqual(payload["warm_start"][0]["filename"], "seed.cif")
        self.assertEqual(payload["warm_start"][0]["chain"], "B")
        self.assertIn("data_sample", payload["target"]["structure"])


if __name__ == "__main__":
    unittest.main()
