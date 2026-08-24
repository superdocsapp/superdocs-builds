import base64
import hashlib
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

from docrelay.integrations.google.errors import (
    GoogleErrorCode,
    GoogleIntegrationError,
    GoogleOAuthProviderError,
)

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OPENID_SCOPE = "openid"
GOOGLE_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SINGLE_FILE_SCOPES = (GOOGLE_OPENID_SCOPE, GOOGLE_DRIVE_FILE_SCOPE)
GOOGLE_WATCH_SCOPES = (
    GOOGLE_OPENID_SCOPE,
    GOOGLE_DRIVE_FILE_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
)
# Backward-compatible name for the normal, deliberately narrow connection flow.
GOOGLE_OAUTH_SCOPES = GOOGLE_SINGLE_FILE_SCOPES


class GoogleAuthorizationProfile(StrEnum):
    SINGLE_FILE = "single_file"
    WATCH = "watch"


OAUTH_RETURN_COOKIE = "docrelay_google_oauth_return"
OAUTH_ALLOWED_RETURN_PATHS = frozenset({"/", "/watch"})
DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"


def scopes_for_profile(profile: GoogleAuthorizationProfile) -> tuple[str, ...]:
    if profile is GoogleAuthorizationProfile.WATCH:
        return GOOGLE_WATCH_SCOPES
    return GOOGLE_SINGLE_FILE_SCOPES


def oauth_return_path_for_profile(profile: GoogleAuthorizationProfile) -> str:
    return "/watch" if profile is GoogleAuthorizationProfile.WATCH else "/"


def safe_oauth_return_path(value: str | None) -> str:
    return value if value in OAUTH_ALLOWED_RETURN_PATHS else "/"


def frontend_oauth_redirect_url(*, origins: Sequence[str], path: str | None) -> str:
    origin = origins[0] if origins else DEFAULT_FRONTEND_ORIGIN
    return f"{origin.rstrip('/')}{safe_oauth_return_path(path)}"


class OAuthContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OAuthTokenGrant(OAuthContract):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    token_type: str = "Bearer"
    # RFC 6749 permits a refresh response to omit ``scope`` when it is unchanged.
    # The initial authorization path still verifies the exact required scopes.
    scopes: tuple[str, ...] = ()
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime | None = None


class GoogleOAuthPort(Protocol):
    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokenGrant: ...

    async def refresh_access_token(self, *, refresh_token: SecretStr) -> OAuthTokenGrant: ...

    async def principal_subject(self, *, access_token: SecretStr) -> str: ...

    async def revoke(self, *, token: SecretStr) -> None: ...


def new_pkce_verifier() -> str:
    # token_urlsafe uses the unreserved URL alphabet and comfortably exceeds RFC
    # 7636's minimum entropy and length requirements.
    return secrets.token_urlsafe(64)[:96]


def pkce_s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_verifier: str,
    scopes: tuple[str, ...] = GOOGLE_OAUTH_SCOPES,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
            "state": state,
            "code_challenge": pkce_s256_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"


class GoogleOAuthHTTPClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        client_id: str,
        client_secret: SecretStr,
        redirect_uri: str,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokenGrant:
        response = await self._post_token(
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret.get_secret_value(),
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            during_refresh=False,
        )
        return self._parse_grant(response)

    async def refresh_access_token(self, *, refresh_token: SecretStr) -> OAuthTokenGrant:
        response = await self._post_token(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret.get_secret_value(),
                "refresh_token": refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
            },
            during_refresh=True,
        )
        return self._parse_grant(response)

    async def principal_subject(self, *, access_token: SecretStr) -> str:
        try:
            response = await self._http.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token.get_secret_value()}"},
            )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google identity service is unavailable",
                retryable=True,
            ) from exc
        if response.status_code == 401:
            raise GoogleIntegrationError(
                GoogleErrorCode.REAUTH_REQUIRED,
                "Google authorization could not identify the connected account",
            )
        if not response.is_success:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google identity service could not complete the request",
                retryable=response.status_code >= 500,
            )
        try:
            subject = response.json().get("sub")
        except (ValueError, AttributeError) as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google identity service returned an invalid response",
            ) from exc
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google identity service did not return a usable principal identifier",
            )
        return subject

    async def revoke(self, *, token: SecretStr) -> None:
        try:
            response = await self._http.post(
                GOOGLE_REVOCATION_ENDPOINT,
                data={"token": token.get_secret_value()},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google token revocation is unavailable",
                retryable=True,
            ) from exc
        if response.status_code == 200:
            return
        oauth_error = _oauth_error(response)
        if oauth_error == "invalid_token":
            return
        raise GoogleIntegrationError(
            GoogleErrorCode.UNAVAILABLE,
            "Google token revocation could not complete",
            retryable=response.status_code >= 500,
        )

    async def _post_token(self, form: dict[str, str], *, during_refresh: bool) -> dict[str, Any]:
        try:
            response = await self._http.post(
                GOOGLE_TOKEN_ENDPOINT,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.UNAVAILABLE,
                "Google OAuth token service is unavailable",
                retryable=True,
            ) from exc
        if not response.is_success:
            raise GoogleOAuthProviderError(
                _oauth_error(response) or "unknown_oauth_error",
                during_refresh=during_refresh,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google OAuth token service returned an invalid response",
            ) from exc
        if not isinstance(payload, dict):
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google OAuth token service returned an invalid response",
            )
        return payload

    @staticmethod
    def _parse_grant(payload: dict[str, Any]) -> OAuthTokenGrant:
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        scope = payload.get("scope")
        token_type = payload.get("token_type", "Bearer")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, int)
            or expires_in <= 0
            or str(token_type).lower() != "bearer"
        ):
            raise GoogleIntegrationError(
                GoogleErrorCode.INVALID_RESPONSE,
                "Google OAuth token response omitted required fields",
            )
        refresh_token = payload.get("refresh_token")
        refresh_expires_in = payload.get("refresh_token_expires_in")
        now = datetime.now(UTC)
        return OAuthTokenGrant(
            access_token=SecretStr(access_token),
            refresh_token=(
                SecretStr(refresh_token)
                if isinstance(refresh_token, str) and refresh_token
                else None
            ),
            token_type="Bearer",
            scopes=(tuple(sorted(set(scope.split()))) if isinstance(scope, str) and scope else ()),
            access_token_expires_at=now + timedelta(seconds=expires_in),
            refresh_token_expires_at=(
                now + timedelta(seconds=refresh_expires_in)
                if isinstance(refresh_expires_in, int) and refresh_expires_in > 0
                else None
            ),
        )


def _oauth_error(response: httpx.Response) -> str | None:
    try:
        value = response.json().get("error")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None
