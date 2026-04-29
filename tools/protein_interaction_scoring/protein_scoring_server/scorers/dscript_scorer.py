from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from .schemas import DScriptResult, SequencePair
from .utils import (
    command_available,
    parse_dscript_predictions,
    safe_item_token,
    write_fasta,
    write_pairs_tsv,
)


class DScriptScorer:
    """Batched D-SCRIPT scorer with Python API first and CLI fallback.

    When the D-SCRIPT package is importable, load() keeps the model resident for
    reuse across requests. If that backend is unavailable and the CLI exists,
    the scorer falls back to D-SCRIPT's documented embed/predict file flow.
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        command: str = "dscript",
        device: str | None = None,
        backend: str | None = None,
        timeout_seconds: int = 20 * 60,
    ) -> None:
        self.model_name = model_name or os.getenv(
            "DSCRIPT_MODEL", "samsl/topsy_turvy_human_v1"
        )
        self.command = command
        self.device = device or os.getenv("DSCRIPT_DEVICE")
        self.backend = (backend or os.getenv("DSCRIPT_BACKEND", "auto")).lower()
        self.timeout_seconds = timeout_seconds
        self._loaded = False
        self._available = False
        self._active_backend: str | None = None
        self._load_error: str | None = None
        self._model = None
        self._lm_embed = None
        self._torch = None
        self._use_cuda = False

    def load(self) -> None:
        self._available = False
        self._active_backend = None
        self._load_error = None

        if self.backend in {"auto", "python"}:
            try:
                import torch
                from dscript.language_model import lm_embed
                from dscript.models.interaction import DSCRIPTModel

                use_cuda = torch.cuda.is_available()
                model = DSCRIPTModel.from_pretrained(
                    self.model_name,
                    use_cuda=use_cuda,
                )
                if use_cuda:
                    model = model.cuda()
                    model.use_cuda = True
                else:
                    model = model.cpu()
                    model.use_cuda = False
                model.eval()

                self._model = model
                self._lm_embed = lm_embed
                self._torch = torch
                self._use_cuda = use_cuda
                self._active_backend = "python"
                self._available = True
                self._loaded = True
                return
            except Exception as exc:
                self._load_error = f"Python D-SCRIPT backend failed to load: {exc}"
                if self.backend == "python":
                    self._loaded = True
                    return

        if self.backend in {"auto", "cli"} and command_available(self.command):
            self._active_backend = "cli"
            self._available = True
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_available(self) -> bool:
        return self._available

    def score_batch(self, pairs: list[SequencePair]) -> dict[str, DScriptResult]:
        if not self._loaded:
            self.load()

        results: dict[str, DScriptResult] = {}
        runnable_pairs: list[tuple[SequencePair, str, str]] = []

        for index, pair in enumerate(pairs):
            if not pair.sequence_a or not pair.sequence_b:
                results[pair.item_id] = DScriptResult.unavailable(
                    "D-SCRIPT requires protein_a.sequence and protein_b.sequence",
                    model_name=self.model_name,
                )
                continue
            left_key = f"pair{index:03d}_{safe_item_token(pair.item_id)}_A"
            right_key = f"pair{index:03d}_{safe_item_token(pair.item_id)}_B"
            runnable_pairs.append((pair, left_key, right_key))

        if not runnable_pairs:
            return results

        if not self._available:
            load_error = f" ({self._load_error})" if self._load_error else ""
            for pair, _left_key, _right_key in runnable_pairs:
                results[pair.item_id] = DScriptResult.unavailable(
                    "D-SCRIPT is not available in this container" + load_error,
                    model_name=self.model_name,
                )
            return results

        if self._active_backend == "python":
            return self._score_batch_python(runnable_pairs, results)
        return self._score_batch_cli(runnable_pairs, results)

    def _score_batch_python(
        self,
        runnable_pairs: list[tuple[SequencePair, str, str]],
        results: dict[str, DScriptResult],
    ) -> dict[str, DScriptResult]:
        if self._model is None or self._lm_embed is None or self._torch is None:
            error = "D-SCRIPT Python backend was selected but model resources are missing"
            for pair, _left_key, _right_key in runnable_pairs:
                results[pair.item_id] = DScriptResult.unavailable(
                    error,
                    model_name=self.model_name,
                )
            return results

        sequence_embeddings = {}
        for pair, left_key, right_key in runnable_pairs:
            try:
                if left_key not in sequence_embeddings:
                    sequence_embeddings[left_key] = self._lm_embed(
                        pair.sequence_a or "",
                        self._use_cuda,
                    )
                if right_key not in sequence_embeddings:
                    sequence_embeddings[right_key] = self._lm_embed(
                        pair.sequence_b or "",
                        self._use_cuda,
                    )
            except Exception as exc:
                results[pair.item_id] = DScriptResult.unavailable(
                    f"D-SCRIPT embedding failed: {exc}",
                    model_name=self.model_name,
                )

        with self._torch.no_grad():
            for pair, left_key, right_key in runnable_pairs:
                if pair.item_id in results:
                    continue
                try:
                    p0 = sequence_embeddings[left_key]
                    p1 = sequence_embeddings[right_key]
                    if self._use_cuda:
                        p0 = p0.cuda()
                        p1 = p1.cuda()
                    _contact_map, probability = self._model.map_predict(p0, p1)
                    raw_score = float(probability.item())
                except Exception as exc:
                    results[pair.item_id] = DScriptResult.unavailable(
                        f"D-SCRIPT prediction failed: {exc}",
                        model_name=self.model_name,
                    )
                    continue

                warnings: list[str] = []
                interaction_probability = raw_score if 0.0 <= raw_score <= 1.0 else None
                if interaction_probability is None:
                    warnings.append(
                        "D-SCRIPT raw score was outside [0, 1], so interaction_probability is null"
                    )
                results[pair.item_id] = DScriptResult(
                    available=True,
                    interaction_probability=interaction_probability,
                    raw_score=raw_score,
                    model_name=self.model_name,
                    warnings=warnings,
                )

        return results

    def _score_batch_cli(
        self,
        runnable_pairs: list[tuple[SequencePair, str, str]],
        results: dict[str, DScriptResult],
    ) -> dict[str, DScriptResult]:
        with tempfile.TemporaryDirectory(prefix="dscript_batch_") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            fasta_path = temp_dir / "sequences.fasta"
            pairs_path = temp_dir / "pairs.tsv"
            embedding_path = temp_dir / "embeddings.h5"
            output_prefix = temp_dir / "predictions"

            records: dict[str, str] = {}
            pair_keys: list[tuple[str, str]] = []
            key_to_item: dict[tuple[str, str], str] = {}
            for pair, left_key, right_key in runnable_pairs:
                records[left_key] = pair.sequence_a or ""
                records[right_key] = pair.sequence_b or ""
                pair_keys.append((left_key, right_key))
                key_to_item[(left_key, right_key)] = pair.item_id

            write_fasta(fasta_path, records)
            write_pairs_tsv(pairs_path, pair_keys)

            try:
                self._run_command(
                    [
                        self.command,
                        "embed",
                        "--seqs",
                        str(fasta_path),
                        "--outfile",
                        str(embedding_path),
                    ]
                )

                predict_command = [
                    self.command,
                    "predict",
                    "--pairs",
                    str(pairs_path),
                    "--embeddings",
                    str(embedding_path),
                    "--model",
                    self.model_name,
                    "--outfile",
                    str(output_prefix),
                ]
                if self.device:
                    predict_command.extend(["-d", self.device])
                self._run_command(predict_command)

                predictions = parse_dscript_predictions(output_prefix)
            except Exception as exc:
                error = f"D-SCRIPT failed: {exc}"
                for pair, _left_key, _right_key in runnable_pairs:
                    results[pair.item_id] = DScriptResult.unavailable(
                        error,
                        model_name=self.model_name,
                    )
                return results

        for key_pair, item_id in key_to_item.items():
            raw_score = predictions.get(key_pair)
            if raw_score is None:
                results[item_id] = DScriptResult.unavailable(
                    "D-SCRIPT did not produce a score for this pair",
                    model_name=self.model_name,
                )
                continue

            warnings: list[str] = []
            probability = raw_score if 0.0 <= raw_score <= 1.0 else None
            if probability is None:
                warnings.append(
                    "D-SCRIPT raw score was outside [0, 1], so interaction_probability is null"
                )
            results[item_id] = DScriptResult(
                available=True,
                interaction_probability=probability,
                raw_score=raw_score,
                model_name=self.model_name,
                warnings=warnings,
            )

        return results

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"{' '.join(command[:2])} exited {completed.returncode} after "
                f"{elapsed:.2f}s: {stderr[-1000:]}"
            )
        return completed


class MockDScriptScorer:
    def __init__(
        self,
        *,
        score_by_id: dict[str, float] | None = None,
        default_score: float = 0.83,
        model_name: str = "dscript-mock",
    ) -> None:
        self.score_by_id = score_by_id or {}
        self.default_score = default_score
        self.model_name = model_name
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_available(self) -> bool:
        return True

    def score_batch(self, pairs: list[SequencePair]) -> dict[str, DScriptResult]:
        self.load()
        results: dict[str, DScriptResult] = {}
        for pair in pairs:
            if not pair.sequence_a or not pair.sequence_b:
                results[pair.item_id] = DScriptResult.unavailable(
                    "D-SCRIPT requires protein_a.sequence and protein_b.sequence",
                    model_name=self.model_name,
                )
                continue
            raw_score = self.score_by_id.get(pair.item_id, self.default_score)
            probability = raw_score if 0.0 <= raw_score <= 1.0 else None
            warnings = []
            if probability is None:
                warnings.append("Mock raw score was outside [0, 1]")
            results[pair.item_id] = DScriptResult(
                available=True,
                interaction_probability=probability,
                raw_score=raw_score,
                model_name=self.model_name,
                warnings=warnings,
            )
        return results
