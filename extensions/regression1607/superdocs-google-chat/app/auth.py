"""Verify that a webhook call really came from Google Chat.

Google Chat signs each request with a bearer JWT issued by
``chat@system.gserviceaccount.com`` whose audience is the value you configured on
the app's connection (your project number or the app URL). We verify it against
Google's public certs.

Auth is *opt-in*: leave ``GOOGLE_CHAT_AUDIENCE`` unset for local development and
every request is accepted; set it in production and unsigned/forged calls are
rejected. This keeps the tests key-free while still hardening the deployed app.
"""

from __future__ import annotations

CHAT_ISSUER = "chat@system.gserviceaccount.com"
_CERTS_URL = f"https://www.googleapis.com/service_accounts/v1/metadata/x509/{CHAT_ISSUER}"


def verify_request(authorization: str | None, audience: str | None) -> bool:
    if not audience:
        return True  # auth disabled (local / dev)
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization.split(" ", 1)[1]
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token
        claims = id_token.verify_token(
            token, g_requests.Request(), audience=audience, certs_url=_CERTS_URL)
    except Exception:
        return False
    return claims.get("email") == CHAT_ISSUER or claims.get("iss") == CHAT_ISSUER
