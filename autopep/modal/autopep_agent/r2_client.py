from __future__ import annotations

import asyncio
import hashlib
from typing import Any


# TODO(MVP scale): hoist boto3 client construction out of the per-call path.
# Building a fresh client on every put_object thrashes the cert/signer setup
# (TLS, credential resolver, region resolver) and adds avoidable latency to
# each artifact upload. A module-level cached client (or a small dict keyed by
# account_id + access_key_id) would be a one-time fix. Acceptable for MVP
# scale where the agent uploads a handful of artifacts per run.
def _build_client(
    *,
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
) -> Any:
    import boto3  # imported lazily so unit tests that monkeypatch this module
    # do not require boto3 import-time configuration.

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


async def put_object(
    *,
    bucket: str,
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    key: str,
    body: bytes,
    content_type: str,
) -> str:
    """Upload ``body`` to R2 at ``key`` and return its SHA-256 hex digest.

    boto3 is synchronous, so the actual ``PutObject`` runs in a thread to
    avoid blocking the asyncio event loop.
    """

    sha256 = hashlib.sha256(body).hexdigest()

    def _put() -> None:
        client = _build_client(
            account_id=account_id,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    await asyncio.to_thread(_put)
    return sha256
