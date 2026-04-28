from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class _FakeImage:
    def apt_install(self, *args, **kwargs):
        return self

    def run_commands(self, *args, **kwargs):
        return self

    def env(self, *args, **kwargs):
        return self

    def workdir(self, *args, **kwargs):
        return self

    def add_local_python_source(self, *args, **kwargs):
        return self


class _FakeVolume:
    @classmethod
    def from_name(cls, *args, **kwargs):
        return cls()

    def read_only(self):
        return self

    def reload(self):
        return None

    def commit(self):
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
    fake_modal = types.SimpleNamespace(
        App=_FakeApp,
        Image=types.SimpleNamespace(from_registry=lambda *args, **kwargs: _FakeImage()),
        Secret=_FakeSecret,
        Volume=_FakeVolume,
    )
    sys.modules["modal"] = fake_modal


def _import_modal_app():
    module_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(module_dir))
    sys.modules.pop("modal_app", None)
    _install_fake_modal()
    return importlib.import_module("modal_app")


modal_app = _import_modal_app()


class DesignCommandTests(unittest.TestCase):
    def test_steps_are_appended_after_hydra_overrides(self) -> None:
        command = modal_app._design_command(
            task_name="target_102L",
            run_name="smoke_run",
            pipeline_config=modal_app.DEFAULT_PIPELINE_CONFIG,
            overrides=["++generation.args.nsteps=20"],
            steps=["generate"],
        )

        self.assertEqual(command[-2:], ["--steps", "generate"])
        step_index = command.index("--steps")
        self.assertLess(command.index("++ckpt_path=/models/protein-target-160m"), step_index)
        self.assertLess(command.index("++generation.args.nsteps=20"), step_index)

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--steps",
            nargs="+",
            choices=["generate", "filter", "evaluate", "analyze"],
        )
        parser.add_argument("config")
        parser.add_argument("overrides", nargs="*")

        parsed = parser.parse_args(command[2:])
        self.assertEqual(parsed.steps, ["generate"])
        self.assertIn("++ckpt_path=/models/protein-target-160m", parsed.overrides)
        self.assertIn("++generation.args.nsteps=20", parsed.overrides)

    def test_no_steps_omits_steps_flag(self) -> None:
        command = modal_app._design_command(
            task_name="target_102L",
            run_name="full_run",
            pipeline_config=modal_app.DEFAULT_PIPELINE_CONFIG,
            overrides=[],
            steps=[],
        )

        self.assertNotIn("--steps", command)

    def test_invalid_steps_are_rejected_before_remote_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid design steps"):
            modal_app._design_command(
                task_name="target_102L",
                run_name="bad_run",
                pipeline_config=modal_app.DEFAULT_PIPELINE_CONFIG,
                overrides=[],
                steps=["++ckpt_path=/models/protein-target-160m"],
            )

    def test_target_overrides_point_at_complexa_target_pdb(self) -> None:
        target_path = modal_app.TARGET_DATA_DIR / "target_102L.pdb"
        overrides = modal_app._target_overrides(
            target_name="target_102L",
            target_path=target_path,
            target_input="A1-162",
            hotspot_residues=["A40"],
            binder_length=[60, 120],
            pdb_id="target_102L",
        )

        self.assertIn(
            "++generation.target_dict_cfg.target_102L.source=preprocessed_targets",
            overrides,
        )
        self.assertIn(
            "++generation.target_dict_cfg.target_102L.target_filename=target_102L",
            overrides,
        )
        self.assertIn(
            "++generation.target_dict_cfg.target_102L.target_path=/data/target_data/preprocessed_targets/target_102L.pdb",
            overrides,
        )

    def test_resolve_design_overrides_hydrates_preprocessed_target_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preprocess_dir = root / "preprocessed_targets"
            target_dir = root / "target_data" / "preprocessed_targets"
            preprocess_dir.mkdir(parents=True)
            target_dir.mkdir(parents=True)
            pdb_path = target_dir / "target_custom.pdb"
            pdb_path.write_text("ATOM\n")
            (preprocess_dir / "target_custom.target.json").write_text(
                json.dumps(
                    {
                        "target_name": "target_custom",
                        "target_path": str(pdb_path),
                        "target_input": "A1-20,B5-9",
                        "hotspot_residues": ["A10"],
                        "binder_length": [70, 90],
                        "pdb_id": "target_custom",
                    }
                )
            )

            with (
                mock.patch.object(modal_app, "PREPROCESS_DIR", preprocess_dir),
                mock.patch.object(modal_app, "TARGET_DATA_DIR", target_dir),
            ):
                overrides = modal_app._resolve_design_overrides(
                    "target_custom",
                    ["++generation.args.nsteps=20"],
                )

        self.assertIn(
            "++generation.target_dict_cfg.target_custom.target_path=" + str(pdb_path),
            overrides,
        )
        self.assertIn(
            '++generation.target_dict_cfg.target_custom.target_input="A1-20,B5-9"',
            overrides,
        )
        self.assertIn(
            '++generation.target_dict_cfg.target_custom.hotspot_residues=["A10"]',
            overrides,
        )
        self.assertIn(
            "++generation.target_dict_cfg.target_custom.binder_length=[70,90]",
            overrides,
        )
        self.assertEqual(overrides[-1], "++generation.args.nsteps=20")

    def test_resolve_design_overrides_uses_legacy_preprocess_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preprocess_dir = root / "preprocessed_targets"
            target_dir = root / "target_data" / "preprocessed_targets"
            preprocess_dir.mkdir(parents=True)
            target_dir.mkdir(parents=True)
            (target_dir / "target_legacy.pdb").write_text("ATOM\n")
            (preprocess_dir / "target_legacy.preprocess.json").write_text(
                json.dumps({"target_input": "A1-10"})
            )

            with (
                mock.patch.object(modal_app, "PREPROCESS_DIR", preprocess_dir),
                mock.patch.object(modal_app, "TARGET_DATA_DIR", target_dir),
            ):
                overrides = modal_app._resolve_design_overrides("target_legacy", [])

        self.assertIn(
            "++generation.target_dict_cfg.target_legacy.target_path="
            + str(target_dir / "target_legacy.pdb"),
            overrides,
        )
        self.assertIn(
            "++generation.target_dict_cfg.target_legacy.binder_length=[60,120]",
            overrides,
        )

    def test_partial_target_overrides_fail_early_without_preprocessed_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            modal_app._resolve_design_overrides(
                "target_custom",
                ["++generation.target_dict_cfg.target_custom.target_input=A1-20"],
            )

    def test_run_output_overrides_keep_outputs_on_runs_volume(self) -> None:
        overrides = modal_app._run_output_overrides(
            task_name="target_102L",
            run_name="smoke_run",
            pipeline_config=modal_app.DEFAULT_PIPELINE_CONFIG,
        )

        self.assertIn(
            "++root_path=/runs/smoke_run/inference/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )
        self.assertIn(
            "++sample_storage_path=/runs/smoke_run/inference/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )
        self.assertIn(
            "++output_dir=/runs/smoke_run/evaluation_results/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )
        self.assertIn(
            "++results_dir=/runs/smoke_run/evaluation_results/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )
        self.assertTrue(any(override.startswith("++hydra.run.dir=/runs/smoke_run/logs/") for override in overrides))

    def test_design_binder_runs_from_complexa_root_with_persisted_output_paths(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(modal_app, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(modal_app, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(modal_app, "_run_complexa", fake_run),
            mock.patch.object(modal_app, "_target_overrides_from_preprocessed_config", return_value=[]),
        ):
            result = modal_app.design_binder(
                task_name="02_PDL1",
                run_name="pdl1_smoke",
                overrides=["++generation.args.nsteps=20"],
                steps=["generate"],
            )

        self.assertEqual(result["log_tail"], "ok")
        self.assertEqual(calls[0][1], Path(tmp) / "complexa")
        command = calls[0][0]
        self.assertIn(
            f"++root_path={Path(tmp) / 'runs' / 'pdl1_smoke' / 'inference' / 'search_binder_local_pipeline_02_PDL1_pdl1_smoke'}",
            command,
        )
        self.assertIn("++generation.args.nsteps=20", command)


if __name__ == "__main__":
    unittest.main()
