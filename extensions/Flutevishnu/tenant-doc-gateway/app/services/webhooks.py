"""Outgoing webhook delivery for job completion (optional, alongside polling).

If the caller supplied a webhook URL when starting a job, we POST the terminal
result to it. Payloads are signed with HMAC-SHA256 so the receiver can verify
authenticity (the secret is never sent, only the signature).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.logging import get_logger

_log = get_logger("webhooks")


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def send_webhook(url: str, payload: dict, *, secret: str, timeout: float = 10.0) -> bool:
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Signature": f"sha256={sign_payload(secret, body)}",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, content=body, headers=headers)
        # Graceful degradation: a webhook failure must never fail the job; the
        # result is still retrievable by polling. We log and move on.
        if response.status_code >= 400:
            _log.warning("webhook.non_2xx", url=url, status_code=response.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        _log.warning("webhook.failed", url=url, error=str(exc))
        return False
