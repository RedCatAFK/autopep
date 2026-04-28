from __future__ import annotations

import argparse
import importlib
import sys
import types
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
