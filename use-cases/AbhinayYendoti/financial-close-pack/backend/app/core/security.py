"""Signed session tokens.

Replaces the previous model where every handler hardcoded `actor="Abhinay"` and any
caller could sign off as anybody by putting a name in the request body. The actor is
now derived from a signed session token and can never be supplied by the client.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException, status

from .config import settings

_log = logging.getLogger(__name__)


class Principal(dict):
    """The authenticated caller: {"id", "name", "role"}."""

    @property
    def id(self) -> str:
        return str(self["id"])

    @property
    def name(self) -> str:
        return str(self["name"])

    @property
    def role(self) -> str:
        return str(self["role"])


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    if settings.session_secret:
        return settings.session_secret.encode("utf-8")

    path = Path(settings.storage_dir) / ".session_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # O_EXCL so concurrent workers cannot clobber each other on first boot.
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(secrets.token_urlsafe(48))
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def issue_session(user: dict[str, Any], ttl_seconds: int | None = None) -> dict[str, Any]:
    ttl = ttl_seconds or settings.session_ttl_seconds
    payload = {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "exp": int(time.time()) + ttl,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return {"token": f"{body}.{signature}", "expires_in": ttl, "user": user}


def verify_session(token: str) -> Principal:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        body, signature = token.split(".", 1)
    except ValueError:
        raise invalid from None

    expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise invalid

    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        raise invalid from None

    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        raise invalid

    return Principal(id=payload["id"], name=payload["name"], role=payload["role"])


# --------------------------------------------------------------------------------------
# Clerk
# --------------------------------------------------------------------------------------

# Clerk's default session token carries `sub` but no display name, and sign-offs are
# attributed to a person by name. The profile is fetched once per user from the Backend
# API and cached, so attribution costs one request per user per process, not one per call.
_PROFILE_TTL_SECONDS = 600
_profiles: dict[str, tuple[float, dict[str, str]]] = {}
_jwks_client: Any = None


def _clerk_jwks() -> Any:
    global _jwks_client
    if _jwks_client is None:
        import jwt

        # PyJWKClient caches the key set and refetches on an unknown kid, which is what
        # makes Clerk's key rotation a non-event here.
        _jwks_client = jwt.PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
    return _jwks_client


def reset_clerk_cache_for_tests() -> None:
    global _jwks_client
    _jwks_client = None
    _profiles.clear()


def _clerk_profile(user_id: str) -> dict[str, str]:
    cached = _profiles.get(user_id)
    if cached and cached[0] > time.time():
        return cached[1]

    profile = {"name": user_id, "role": "Controller"}
    try:
        import httpx

        response = httpx.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            timeout=10,
        )
        if response.status_code == 200:
            body = response.json()
            names = [body.get("first_name"), body.get("last_name")]
            full = " ".join(part for part in names if part).strip()
            emails = body.get("email_addresses") or []
            email = emails[0].get("email_address") if emails else None
            profile["name"] = full or body.get("username") or email or user_id
            metadata = body.get("public_metadata") or {}
            if metadata.get("role"):
                profile["role"] = str(metadata["role"])
    except Exception:
        # A profile lookup failure must not lock a validly-authenticated user out; the
        # token was already verified cryptographically. Fall back to the user id.
        pass

    _profiles[user_id] = (time.time() + _PROFILE_TTL_SECONDS, profile)
    return profile


def verify_clerk_token(token: str) -> Principal:
    import jwt

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired Clerk session",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        signing_key = _clerk_jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            # Clerk session tokens carry no `aud`, so there is nothing to verify against;
            # the issuer check plus the instance-scoped signing key is the binding.
            options={"verify_aud": False, "require": ["exp", "iat", "sub"]},
            leeway=5,
        )
    except Exception as exc:
        # The client is told nothing beyond "invalid or expired" - anything more is a
        # probing oracle. The operator, though, needs to know *which* failure this was:
        # an expiry race, a bad issuer and an unreachable JWKS endpoint are three very
        # different problems that were previously indistinguishable in the log.
        _log.warning("Clerk token rejected: %s: %s", type(exc).__name__, exc)
        raise invalid from None

    user_id = str(claims.get("sub") or "")
    if not user_id:
        raise invalid

    profile = _clerk_profile(user_id)
    return Principal(id=user_id, name=profile["name"], role=profile["role"])


def get_current_user(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    # With Clerk configured it is the only accepted issuer. Falling back to the local
    # HMAC token would leave the demo identity as a live bypass of real authentication.
    if settings.clerk_enabled:
        return verify_clerk_token(token)
    return verify_session(token)
