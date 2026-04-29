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
    def __init__(self):
        self.calls = []

    def apt_install(self, *args, **kwargs):
        self.calls.append(("apt_install", args, kwargs))
        return self

    def run_commands(self, *args, **kwargs):
        self.calls.append(("run_commands", args, kwargs))
        return self

    def pip_install(self, *args, **kwargs):
        self.calls.append(("pip_install", args, kwargs))
        return self

    def env(self, *args, **kwargs):
        self.calls.append(("env", args, kwargs))
        return self

    def workdir(self, *args, **kwargs):
        self.calls.append(("workdir", args, kwargs))
        return self

    def add_local_python_source(self, *args, **kwargs):
        self.calls.append(("add_local_python_source", args, kwargs))
        return self

    def add_local_file(self, *args, **kwargs):
        self.calls.append(("add_local_file", args, kwargs))
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


def _install_fake_modal() -> None:
    fake_modal = types.SimpleNamespace(
        App=_FakeApp,
        Image=types.SimpleNamespace(from_registry=lambda *args, **kwargs: _FakeImage()),
        Secret=_FakeSecret,
        Volume=_FakeVolume,
        asgi_app=lambda *args, **kwargs: (lambda function: function),
    )
    sys.modules["modal"] = fake_modal


def _import_modules():
    module_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(module_dir))
    _install_fake_modal()
    for name in list(sys.modules):
        if name == "modal_app" or name.startswith("proteina_complexa."):
            sys.modules.pop(name, None)
    return {
        "commands": importlib.import_module("proteina_complexa.commands"),
        "design": importlib.import_module("proteina_complexa.design"),
        "http_server": importlib.import_module("proteina_complexa.http_server"),
        "target_preprocessing": importlib.import_module("proteina_complexa.target_preprocessing"),
        "warm_start": importlib.import_module("proteina_complexa.warm_start"),
    }


modules = _import_modules()
commands = modules["commands"]
design = modules["design"]
http_server = modules["http_server"]
target_preprocessing = modules["target_preprocessing"]
warm_start = modules["warm_start"]


class DesignCommandTests(unittest.TestCase):
    def test_modal_app_entrypoint_imports_thin_asgi_app(self) -> None:
        sys.modules.pop("modal_app", None)
        modal_app = importlib.import_module("modal_app")

        self.assertTrue(callable(modal_app.fastapi_app))

    def test_modal_image_clones_configured_fork_without_patch_upload(self) -> None:
        config = importlib.import_module("proteina_complexa.config")
        modal_resources = importlib.import_module("proteina_complexa.modal_resources")
        image_calls = modal_resources.image.calls
        run_commands = [
            command
            for method_name, args, _kwargs in image_calls
            if method_name == "run_commands"
            for command in args
        ]

        self.assertTrue(
            any(
                config.COMPLEXA_REPO_URL in command
                and f"--branch {config.COMPLEXA_REPO_REF}" in command
                for command in run_commands
            )
        )
        self.assertTrue(
            any("Proteina warm-start hooks: present in forked source" in command for command in run_commands)
        )
        self.assertFalse(any(method_name == "add_local_file" for method_name, _args, _kwargs in image_calls))
        self.assertFalse(any("git apply" in command for command in run_commands))
        self.assertFalse(any("proteina-warm-start.patch" in command for command in run_commands))

    def test_steps_are_appended_after_hydra_overrides(self) -> None:
        command = commands.design_command(
            task_name="target_102L",
            run_name="smoke_run",
            pipeline_config=commands.DEFAULT_PIPELINE_CONFIG,
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
        command = commands.design_command(
            task_name="target_102L",
            run_name="full_run",
            pipeline_config=commands.DEFAULT_PIPELINE_CONFIG,
            overrides=[],
            steps=[],
        )

        self.assertNotIn("--steps", command)

    def test_invalid_steps_are_rejected_before_remote_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid design steps"):
            commands.design_command(
                task_name="target_102L",
                run_name="bad_run",
                pipeline_config=commands.DEFAULT_PIPELINE_CONFIG,
                overrides=[],
                steps=["++ckpt_path=/models/protein-target-160m"],
            )

    def test_target_overrides_point_at_complexa_target_pdb(self) -> None:
        target_path = target_preprocessing.TARGET_DATA_DIR / "target_102L.pdb"
        overrides = target_preprocessing.target_overrides(
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

    def test_run_output_overrides_keep_outputs_on_runs_volume(self) -> None:
        overrides = commands.run_output_overrides(
            task_name="target_102L",
            run_name="smoke_run",
            pipeline_config=commands.DEFAULT_PIPELINE_CONFIG,
        )

        self.assertIn(
            "++root_path=/runs/smoke_run/inference/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )
        self.assertIn(
            "++results_dir=/runs/smoke_run/evaluation_results/search_binder_local_pipeline_target_102L_smoke_run",
            overrides,
        )

    def test_run_design_runs_from_complexa_root_with_persisted_output_paths(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(design, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(commands, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(design, "run_complexa", fake_run),
        ):
            result = design.run_design(
                task_name="target_102L",
                run_name="smoke_run",
                overrides=["++generation.target_dict_cfg.target_102L.target_input=A1-162"],
                steps=["generate"],
            )

        command, cwd = calls[0]
        self.assertEqual(cwd, Path(tmp) / "complexa")
        self.assertIn("++generation.target_dict_cfg.target_102L.target_input=A1-162", command)
        self.assertTrue(any(str(Path(tmp) / "runs" / "smoke_run" / "inference") in part for part in command))
        self.assertEqual(result["warm_start"], {"mode": "cold"})

    def test_seed_binder_overrides_include_optional_controls(self) -> None:
        overrides = warm_start.seed_binder_overrides(
            seed_binder_path=Path("/data/seed_binders/seed.pdb"),
            seed_binder_chain="B",
            seed_binder_noise_level=0.25,
            seed_binder_start_t=0.75,
            seed_binder_num_steps=80,
        )

        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=/data/seed_binders/seed.pdb",
            overrides,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_chain=B",
            overrides,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_noise_level=0.25",
            overrides,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_start_t=0.75",
            overrides,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_num_steps=80",
            overrides,
        )

    def test_seed_binder_overrides_accept_batched_paths_and_chains(self) -> None:
        overrides = warm_start.seed_binder_overrides(
            seed_binder_path=[
                Path("/data/seed_binders/seed_0.cif"),
                Path("/data/seed_binders/seed_1.cif"),
            ],
            seed_binder_chain=[None, "B"],
            seed_binder_noise_level=0.5,
        )

        self.assertIn(
            '++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=["/data/seed_binders/seed_0.cif","/data/seed_binders/seed_1.cif"]',
            overrides,
        )
        self.assertIn(
            '++generation.dataloader.dataset.conditional_features.0.seed_binder_chain=[null,"B"]',
            overrides,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_noise_level=0.5",
            overrides,
        )

    def test_seed_binder_remote_path_preserves_uncompressed_structure_suffix(self) -> None:
        self.assertEqual(
            warm_start.seed_binder_remote_path(
                task_name="target_102L",
                run_name="warm_smoke",
                seed_binder_filename="105M.cif.gz",
            ),
            warm_start.SEED_BINDER_DIR / "target_102L_warm_smoke.cif",
        )
        self.assertEqual(
            warm_start.seed_binder_remote_path(
                task_name="target_102L",
                run_name="warm_smoke",
                seed_binder_filename="seed.pdb",
            ),
            warm_start.SEED_BINDER_DIR / "target_102L_warm_smoke.pdb",
        )
        self.assertEqual(
            warm_start.seed_binder_remote_path(
                task_name="target_102L",
                run_name="warm_smoke",
                seed_binder_filename="105M.cif.gz",
                seed_binder_index=0,
            ),
            warm_start.SEED_BINDER_DIR / "target_102L_warm_smoke_seed_0_target_105M.cif",
        )

    def test_run_design_with_seed_passes_seed_overrides(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(design, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(commands, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(design, "run_complexa", fake_run),
            mock.patch.object(
                design,
                "warm_start_overrides",
                return_value=(
                    [
                        "++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=/data/seed_binders/seed.pdb",
                        "++generation.dataloader.dataset.conditional_features.0.seed_binder_chain=B",
                    ],
                    {"mode": "warm", "seed_binder_path": "/data/seed_binders/seed.pdb", "support_status": "native"},
                ),
            ) as setup,
        ):
            result = design.run_design(
                task_name="02_PDL1",
                run_name="pdl1_seeded",
                overrides=[],
                steps=["generate"],
                seed_binder_text="ATOM\n",
                seed_binder_chain="B",
            )

        setup.assert_called_once()
        command = calls[0][0]
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=/data/seed_binders/seed.pdb",
            command,
        )
        self.assertIn(
            "++generation.dataloader.dataset.conditional_features.0.seed_binder_chain=B",
            command,
        )
        self.assertEqual(result["warm_start"]["mode"], "warm")
        self.assertEqual(result["warm_start"]["support_status"], "native")

    def test_run_design_with_batched_seeds_passes_seed_list_overrides(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(design, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(commands, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(design, "run_complexa", fake_run),
            mock.patch.object(
                design,
                "warm_start_batch_overrides",
                return_value=(
                    [
                        '++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=["/data/seed_binders/seed_0.pdb","/data/seed_binders/seed_1.pdb"]',
                    ],
                    {
                        "mode": "warm",
                        "seed_binder_count": 2,
                        "seed_binder_paths": ["/data/seed_binders/seed_0.pdb", "/data/seed_binders/seed_1.pdb"],
                        "support_status": "native",
                    },
                ),
            ) as setup,
        ):
            result = design.run_design(
                task_name="02_PDL1",
                run_name="pdl1_seeded",
                overrides=[],
                steps=["generate"],
                seed_binders=[
                    {"structure_text": "ATOM seed 0\n", "filename": "seed_0.pdb"},
                    {"structure_text": "ATOM seed 1\n", "filename": "seed_1.pdb"},
                ],
            )

        setup.assert_called_once()
        command = calls[0][0]
        self.assertIn(
            '++generation.dataloader.dataset.conditional_features.0.seed_binder_pdb_path=["/data/seed_binders/seed_0.pdb","/data/seed_binders/seed_1.pdb"]',
            command,
        )
        self.assertEqual(result["warm_start"]["mode"], "warm")
        self.assertEqual(result["warm_start"]["seed_binder_count"], 2)

    def test_run_design_falls_back_to_cold_when_warm_start_setup_fails(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(design, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(commands, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(design, "run_complexa", fake_run),
            mock.patch.object(design, "warm_start_overrides", side_effect=RuntimeError("missing")),
        ):
            result = design.run_design(
                task_name="02_PDL1",
                run_name="pdl1_seeded",
                overrides=[],
                seed_binder_text="ATOM\n",
            )

        command = calls[0][0]
        self.assertFalse(any("seed_binder_pdb_path" in part for part in command))
        self.assertEqual(result["warm_start"]["mode"], "cold")

    def test_http_design_request_runs_target_each_time_and_passes_warm_start(self) -> None:
        preprocessed = {
            "target_name": "target_102L",
            "hydra_overrides": [
                "++generation.task_name=target_102L",
                "++generation.target_dict_cfg.target_102L.target_path=/data/target_data/preprocessed_targets/target_102L.pdb",
            ],
        }

        with (
            mock.patch.object(http_server, "preprocess_target_structure", return_value=preprocessed) as preprocess,
            mock.patch.object(http_server, "run_design", return_value={"warm_start": {"mode": "warm"}}) as run,
        ):
            result = http_server.run_design_request(
                {
                    "action": "smoke-cif",
                    "run_name": "api_smoke",
                    "target": {
                        "structure": "data_target\n#",
                        "filename": "102L.cif",
                        "name": "target_102L",
                        "target_input": "A1-162",
                        "hotspot_residues": ["A45"],
                        "binder_length": [60, 120],
                    },
                    "warm_start": {
                        "structure": "ATOM      1  CA  GLY B   1       0.000   0.000   0.000",
                        "filename": "seed.pdb",
                        "chain": "B",
                        "noise_level": 0.4,
                    },
                    "overrides": ["++generation.dataloader.batch_size=2"],
                }
            )

        preprocess.assert_called_once()
        preprocess_kwargs = preprocess.call_args.kwargs
        self.assertEqual(preprocess_kwargs["structure_filename"], "102L.cif")
        self.assertEqual(preprocess_kwargs["target_name"], "target_102L")
        self.assertEqual(preprocess_kwargs["target_input"], "A1-162")
        self.assertEqual(preprocess_kwargs["hotspot_residues"], ["A45"])

        run.assert_called_once()
        run_kwargs = run.call_args.kwargs
        self.assertEqual(run_kwargs["task_name"], "target_102L")
        self.assertEqual(run_kwargs["run_name"], "api_smoke")
        self.assertEqual(run_kwargs["steps"], ["generate"])
        self.assertEqual(run_kwargs["seed_binder_filename"], "seed.pdb")
        self.assertEqual(run_kwargs["seed_binder_chain"], "B")
        self.assertEqual(run_kwargs["seed_binder_noise_level"], 0.4)
        self.assertIs(run_kwargs["include_generated_pdbs"], True)
        self.assertIn("++generation.args.nsteps=20", run_kwargs["overrides"])
        self.assertIn("++generation.dataloader.batch_size=2", run_kwargs["overrides"])
        self.assertEqual(result["mode"], "smoke-cif")
        self.assertEqual(result["format"], "pdb")

    def test_http_design_request_accepts_batched_warm_starts(self) -> None:
        preprocessed = {
            "target_name": "target_102L",
            "hydra_overrides": [
                "++generation.task_name=target_102L",
                "++generation.target_dict_cfg.target_102L.target_path=/data/target_data/preprocessed_targets/target_102L.pdb",
            ],
        }

        with (
            mock.patch.object(http_server, "preprocess_target_structure", return_value=preprocessed) as preprocess,
            mock.patch.object(http_server, "run_design", return_value={"warm_start": {"mode": "warm"}}) as run,
        ):
            result = http_server.run_design_request(
                {
                    "action": "smoke-cif",
                    "run_name": "api_smoke",
                    "target": {
                        "structure": "data_target\n#",
                        "filename": "102L.cif",
                        "name": "target_102L",
                        "target_input": "A1-162",
                        "binder_length": [60, 120],
                    },
                    "warm_start": [
                        {
                            "structure": "ATOM seed 0\n",
                            "filename": "105M.cif",
                            "noise_level": 0.5,
                        },
                        {
                            "structure": "ATOM seed 1\n",
                            "filename": "1OZ9.cif",
                            "noise_level": 0.5,
                        },
                    ],
                }
            )

        preprocess.assert_called_once()
        run.assert_called_once()
        run_kwargs = run.call_args.kwargs
        self.assertEqual(run_kwargs["seed_binders"][0]["filename"], "105M.cif")
        self.assertEqual(run_kwargs["seed_binders"][1]["filename"], "1OZ9.cif")
        self.assertIn("++generation.dataloader.batch_size=2", run_kwargs["overrides"])
        self.assertIn("++generation.dataloader.dataset.nres.nsamples=2", run_kwargs["overrides"])
        self.assertEqual(run_kwargs["steps"], ["generate"])
        self.assertEqual(result["warm_start_count"], 2)

    def test_http_design_request_rejects_mixed_batch_noise_levels(self) -> None:
        with self.assertRaisesRegex(ValueError, "same noise_level"):
            http_server.run_design_request(
                {
                    "action": "smoke-cif",
                    "target": {
                        "structure": "data_target\n#",
                        "filename": "102L.cif",
                        "target_input": "A1-162",
                    },
                    "warm_start": [
                        {"structure": "ATOM seed 0\n", "filename": "105M.cif", "noise_level": 0.25},
                        {"structure": "ATOM seed 1\n", "filename": "1OZ9.cif", "noise_level": 0.5},
                    ],
                }
            )

    def test_http_design_request_requires_target_contents_not_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "file contents"):
            http_server.run_design_request({"target": {"structure": "/tmp/target.cif"}})

    def test_collect_generated_pdbs_reads_ranked_pdb_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inference_dir = Path(tmp) / "inference"
            first_dir = inference_dir / "job_0"
            second_dir = inference_dir / "job_1"
            first_dir.mkdir(parents=True)
            second_dir.mkdir(parents=True)
            (second_dir / "job_1.pdb").write_text("ATOM second\n")
            (first_dir / "job_0.pdb").write_text("ATOM first\n")

            pdbs = commands.collect_generated_pdbs(inference_dir=inference_dir)

        self.assertEqual(len(pdbs), 2)
        self.assertEqual(pdbs[0]["filename"], "job_0.pdb")
        self.assertEqual(pdbs[0]["relative_path"], "job_0/job_0.pdb")
        self.assertEqual(pdbs[0]["pdb"], "ATOM first\n")

    def test_run_design_only_returns_pdbs_when_requested(self) -> None:
        calls = []

        def fake_run(command, *, cwd):
            calls.append((command, cwd))
            return "ok"

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(design, "COMPLEXA_ROOT", Path(tmp) / "complexa"),
            mock.patch.object(commands, "RUNS_DIR", Path(tmp) / "runs"),
            mock.patch.object(design, "run_complexa", fake_run),
        ):
            result = design.run_design(
                task_name="target_102L",
                run_name="local_dev",
                steps=["generate"],
            )

        self.assertNotIn("pdbs", result)

    def test_pdb_file_payload_extracts_first_generated_structure(self) -> None:
        filename, pdb_text = http_server.pdb_file_payload(
            {
                "pdbs": [
                    {
                        "filename": "job_0.pdb",
                        "pdb": "ATOM first\n",
                    }
                ]
            }
        )

        self.assertEqual(filename, "job_0.pdb")
        self.assertEqual(pdb_text, "ATOM first\n")

    def test_pdb_download_headers_force_attachment_filename(self) -> None:
        headers = http_server.pdb_download_headers("../job_0.pdb")

        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="job_0.pdb"')


if __name__ == "__main__":
    unittest.main()
