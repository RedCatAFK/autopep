from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest


def test_run_stream_endpoint_is_defined() -> None:
    from autopep_worker import run_stream

    assert run_stream is not None


def test_start_run_endpoint_is_defined() -> None:
    from autopep_worker import start_run

    assert start_run is not None


def test_run_autopep_agent_function_is_defined() -> None:
    from autopep_worker import run_autopep_agent

    assert run_autopep_agent is not None


def _mint_token(secret: str, payload: dict) -> str:
    header = (
        base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"),
        )
        .rstrip(b"=")
        .decode("utf-8")
    )
    body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .rstrip(b"=")
        .decode("utf-8")
    )
    message = f"{header}.{body}".encode("utf-8")
    sig = (
        base64.urlsafe_b64encode(
            hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest(),
        )
        .rstrip(b"=")
        .decode("utf-8")
    )
    return f"{header}.{body}.{sig}"


def test_verify_run_stream_jwt_accepts_valid_token(monkeypatch) -> None:
    from autopep_worker import _verify_run_stream_jwt

    secret = "test-modal-webhook-secret"
    monkeypatch.setenv("AUTOPEP_MODAL_WEBHOOK_SECRET", secret)
    run_id = "11111111-1111-4111-8111-111111111111"
    token = _mint_token(
        secret,
        {"runId": run_id, "userId": "user-1", "exp": int(time.time()) + 600},
    )

    _verify_run_stream_jwt(token, run_id)


def test_verify_run_stream_jwt_rejects_wrong_secret(monkeypatch) -> None:
    from autopep_worker import _verify_run_stream_jwt
    from fastapi import HTTPException

    monkeypatch.setenv(
        "AUTOPEP_MODAL_WEBHOOK_SECRET", "test-modal-webhook-secret",
    )
    run_id = "11111111-1111-4111-8111-111111111111"
    bad_token = _mint_token(
        "different-secret",
        {"runId": run_id, "userId": "user-1", "exp": int(time.time()) + 600},
    )

    with pytest.raises(HTTPException) as excinfo:
        _verify_run_stream_jwt(bad_token, run_id)
    assert excinfo.value.status_code == 401


def test_verify_run_stream_jwt_rejects_expired_token(monkeypatch) -> None:
    from autopep_worker import _verify_run_stream_jwt
    from fastapi import HTTPException

    secret = "test-modal-webhook-secret"
    monkeypatch.setenv("AUTOPEP_MODAL_WEBHOOK_SECRET", secret)
    run_id = "11111111-1111-4111-8111-111111111111"
    token = _mint_token(
        secret,
        {"runId": run_id, "userId": "user-1", "exp": int(time.time()) - 10},
    )

    with pytest.raises(HTTPException) as excinfo:
        _verify_run_stream_jwt(token, run_id)
    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


def test_verify_run_stream_jwt_rejects_runid_mismatch(monkeypatch) -> None:
    from autopep_worker import _verify_run_stream_jwt
    from fastapi import HTTPException

    secret = "test-modal-webhook-secret"
    monkeypatch.setenv("AUTOPEP_MODAL_WEBHOOK_SECRET", secret)
    token = _mint_token(
        secret,
        {
            "runId": "11111111-1111-4111-8111-111111111111",
            "userId": "user-1",
            "exp": int(time.time()) + 600,
        },
    )

    with pytest.raises(HTTPException) as excinfo:
        _verify_run_stream_jwt(
            token, "22222222-2222-4222-8222-222222222222",
        )
    assert excinfo.value.status_code == 401
