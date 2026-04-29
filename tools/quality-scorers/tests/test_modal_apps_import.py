from __future__ import annotations

import importlib
import io
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeImage:
    def apt_install(self, *args, **kwargs):
        return self

    def pip_install(self, *args, **kwargs):
        return self

    def env(self, *args, **kwargs):
        return self

    def add_local_python_source(self, *args, **kwargs):
        return self


class _FakeVolume:
    @classmethod
    def from_name(cls, *args, **kwargs):
        return cls()

    def read_only(self):
        return self

    def commit(self):
        return None

    def reload(self):
        return None


class _FakeSecret:
    @classmethod
    def from_name(cls, *args, **kwargs):
        return cls()


class _FakeApp:
    def __init__(self, *args, **kwargs):
        pass

    def function(self, *args, **kwargs):
        def decorator(function):
            return function

        return decorator

    def local_entrypoint(self, *args, **kwargs):
        def decorator(function):
            return function

        return decorator


def _install_fake_modal() -> None:
    sys.modules["modal"] = types.SimpleNamespace(
        App=_FakeApp,
        Image=types.SimpleNamespace(from_registry=lambda *args, **kwargs: _FakeImage()),
        Secret=_FakeSecret,
        Volume=_FakeVolume,
        asgi_app=lambda *args, **kwargs: (lambda function: function),
    )


class ModalAppImportTests(unittest.TestCase):
    def test_embedding_and_training_apps_import_with_fake_modal(self) -> None:
        _install_fake_modal()
        for module_name in ("esm2_embedding_app", "head_training_app", "inference_modal_app"):
            sys.modules.pop(module_name, None)
            module = importlib.import_module(module_name)
            self.assertTrue(hasattr(module, "app"))

    def test_inference_fasta_parser_accepts_one_record(self) -> None:
        _install_fake_modal()
        sys.modules.pop("inference_modal_app", None)
        module = importlib.import_module("inference_modal_app")

        parsed = module._parse_single_fasta(">candidate A\nACD\nEFG\n")

        self.assertEqual(parsed.name, "candidate A")
        self.assertEqual(parsed.sequence, "ACDEFG")

    def test_inference_fasta_parser_rejects_bad_inputs(self) -> None:
        _install_fake_modal()
        sys.modules.pop("inference_modal_app", None)
        module = importlib.import_module("inference_modal_app")

        with self.assertRaisesRegex(ValueError, "must start"):
            module._parse_single_fasta("ACDE")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            module._parse_single_fasta(">a\nACD\n>b\nEFG\n")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            module._parse_single_fasta(">a\nACDX\n")

    def test_inference_hla_alias_resolution_matches_panel_formats(self) -> None:
        _install_fake_modal()
        sys.modules.pop("inference_modal_app", None)
        module = importlib.import_module("inference_modal_app")

        self.assertEqual(module.allele_alias_key("HLA-A*02:01"), module.allele_alias_key("HLA-A02:01"))
        self.assertEqual(
            module.allele_alias_key("HLA-DPA1*01:03/DPB1*02:01"),
            module.allele_alias_key("HLA-DPA10103-DPB10201"),
        )

    def test_inference_sliding_windows_handles_short_sequences(self) -> None:
        _install_fake_modal()
        sys.modules.pop("inference_modal_app", None)
        module = importlib.import_module("inference_modal_app")

        self.assertEqual(list(module._sliding_windows("ABCDE", (6,))), [])
        self.assertEqual(
            list(module._sliding_windows("ABCDEFG", (6,))),
            [(0, 6, "ABCDEF"), (1, 7, "BCDEFG")],
        )

    def test_inference_hla_aggregation_formula(self) -> None:
        _install_fake_modal()
        sys.modules.pop("inference_modal_app", None)
        module = importlib.import_module("inference_modal_app")

        scores = [0.1, 0.9, 0.8, 0.7]
        expected = 0.5 * 0.9 + 0.3 * sum(scores) / 4 + 0.2 * 0.2

        self.assertAlmostEqual(
            module._aggregate_hla_scores(scores),
            expected,
        )

    def test_safe_extract_rejects_tar_symlinks(self) -> None:
        _install_fake_modal()
        sys.modules.pop("esm2_embedding_app", None)
        module = importlib.import_module("esm2_embedding_app")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tar_path = root / "bad.tar"
            with tarfile.open(tar_path, "w") as archive:
                info = tarfile.TarInfo("outside-link")
                info.type = tarfile.SYMTYPE
                info.linkname = "../outside"
                archive.addfile(info)

            with self.assertRaisesRegex(ValueError, "Unsafe tar member type"):
                module._safe_extract_tarball(tar_path, root / "extract")

    def test_safe_extract_rejects_tar_hardlinks(self) -> None:
        _install_fake_modal()
        sys.modules.pop("esm2_embedding_app", None)
        module = importlib.import_module("esm2_embedding_app")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tar_path = root / "bad.tar"
            with tarfile.open(tar_path, "w") as archive:
                payload = b"ok"
                good = tarfile.TarInfo("good.txt")
                good.size = len(payload)
                archive.addfile(good, io.BytesIO(payload))

                hardlink = tarfile.TarInfo("hardlink")
                hardlink.type = tarfile.LNKTYPE
                hardlink.linkname = "good.txt"
                archive.addfile(hardlink)

            with self.assertRaisesRegex(ValueError, "Unsafe tar member type"):
                module._safe_extract_tarball(tar_path, root / "extract")

    @unittest.skipIf(
        importlib.util.find_spec("numpy") is None or importlib.util.find_spec("pandas") is None,
        "numpy/pandas are not installed locally",
    )
    def test_hla_limit_compacts_embedding_matrices(self) -> None:
        import numpy as np
        import pandas as pd

        _install_fake_modal()
        sys.modules.pop("head_training_app", None)
        module = importlib.import_module("head_training_app")

        pairs = pd.DataFrame(
            {
                "split": ["train", "valid", "test"],
                "peptide_idx": [5, 7, 5],
                "hla_idx": [2, 3, 2],
                "target": [1.0, 0.0, 1.0],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            peptide_path = root / "peptides.npy"
            hla_path = root / "hla.npy"
            np.save(peptide_path, np.arange(20, dtype=np.float32).reshape(10, 2))
            np.save(hla_path, np.arange(12, dtype=np.float32).reshape(6, 2))

            compact_pairs, peptide_embeddings, hla_embeddings = module._subset_hla_embeddings_for_pairs(
                pairs,
                peptide_path,
                hla_path,
            )

        self.assertEqual(compact_pairs["peptide_idx"].tolist(), [0, 1, 0])
        self.assertEqual(compact_pairs["hla_idx"].tolist(), [0, 1, 0])
        self.assertTrue(np.array_equal(peptide_embeddings, np.array([[10, 11], [14, 15]], dtype=np.float32)))
        self.assertTrue(np.array_equal(hla_embeddings, np.array([[4, 5], [6, 7]], dtype=np.float32)))

    @unittest.skipIf(
        importlib.util.find_spec("numpy") is None
        or importlib.util.find_spec("pandas") is None
        or importlib.util.find_spec("sklearn") is None,
        "numpy/pandas/sklearn are not installed locally",
    )
    def test_apr_training_uses_hex1279_validation_and_hex142_test(self) -> None:
        import numpy as np
        import pandas as pd

        _install_fake_modal()
        sys.modules.pop("head_training_app", None)
        module = importlib.import_module("head_training_app")

        table = pd.DataFrame(
            {
                "split": ["train"] * 10 + ["test"] * 4,
                "label": [0, 1] * 5 + [0, 1, 0, 1],
            }
        )
        matrix = np.arange(14 * 2, dtype=np.float32).reshape(14, 2)
        captured = {}

        def fake_train_head(**kwargs):
            captured["train_rows"] = int(kwargs["train_x"].shape[0])
            captured["valid_rows"] = int(kwargs["valid_x"].shape[0])
            captured["test_rows"] = int(kwargs["test_x"].shape[0])
            captured["valid_values"] = kwargs["valid_x"].copy()
            captured["test_values"] = kwargs["test_x"].copy()
            return {
                "artifact_path": str(kwargs["artifact_path"]),
                "metrics": {},
                "train_rows": captured["train_rows"],
                "valid_rows": captured["valid_rows"],
                "test_rows": captured["test_rows"],
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module._load_embedding_artifacts = lambda _model_id, _dataset: (table, matrix)
            module.train_sklearn_logistic_head = fake_train_head
            module.head_model_dir = lambda _model_id: root
            module.embedding_model_dir = lambda _model_id: root
            module.write_json = lambda *_args, **_kwargs: None

            module._train_apr_impl("model")

        self.assertEqual(captured["train_rows"], 8)
        self.assertEqual(captured["valid_rows"], 2)
        self.assertEqual(captured["test_rows"], 4)
        self.assertFalse(np.array_equal(captured["valid_values"], captured["test_values"][:2]))


if __name__ == "__main__":
    unittest.main()
