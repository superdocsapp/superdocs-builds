"""Prove the secrecy gate fails on things it is supposed to fail on.

A gate that has never been seen to reject anything is not a gate. Every case here is a
payload that *should* be refused; if the audit passes one, the test fails.

This exists because the first version of the audit passed a cassette that contained a real
account identifier. The identifier was nested inside a JSON-encoded string -- MCP tool
results carry their payload as text -- so the pattern walked straight past the escaped
quotes. The lesson generalised: check the escaped form too, and never trust a filter you
have not watched reject something.

It is the same argument as the mutation testing in Phase 4, applied to the one control
that has to hold before this repository can be public.
"""

from __future__ import annotations

import json

import pytest

from sdmock.scrub import audit, scrub_text, scrub_value

# Every value below is obviously synthetic and still matches the shape the scrubber
# hunts for, which is all the test needs. An earlier version used a real key as a
# fixture -- gitleaks caught it in CI, and the history was rewritten. The lesson is
# banal and worth writing down anyway: a leak test is exactly the place a real
# credential gets typed, because it is the one file where a credential looks like it
# belongs.
LEAKS = [
    pytest.param(
        '{"headers": {"authorization": "Bearer sk_EXAMPLEnotarealkey00000000000000"}}',
        "sk_", id="personal-api-key"),
    pytest.param(
        '{"key": "lce_EXAMPLEnotarealorgkey000"}', "lce_", id="organization-key"),
    pytest.param(
        '{"auth": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"}', "bearer",
        id="bearer-token"),
    pytest.param(
        '{"contact": "a.person@example-supplier.invalid"}', "email",
        id="personal-address"),
    pytest.param(
        '{"url": "https://s3.example.com/f.docx?X-Amz-Signature=deadbeefcafe1234"}',
        "signature", id="presigned-url-signature"),
    pytest.param(
        '{"account_id": "ffaf112f-40fa-4887-8a0c-5c1c3d4f14c2"}', "account identifier",
        id="account-id-plain"),
    # The one that actually got through.
    pytest.param(
        '{"content": [{"type": "text", "text": '
        '"{\\"account_id\\":\\"ffaf112f-40fa-4887-8a0c-5c1c3d4f14c2\\",'
        '\\"tier\\":\\"free\\"}"}]}',
        "account identifier", id="account-id-nested-in-json-string"),
    pytest.param(
        '{"text": "{\\"redemption_id\\":\\"476fb5cf-b0af-403b-986b-f57b310535f6\\"}"}',
        "account identifier", id="redemption-id-nested"),
]


@pytest.mark.parametrize("payload,expected", LEAKS)
def test_audit_rejects(payload: str, expected: str) -> None:
    problems = audit(payload)
    assert problems, f"the audit passed a payload it should have refused: {payload[:80]}"
    assert any(expected in problem.lower() for problem in problems), (
        f"refused for the wrong reason: {problems}"
    )


@pytest.mark.parametrize("payload,_expected", LEAKS)
def test_scrubbing_then_auditing_is_clean(payload: str, _expected: str) -> None:
    """Whatever the audit refuses, the scrubber must be able to clean."""
    cleaned = json.dumps(scrub_value(json.loads(scrub_text(payload))))
    assert not audit(cleaned), (
        f"scrubbed output still fails the audit: {audit(cleaned)}"
    )


def test_audit_passes_legitimate_content() -> None:
    """The gate must not cry wolf, or it gets switched off.

    Public constants and structural ids are load-bearing: an integrator handling a
    capacity refusal needs the support address, and replay needs session and job ids.
    """
    fine = json.dumps({
        "detail": {"contact_email": "hello@superdocs.app",
                   "error_code": "DOCUMENT_TOO_COMPLEX"},
        "session_id": "sdmock-review-001",
        "job_id": "12458c63-154c-4a71-9cf7-758797284e93",
        "change_id": "3478b121-b765-4b96-a8a3-bbc5c5f3b655",
        "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
        "account_id": "[REDACTED]",
    })
    assert not audit(fine), audit(fine)
