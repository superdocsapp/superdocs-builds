"""Zoom webhook verification.

Two independent mechanisms, both keyed on the same secret token, per Zoom's
documented webhook contract (developers.zoom.us/docs/api/webhooks/):

1. The one-time `endpoint.url_validation` handshake, answered by hashing the
   `plainToken` Zoom sends — this is how Zoom confirms we hold the secret
   before it will deliver anything else.
2. Per-request signature verification (`x-zm-signature`) on every event after
   that, so a request merely claiming to be from Zoom cannot be logged or
   acted on.

Both are HMAC-SHA256 keyed by the *secret token*, not the OAuth client
secret — different value, different purpose.
"""

from __future__ import annotations

import hashlib
import hmac


def build_url_validation_response(secret_token: str, plain_token: str) -> dict[str, str]:
    encrypted_token = hmac.new(
        secret_token.encode(), plain_token.encode(), hashlib.sha256
    ).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted_token}


def verify_signature(
    secret_token: str, timestamp: str, raw_body: bytes, signature_header: str
) -> bool:
    """Verify `x-zm-signature` against `v0:{timestamp}:{raw_body}`.

    `raw_body` must be the exact bytes received, not a re-serialized JSON
    object — HMAC is sensitive to whitespace and key order, and a
    round-tripped `json.dumps` is not guaranteed to reproduce Zoom's bytes.
    """
    message = f"v0:{timestamp}:{raw_body.decode()}"
    computed = hmac.new(secret_token.encode(), message.encode(), hashlib.sha256).hexdigest()
    expected_header = f"v0={computed}"
    return hmac.compare_digest(expected_header, signature_header)


def build_rtms_signature(
    client_id: str, client_secret: str, meeting_uuid: str, rtms_stream_id: str
) -> str:
    """HMAC-SHA256 for the RTMS websocket signaling/media handshake —
    Milestone 4. A different scheme from both functions above: keyed on the
    OAuth *client secret*, not the webhook secret token, over
    `{client_id},{meeting_uuid},{rtms_stream_id}` rather than
    `v0:{timestamp}:{body}`. Source: developers.zoom.us/blog/
    realtime-mediastreams-websockets/ — see PROGRESS.md M4 for the full
    protocol trail this was built against.
    """
    message = f"{client_id},{meeting_uuid},{rtms_stream_id}"
    return hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
