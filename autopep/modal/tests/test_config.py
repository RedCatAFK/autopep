from __future__ import annotations

import pytest

from autopep_agent.config import WorkerConfig


REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://autopep:test@db.example/autopep",
    "R2_BUCKET": "autopep-artifacts",
    "R2_ACCOUNT_ID": "r2-account",
    "R2_ACCESS_KEY_ID": "r2-access-key",
    "R2_SECRET_ACCESS_KEY": "r2-secret",
    "MODAL_PROTEINA_URL": "https://proteina.example/run/",
    "MODAL_PROTEINA_API_KEY": "proteina-key",
    "MODAL_CHAI_URL": "https://chai.example/run/",
    "MODAL_CHAI_API_KEY": "chai-key",
    "MODAL_PROTEIN_INTERACTION_SCORING_URL": "https://pis.example/run/",
    "MODAL_PROTEIN_INTERACTION_SCORING_API_KEY": "pis-key",
    "OPENAI_API_KEY": "openai-key",
}


def set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_from_env_reads_required_values_and_normalizes_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)

    config = WorkerConfig.from_env()

    assert config.database_url == REQUIRED_ENV["DATABASE_URL"]
    assert config.r2_bucket == REQUIRED_ENV["R2_BUCKET"]
    assert config.r2_account_id == REQUIRED_ENV["R2_ACCOUNT_ID"]
    assert config.r2_access_key_id == REQUIRED_ENV["R2_ACCESS_KEY_ID"]
    assert config.r2_secret_access_key == REQUIRED_ENV["R2_SECRET_ACCESS_KEY"]
    assert config.modal_proteina_url == "https://proteina.example/run"
    assert config.modal_proteina_api_key == REQUIRED_ENV["MODAL_PROTEINA_API_KEY"]
    assert config.modal_chai_url == "https://chai.example/run"
    assert config.modal_chai_api_key == REQUIRED_ENV["MODAL_CHAI_API_KEY"]
    assert config.modal_protein_interaction_scoring_url == "https://pis.example/run"
    assert (
        config.modal_protein_interaction_scoring_api_key
        == REQUIRED_ENV["MODAL_PROTEIN_INTERACTION_SCORING_API_KEY"]
    )
    assert config.openai_api_key == REQUIRED_ENV["OPENAI_API_KEY"]
    assert config.default_model == "gpt-5.5"


def test_from_env_uses_openai_default_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "gpt-5.5")

    config = WorkerConfig.from_env()

    assert config.default_model == "gpt-5.5"


def test_from_env_reports_missing_required_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(RuntimeError) as exc_info:
        WorkerConfig.from_env()

    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "OPENAI_API_KEY" in message
