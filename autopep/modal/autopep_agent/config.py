from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_MODEL = "gpt-5.5"

REQUIRED_ENV_VARS = (
    "DATABASE_URL",
    "R2_BUCKET",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "MODAL_PROTEINA_URL",
    "MODAL_PROTEINA_API_KEY",
    "MODAL_CHAI_URL",
    "MODAL_CHAI_API_KEY",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL",
    "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY",
    "MODAL_QUALITY_SCORERS_URL",
    "MODAL_QUALITY_SCORERS_API_KEY",
    "OPENAI_API_KEY",
)

URL_ENV_VARS = {
    "MODAL_PROTEINA_URL",
    "MODAL_CHAI_URL",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL",
    "MODAL_QUALITY_SCORERS_URL",
}


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    r2_bucket: str
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    modal_proteina_url: str
    modal_proteina_api_key: str
    modal_chai_url: str
    modal_chai_api_key: str
    modal_protein_interaction_scoring_url: str
    modal_protein_interaction_scoring_api_key: str
    modal_quality_scorers_url: str
    modal_quality_scorers_api_key: str
    openai_api_key: str
    default_model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> WorkerConfig:
        source = os.environ if env is None else env
        values: dict[str, str] = {}
        missing: list[str] = []

        for key in REQUIRED_ENV_VARS:
            value = source.get(key, "").strip()
            if not value:
                missing.append(key)
                continue
            if key in URL_ENV_VARS:
                value = value.rstrip("/")
            values[key] = value

        if missing:
            missing_vars = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variables: {missing_vars}")

        default_model = source.get("OPENAI_DEFAULT_MODEL", "").strip() or DEFAULT_MODEL

        return cls(
            database_url=values["DATABASE_URL"],
            r2_bucket=values["R2_BUCKET"],
            r2_account_id=values["R2_ACCOUNT_ID"],
            r2_access_key_id=values["R2_ACCESS_KEY_ID"],
            r2_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
            modal_proteina_url=values["MODAL_PROTEINA_URL"],
            modal_proteina_api_key=values["MODAL_PROTEINA_API_KEY"],
            modal_chai_url=values["MODAL_CHAI_URL"],
            modal_chai_api_key=values["MODAL_CHAI_API_KEY"],
            modal_protein_interaction_scoring_url=values[
                "MODAL_PROTEIN_INTERACTION_SCORING_URL"
            ],
            modal_protein_interaction_scoring_api_key=values[
                "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY"
            ],
            modal_quality_scorers_url=values["MODAL_QUALITY_SCORERS_URL"],
            modal_quality_scorers_api_key=values["MODAL_QUALITY_SCORERS_API_KEY"],
            openai_api_key=values["OPENAI_API_KEY"],
            default_model=default_model,
        )
