from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from google.auth.transport import requests
from google.oauth2 import id_token

from series_bible.config import Settings


class AuthenticationError(ValueError):
    pass


def issue_token(user_id: UUID, settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise AuthenticationError("JWT_SECRET must be configured for Google sign-in")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=settings.jwt_expiry_hours)},
        settings.jwt_secret.get_secret_value(), algorithm="HS256",
    )


def verify_token(token: str, settings: Settings) -> dict[str, Any]:
    if settings.jwt_secret is None:
        raise AuthenticationError("JWT authentication is not configured")
    try:
        return jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise AuthenticationError("Invalid or expired session") from error


def verify_google_credential(credential: str, settings: Settings) -> dict[str, Any]:
    if not settings.google_client_id:
        raise AuthenticationError("GOOGLE_CLIENT_ID is not configured")
    try:
        claims = id_token.verify_oauth2_token(credential, requests.Request(), settings.google_client_id)
    except ValueError as error:
        raise AuthenticationError("Google sign-in could not be verified") from error
    if not claims.get("email_verified") or not claims.get("sub") or not claims.get("email"):
        raise AuthenticationError("Google account must have a verified email address")
    return claims