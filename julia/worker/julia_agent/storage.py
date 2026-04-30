from __future__ import annotations

from pathlib import Path

import boto3

from julia_agent.config import WorkerConfig


def create_r2_client(config: WorkerConfig):
    missing = [
        name
        for name, value in {
            "R2_ENDPOINT_URL": config.r2_endpoint_url,
            "R2_ACCESS_KEY_ID": config.r2_access_key_id,
            "R2_SECRET_ACCESS_KEY": config.r2_secret_access_key,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing R2 configuration: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=config.r2_endpoint_url,
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        region_name=config.r2_region,
    )


def upload_file_to_r2(client, bucket: str, path: Path | str, key: str) -> str:
    if not bucket:
        raise ValueError("R2_BUCKET is required")
    local_path = Path(path)
    client.upload_file(str(local_path), bucket, key)
    return key

