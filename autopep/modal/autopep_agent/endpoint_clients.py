from __future__ import annotations

from typing import Any, Mapping, Sequence

import httpx


class ModalEndpointClient:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 900) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def post_json(self, path: str, payload: Mapping[str, Any]) -> Any:
        request_path = path if path.startswith("/") else f"/{path}"
        headers = {
            "X-API-Key": self.api_key,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                f"{self.base_url}{request_path}",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        return response.json()


class ProteinaClient(ModalEndpointClient):
    async def design(
        self,
        target_structure: str,
        target_filename: str,
        target_input: str | None,
        hotspot_residues: Sequence[str],
        binder_length: Sequence[int],
    ) -> Any:
        return await self.post_json(
            "/design",
            {
                "action": "design-cif",
                "target": {
                    "structure": target_structure,
                    "filename": target_filename,
                    "target_input": target_input,
                    "hotspot_residues": list(hotspot_residues),
                    "binder_length": list(binder_length),
                },
            },
        )


class ChaiClient(ModalEndpointClient):
    async def predict(self, fasta: str, num_diffn_samples: int = 1) -> Any:
        return await self.post_json(
            "/predict",
            {
                "fasta": fasta,
                "num_trunk_recycles": 3,
                "num_diffn_timesteps": 200,
                "num_diffn_samples": num_diffn_samples,
                "seed": 42,
                "include_pdb": False,
                "include_viewer_html": False,
            },
        )


class ScoringClient(ModalEndpointClient):
    async def score_batch(self, items: Sequence[Mapping[str, Any]]) -> Any:
        return await self.post_json(
            "/score_batch",
            {
                "items": list(items),
                "options": {
                    "run_dscript": True,
                    "run_prodigy": True,
                    "temperature_celsius": 25.0,
                    "fail_fast": False,
                },
            },
        )
