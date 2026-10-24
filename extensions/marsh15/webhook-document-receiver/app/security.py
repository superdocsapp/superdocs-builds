import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass


class SignatureError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedWebhook:
    provider: str
    event_id: str
    timestamp: int
    payload_sha256: str


_DELIVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_SIGNATURE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name.lower()) or headers.get(name)
    if not value:
        raise SignatureError(f"Missing required header: {name}")
    return value


def _parse_signature(raw: str, provider: str) -> str:
    if "," in raw:
        raise SignatureError("Multiple webhook signatures are not accepted")
    match = _SHA256_SIGNATURE.fullmatch(raw.strip())
    if match is None:
        raise SignatureError("Webhook signature must use sha256=<64 hex characters>")
    return match.group(1).lower()


def verify_webhook(
    *,
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    provider: str,
    signature_header: str,
    event_id_header: str,
    timestamp_header: str,
    tolerance_seconds: int,
    now: int | None = None,
) -> VerifiedWebhook:
    if provider not in {"generic-hmac", "github"}:
        raise SignatureError("Unsupported webhook provider")
    signature_value = _header(headers, signature_header)
    event_id = _header(headers, event_id_header)
    if _DELIVERY_ID.fullmatch(event_id) is None:
        raise SignatureError("Webhook delivery ID is malformed")
    current = int(time.time()) if now is None else now

    if provider == "github":
        timestamp = current
        signed_payload = body
    else:
        timestamp_raw = _header(headers, timestamp_header)
        try:
            timestamp = int(timestamp_raw)
        except ValueError as exc:
            raise SignatureError("Webhook timestamp must be Unix seconds") from exc
        if abs(current - timestamp) > tolerance_seconds:
            raise SignatureError("Webhook timestamp is outside the allowed tolerance")
        # The generic protocol binds the freshness timestamp, delivery identity,
        # and exact bytes. Otherwise a captured valid request could be replayed
        # under a new, unsigned delivery ID during the tolerance window.
        signed_payload = f"{timestamp}.{event_id}.".encode() + body

    supplied = _parse_signature(signature_value, provider)
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise SignatureError("Invalid webhook signature")
    return VerifiedWebhook(
        provider=provider,
        event_id=event_id,
        timestamp=timestamp,
        payload_sha256=hashlib.sha256(body).hexdigest(),
    )
