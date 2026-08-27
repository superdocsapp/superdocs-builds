import hashlib
import hmac

import pytest

from app.security import SignatureError, verify_webhook

SECRET = "s" * 32
BODY = b'{"type":"invoice.paid"}'


def signed_headers(timestamp: int = 1_700_000_000) -> dict[str, str]:
    digest = hmac.new(
        SECRET.encode(), f"{timestamp}.evt_123.".encode() + BODY, hashlib.sha256
    ).hexdigest()
    return {
        "x-webhook-signature": f"sha256={digest}",
        "x-webhook-id": "evt_123",
        "x-webhook-timestamp": str(timestamp),
    }


def test_accepts_valid_signature() -> None:
    result = verify_webhook(
        body=BODY,
        headers=signed_headers(),
        secret=SECRET,
        provider="generic-hmac",
        signature_header="x-webhook-signature",
        event_id_header="x-webhook-id",
        timestamp_header="x-webhook-timestamp",
        tolerance_seconds=300,
        now=1_700_000_010,
    )
    assert result.event_id == "evt_123"
    assert result.provider == "generic-hmac"
    assert result.payload_sha256 == hashlib.sha256(BODY).hexdigest()


@pytest.mark.parametrize("mutation", [b" ", b"x"])
def test_rejects_tampered_payload(mutation: bytes) -> None:
    with pytest.raises(SignatureError, match="Invalid"):
        verify_webhook(
            body=BODY + mutation,
            headers=signed_headers(),
            secret=SECRET,
            provider="generic-hmac",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=300,
            now=1_700_000_010,
        )


def test_rejects_stale_timestamp() -> None:
    with pytest.raises(SignatureError, match="tolerance"):
        verify_webhook(
            body=BODY,
            headers=signed_headers(),
            secret=SECRET,
            provider="generic-hmac",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=300,
            now=1_700_000_301,
        )


def test_rejects_delivery_id_changed_after_signing() -> None:
    headers = signed_headers()
    headers["x-webhook-id"] = "evt_replayed_under_new_id"
    with pytest.raises(SignatureError, match="Invalid"):
        verify_webhook(
            body=BODY,
            headers=headers,
            secret=SECRET,
            provider="generic-hmac",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=300,
            now=1_700_000_010,
        )


@pytest.mark.parametrize(
    ("header_name", "header_value", "message"),
    [
        ("x-webhook-signature", "not-a-signature", "64 hex"),
        ("x-webhook-signature", "sha256=" + "a" * 64 + ",sha256=" + "b" * 64, "Multiple"),
        ("x-webhook-id", "../unsafe", "delivery ID"),
    ],
)
def test_rejects_malformed_security_headers(
    header_name: str, header_value: str, message: str
) -> None:
    headers = signed_headers()
    headers[header_name] = header_value

    with pytest.raises(SignatureError, match=message):
        verify_webhook(
            body=BODY,
            headers=headers,
            secret=SECRET,
            provider="generic-hmac",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=300,
            now=1_700_000_010,
        )


def test_rejects_unknown_provider() -> None:
    with pytest.raises(SignatureError, match="Unsupported"):
        verify_webhook(
            body=BODY,
            headers=signed_headers(),
            secret=SECRET,
            provider="generic",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=300,
            now=1_700_000_010,
        )


def test_github_known_signature_vector() -> None:
    result = verify_webhook(
        body=b"Hello, World!",
        headers={
            "x-hub-signature-256": (
                "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
            ),
            "x-github-delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
        },
        secret="It's a Secret to Everybody",
        provider="github",
        signature_header="x-hub-signature-256",
        event_id_header="x-github-delivery",
        timestamp_header="unused",
        tolerance_seconds=300,
        now=1_700_000_000,
    )

    assert result.provider == "github"
    assert result.payload_sha256 == hashlib.sha256(b"Hello, World!").hexdigest()
