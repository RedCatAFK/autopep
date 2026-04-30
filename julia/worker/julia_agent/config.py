from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _truthy(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str | None
    webhook_secret: str | None
    dry_run: bool
    r2_bucket: str | None
    r2_endpoint_url: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None
    r2_region: str
    r2_public_base_url: str | None

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        load_dotenv()
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            webhook_secret=os.getenv("JULIA_WORKER_WEBHOOK_SECRET"),
            dry_run=_truthy(os.getenv("JULIA_WORKER_DRY_RUN")),
            r2_bucket=os.getenv("R2_BUCKET"),
            r2_endpoint_url=os.getenv("R2_ENDPOINT_URL"),
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            r2_region=os.getenv("R2_REGION", "auto"),
            r2_public_base_url=os.getenv("R2_PUBLIC_BASE_URL"),
        )

