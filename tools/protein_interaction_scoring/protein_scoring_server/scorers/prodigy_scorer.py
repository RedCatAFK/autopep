from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .schemas import ProdigyResult
from .utils import command_available, infer_protein_chains


AFFINITY_RE = re.compile(
    r"Predicted binding affinity.*?:\s*([-+]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
KD_RE = re.compile(
    r"Predicted dissociation constant.*?:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
    re.IGNORECASE,
)
FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class ProdigyScorer:
    def __init__(
        self,
        *,
        command: str = "prodigy",
        timeout_seconds: int = 5 * 60,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self._loaded = False
        self._available = False

    def load(self) -> None:
        self._available = command_available(self.command)
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_available(self) -> bool:
        return self._available

    def score_structure(
        self,
        item_id: str,
        structure_path: Path,
        *,
        structure_format: str = "pdb",
        chain_a: str | None = None,
        chain_b: str | None = None,
        temperature_celsius: float = 25.0,
    ) -> ProdigyResult:
        if not self._loaded:
            self.load()
        if not self._available:
            return ProdigyResult.unavailable(
                "PRODIGY CLI is not installed or not on PATH",
                temperature_celsius=temperature_celsius,
            )
        if not structure_path.exists():
            return ProdigyResult.unavailable(
                f"structure file does not exist for {item_id}",
                temperature_celsius=temperature_celsius,
            )

        warnings: list[str] = []
        chains = infer_protein_chains(structure_path, structure_format)
        if chains and len(chains) < 2:
            return ProdigyResult.unavailable(
                "PRODIGY requires a complex structure with at least two protein chains",
                temperature_celsius=temperature_celsius,
            )

        selection_a, selection_b = self._resolve_chain_selection(
            chains,
            chain_a=chain_a,
            chain_b=chain_b,
            warnings=warnings,
        )
        if (selection_a is None) != (selection_b is None):
            return ProdigyResult.unavailable(
                "could not determine two protein chains for PRODIGY scoring",
                temperature_celsius=temperature_celsius,
                warnings=warnings,
            )

        command = [self.command, str(structure_path), "--temperature", str(temperature_celsius)]
        if selection_a is not None and selection_b is not None:
            command.extend(["--selection", selection_a, selection_b])

        try:
            completed = self._run_command(command)
            delta_g, kd_molar = parse_prodigy_output(completed.stdout)
        except Exception as exc:
            return ProdigyResult.unavailable(
                f"PRODIGY failed: {exc}",
                temperature_celsius=temperature_celsius,
                warnings=warnings,
            )

        if delta_g is None:
            return ProdigyResult.unavailable(
                "PRODIGY output did not include a binding affinity",
                temperature_celsius=temperature_celsius,
                warnings=warnings,
            )

        return ProdigyResult(
            available=True,
            delta_g_kcal_per_mol=delta_g,
            kd_molar=kd_molar,
            temperature_celsius=temperature_celsius,
            warnings=warnings,
        )

    def _resolve_chain_selection(
        self,
        chains: list[str],
        *,
        chain_a: str | None,
        chain_b: str | None,
        warnings: list[str],
    ) -> tuple[str | None, str | None]:
        if chain_a and chain_b:
            if chains:
                missing = [chain for chain in (chain_a, chain_b) if chain not in chains]
                if missing:
                    warnings.append(
                        "Provided chain identifiers were not detected in parsed protein chains: "
                        + ", ".join(missing)
                    )
            return chain_a, chain_b

        if not chains:
            warnings.append(
                "Could not infer protein chains locally; PRODIGY will receive no chain selection"
            )
            return chain_a, chain_b

        if chain_a and not chain_b:
            inferred = next((chain for chain in chains if chain != chain_a), None)
            warnings.append(f"Inferred chain_b={inferred} for PRODIGY selection")
            return chain_a, inferred

        if chain_b and not chain_a:
            inferred = next((chain for chain in chains if chain != chain_b), None)
            warnings.append(f"Inferred chain_a={inferred} for PRODIGY selection")
            return inferred, chain_b

        warnings.append(
            f"structure.chain_a and structure.chain_b were missing; inferred {chains[0]} and {chains[1]}"
        )
        return chains[0], chains[1]

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
                f"{' '.join(command)} exited {completed.returncode} after {elapsed:.2f}s: "
                f"{stderr[-1000:]}"
            )
        return completed


def parse_prodigy_output(stdout: str) -> tuple[float | None, float | None]:
    affinity_match = AFFINITY_RE.search(stdout)
    kd_match = KD_RE.search(stdout)

    delta_g = float(affinity_match.group(1)) if affinity_match else None
    kd_molar = float(kd_match.group(1)) if kd_match else None
    if delta_g is not None:
        return delta_g, kd_molar

    # Quiet mode and some wrappers emit "name  -9.373"; use the last float.
    floats: list[float] = []
    for line in stdout.splitlines():
        for match in FLOAT_RE.findall(line):
            try:
                floats.append(float(match))
            except ValueError:
                continue
    if floats:
        return floats[-1], kd_molar
    return None, kd_molar


class MockProdigyScorer:
    def __init__(
        self,
        *,
        delta_g_by_id: dict[str, float] | None = None,
        kd_by_id: dict[str, float | None] | None = None,
        default_delta_g: float = -9.7,
        default_kd: float | None = 7.8e-8,
    ) -> None:
        self.delta_g_by_id = delta_g_by_id or {}
        self.kd_by_id = kd_by_id or {}
        self.default_delta_g = default_delta_g
        self.default_kd = default_kd
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def is_available(self) -> bool:
        return True

    def score_structure(
        self,
        item_id: str,
        structure_path: Path,
        *,
        structure_format: str = "pdb",
        chain_a: str | None = None,
        chain_b: str | None = None,
        temperature_celsius: float = 25.0,
    ) -> ProdigyResult:
        self.load()
        if not structure_path.exists():
            return ProdigyResult.unavailable(
                "mock structure file does not exist",
                temperature_celsius=temperature_celsius,
            )
        return ProdigyResult(
            available=True,
            delta_g_kcal_per_mol=self.delta_g_by_id.get(
                item_id, self.default_delta_g
            ),
            kd_molar=self.kd_by_id.get(item_id, self.default_kd),
            temperature_celsius=temperature_celsius,
            warnings=[] if chain_a and chain_b else ["Mock scorer received inferred chains"],
        )
