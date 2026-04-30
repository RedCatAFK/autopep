from julia_agent.config import WorkerConfig


def test_worker_config_derives_r2_endpoint_from_account_id(monkeypatch):
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("R2_ACCOUNT_ID", "account123")

    config = WorkerConfig.from_env()

    assert config.r2_endpoint_url == "https://account123.r2.cloudflarestorage.com"


def test_worker_config_prefers_explicit_r2_endpoint(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "account123")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://custom.example.test")

    config = WorkerConfig.from_env()

    assert config.r2_endpoint_url == "https://custom.example.test"
