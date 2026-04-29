from __future__ import annotations

import base64
import hmac
import os
from typing import Any

from .config import API_KEY_ENV, SECRET_NAME


def _extract_api_key_from_basic_auth(value: str) -> str | None:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception:
        return None

    _, separator, password = decoded.partition(":")
    if not separator:
        return None
    return password


def candidate_api_keys(headers: Any) -> list[str]:
    api_keys: list[str] = []

    x_api_key = headers.get("x-api-key")
    if x_api_key:
        api_keys.append(x_api_key.strip())

    authorization = headers.get("authorization")
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        scheme = scheme.lower()
        credentials = credentials.strip()
        if scheme == "bearer" and credentials:
            api_keys.append(credentials)
        elif scheme == "basic" and credentials:
            basic_key = _extract_api_key_from_basic_auth(credentials)
            if basic_key:
                api_keys.append(basic_key)

    return api_keys


def assert_authorized(headers: Any) -> None:
    expected = os.environ.get(API_KEY_ENV)
    if not expected:
        raise RuntimeError(f"Modal Secret {SECRET_NAME!r} must define {API_KEY_ENV}")
    try:
        expected_bytes = expected.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            f"Modal Secret {SECRET_NAME!r} value {API_KEY_ENV} must contain only ASCII characters"
        ) from exc

    for candidate in candidate_api_keys(headers):
        try:
            candidate_bytes = candidate.encode("ascii")
        except UnicodeEncodeError:
            continue
        if hmac.compare_digest(candidate_bytes, expected_bytes):
            return

    from fastapi import HTTPException

    raise HTTPException(
        status_code=401,
        detail="Missing or invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )

