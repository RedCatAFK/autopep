from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from structure_vis.cli import main
from structure_vis.pipeline import compare_structures, html_structures


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_view_writes_pymol_script_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            result = main(
                [
                    "view",
                    str(ROOT / "examples" / "reference.pdb"),
                    str(ROOT / "examples" / "model_shifted.pdb"),
                    "--out-dir",
                    str(tmp_path),
                ]
            )

            self.assertEqual(result, 0)
            pml = (tmp_path / "view.pml").read_text(encoding="utf-8")
            manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("load ", pml)
            self.assertIn("group loaded_structures", pml)
            self.assertEqual(manifest["command"], "view")
            self.assertEqual(len(manifest["inputs"]), 2)

    def test_compare_writes_diff_scene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            result = main(
                [
                    "compare",
                    str(ROOT / "examples" / "reference.pdb"),
                    str(ROOT / "examples" / "model_shifted.pdb"),
                    "--distance-cutoff",
                    "0.5",
                    "--out-dir",
                    str(tmp_path),
                ]
            )

            self.assertEqual(result, 0)
            pml = (tmp_path / "compare.pml").read_text(encoding="utf-8")
            manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("super mobile_02_model_shifted", pml)
            self.assertIn("cmd.spectrum", pml)
            self.assertIn("diff_distances", pml)
            self.assertEqual(manifest["command"], "compare")
            self.assertEqual(manifest["metadata"]["distance_cutoff"], 0.5)

    def test_html_writes_embedded_browser_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            result = main(
                [
                    "html",
                    str(ROOT / "examples" / "reference.pdb"),
                    str(ROOT / "examples" / "model_shifted.pdb"),
                    "--compare",
                    "--out-dir",
                    str(tmp_path),
                ]
            )

            self.assertEqual(result, 0)
            document = (tmp_path / "viewer.html").read_text(encoding="utf-8")
            manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("3Dmol-min.js", document)
            self.assertIn("reference.pdb", document)
            self.assertEqual(manifest["command"], "html")
            self.assertTrue(manifest["metadata"]["compare"])

    def test_direct_api_writes_compare_scene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            scene = compare_structures(
                ROOT / "examples" / "reference.pdb",
                ROOT / "examples" / "model_shifted.pdb",
                out_dir=tmp_path,
                distance_cutoff=0.75,
            )

            self.assertEqual(scene.scene_path.name, "compare.pml")
            self.assertEqual(scene.scene_path.parent, tmp_path.resolve())
            self.assertFalse(scene.opened)
            self.assertIn("distance_cutoff", scene.manifest_path.read_text(encoding="utf-8"))

    def test_direct_api_writes_html_scene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            scene = html_structures(
                [
                    ROOT / "examples" / "reference.pdb",
                    ROOT / "examples" / "model_shifted.pdb",
                ],
                compare=True,
                out_dir=tmp_path,
            )

            self.assertEqual(scene.scene_path.name, "viewer.html")
            self.assertEqual(scene.scene_path.parent, tmp_path.resolve())
            self.assertIn("3Dmol-min.js", scene.scene_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
