from __future__ import annotations

from src.integrations.redaction import redact_headers


def test_redacts_authorization_header():
    headers = {"Authorization": "Bearer sk_live_secret123", "Content-Type": "application/json"}
    redacted = redact_headers(headers)

    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["Content-Type"] == "application/json"
    assert "sk_live_secret123" not in str(redacted)


def test_redaction_is_case_insensitive():
    headers = {"authorization": "Bearer sk_live_secret123"}
    redacted = redact_headers(headers)
    assert redacted["authorization"] == "***REDACTED***"


def test_redacts_cookie_and_api_key_variants():
    headers = {"X-Api-Key": "secret", "Cookie": "session=abc123", "Set-Cookie": "session=abc123"}
    redacted = redact_headers(headers)
    assert all(v == "***REDACTED***" for v in redacted.values())


def test_does_not_mutate_original_dict():
    headers = {"Authorization": "Bearer sk_live_secret123"}
    redact_headers(headers)
    assert headers["Authorization"] == "Bearer sk_live_secret123"
