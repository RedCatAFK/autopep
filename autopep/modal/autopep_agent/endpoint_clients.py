from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

import httpx


PROTEINA_DESIGN_STEPS = ["generate"]
PROTEINA_BATCH_SIZE = 5
PROTEINA_FAST_GENERATION_OVERRIDES = [
    "++generation.search.algorithm=single-pass",
    "++generation.reward_model=null",
    f"++generation.dataloader.batch_size={PROTEINA_BATCH_SIZE}",
    f"++generation.dataloader.dataset.nres.nsamples={PROTEINA_BATCH_SIZE}",
    "++generation.args.nsteps=20",
]

TRANSIENT_STATUS_CODES = {500, 502, 503, 504}


class ModalEndpointError(RuntimeError):
    """Concise endpoint failure surfaced to the agent/tool ledger."""

    def __init__(
        self,
        *,
        method: str,
        url: str,
        status_code: int | None = None,
        response_text: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.response_text = response_text

        if status_code is None:
            detail = f"{method} {url} failed"
        else:
            detail = f"{method} {url} returned HTTP {status_code}"
            if status_code in TRANSIENT_STATUS_CODES:
                detail += " (endpoint unavailable or restarting)"
        if response_text:
            detail += f": {response_text[:500]}"

        super().__init__(detail)
        if cause is not None:
            self.__cause__ = cause


class ModalEndpointClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 900,
        *,
        max_attempts: int = 2,
        retry_delay_s: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_s = max(0.0, float(retry_delay_s))

    async def post_json(self, path: str, payload: Mapping[str, Any]) -> Any:
        request_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{request_path}"
        headers = {
            "X-API-Key": self.api_key,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.RequestError as exc:
                    if attempt < self.max_attempts:
                        await asyncio.sleep(self.retry_delay_s)
                        continue
                    raise ModalEndpointError(
                        method="POST",
                        url=url,
                        response_text=str(exc),
                        cause=exc,
                    ) from exc

                if (
                    response.status_code in TRANSIENT_STATUS_CODES
                    and attempt < self.max_attempts
                ):
                    await asyncio.sleep(self.retry_delay_s)
                    continue

                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ModalEndpointError(
                        method="POST",
                        url=url,
                        status_code=response.status_code,
                        response_text=response.text,
                        cause=exc,
                    ) from exc
                break

        return response.json()


class ProteinaClient(ModalEndpointClient):
    async def design(
        self,
        target_structure: str,
        target_filename: str,
        target_input: str | None,
        hotspot_residues: Sequence[str],
        binder_length: Sequence[int],
        warm_start_structure: str | None = None,
        warm_start_filename: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "action": "design-cif",
            "design_steps": PROTEINA_DESIGN_STEPS,
            "overrides": PROTEINA_FAST_GENERATION_OVERRIDES,
            "target": {
                "structure": target_structure,
                "filename": target_filename,
                "target_input": target_input,
                "hotspot_residues": list(hotspot_residues),
                "binder_length": list(binder_length),
            },
        }
        if warm_start_structure is not None:
            # Top-level ``warm_start`` object: this matches the canonical shape
            # accepted by tools/proteina-complexa/proteina_complexa/payloads.py
            # (``_warm_start_payloads`` reads ``warm_start`` from the outer
            # request body, not from inside ``target``).
            payload["warm_start"] = {
                "structure": warm_start_structure,
                "filename": warm_start_filename or "warm_start.pdb",
            }
        return await self.post_json("/design", payload)


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


class QualityScorersClient(ModalEndpointClient):
    """Client for the per-candidate quality scorer Modal endpoint.

    The deployed FastAPI app (``tools/quality-scorers/inference_modal_app.py``)
    only exposes single-sequence ``POST /predict`` taking
    ``{"fasta": ">id\\nSEQUENCE"}`` and returning ``{"scores": {...}}``.
    There is no batch endpoint, so :meth:`score_batch` fans out one HTTP
    call per sequence using ``asyncio.gather`` and aggregates the results
    into the shape ``{"results": [{"id": ..., "scores": {...}}, ...]}``.
    """

    async def score(self, sequence_id: str, sequence: str) -> dict[str, Any]:
        fasta = f">{sequence_id}\n{sequence}\n"
        return await self.post_json("/predict", {"fasta": fasta})

    async def score_batch(
        self, sequences: Sequence[tuple[str, str]],
    ) -> dict[str, Any]:
        import asyncio

        seq_list = list(sequences)
        if not seq_list:
            return {"results": []}

        responses = await asyncio.gather(
            *(self.score(cid, seq) for cid, seq in seq_list),
            return_exceptions=True,
        )

        results: list[dict[str, Any]] = []
        for (cid, _seq), response in zip(seq_list, responses, strict=True):
            if isinstance(response, BaseException):
                results.append(
                    {
                        "id": cid,
                        "scores": {},
                        "error": str(response).strip()
                        or response.__class__.__name__,
                    },
                )
                continue
            scores: dict[str, Any] = {}
            if isinstance(response, Mapping):
                raw_scores = response.get("scores")
                if isinstance(raw_scores, Mapping):
                    scores = dict(raw_scores)
            results.append({"id": cid, "scores": scores})
        return {"results": results}
