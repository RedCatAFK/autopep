import hashlib
import hmac

from julia_agent.main import verify_signature


def test_verify_signature_accepts_sha256_hmac() -> None:
    body = b'{"runId":"run_1"}'
    secret = "super-secret"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert verify_signature(body, f"sha256={digest}", secret)
    assert verify_signature(body, digest, secret)


def test_verify_signature_rejects_missing_or_wrong_secret() -> None:
    body = b"{}"
    digest = hmac.new(b"right", body, hashlib.sha256).hexdigest()

    assert not verify_signature(body, f"sha256={digest}", "")
    assert not verify_signature(body, "sha256=bad", "right")
