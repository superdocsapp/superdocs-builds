"""Google OAuth 2.0 — web application flow, implemented with httpx only.

Token storage is server-side and in-memory, keyed by a session id that the
browser holds in a signed cookie (Starlette SessionMiddleware). Access
tokens never reach the frontend; the backend attaches them to Classroom and
Drive API calls itself.

Scopes are the minimum the workflow needs:
- classroom.courses.readonly            list the teacher's courses
- classroom.coursework.students.readonly read submissions/attachments
- classroom.coursework.students          modifyAttachments + return
- drive.readonly                         download the student's attached file
- drive.file                             upload the reviewed document
"""

from __future__ import annotations

import time
import urllib.parse

import httpx
from pydantic import BaseModel

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

REFRESH_BUFFER_SECONDS = 60


class TokenData(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: float  # epoch seconds; 0 means "unknown, assume valid"
    token_type: str = "Bearer"
    email: str = ""


class GoogleOAuth:
    """Builds authorization URLs and exchanges/refreshes tokens. Stateless —
    the AuthStore below owns what tokens exist for which session."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # transport is injectable for tests (httpx.MockTransport); the
        # token/userinfo calls build their own short-lived client each time.
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._transport = transport

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # force a fresh consent screen so we get a refresh token
            "state": state,
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> TokenData:
        """Exchanges an authorization code for tokens. Raises
        httpx.HTTPStatusError if Google rejects the code."""
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            r = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            r.raise_for_status()
            payload = r.json()
        email = await self._fetch_email(payload["access_token"])
        return TokenData(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=time.time() + int(payload.get("expires_in", 3600)),
            email=email,
        )

    async def refresh(self, refresh_token: str) -> TokenData:
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            r = await client.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )
            r.raise_for_status()
            payload = r.json()
        return TokenData(
            access_token=payload["access_token"],
            refresh_token=refresh_token,
            expires_at=time.time() + int(payload.get("expires_in", 3600)),
        )

    async def _fetch_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if r.status_code == 200:
                return r.json().get("email", "")
        return ""


class AuthStore:
    """In-memory token store keyed by session id. A backend restart clears
    it and the teacher re-authenticates — an accepted, stated limitation
    (same in-memory decision zoom-app and Task 1 make)."""

    def __init__(self, oauth: GoogleOAuth) -> None:
        self._oauth = oauth
        self._tokens: dict[str, TokenData] = {}

    def set(self, session_id: str, token: TokenData) -> None:
        self._tokens[session_id] = token

    def delete(self, session_id: str) -> None:
        self._tokens.pop(session_id, None)

    async def get(self, session_id: str) -> TokenData | None:
        token = self._tokens.get(session_id)
        if token is None:
            return None
        if (
            token.expires_at
            and time.time() + REFRESH_BUFFER_SECONDS > token.expires_at
            and token.refresh_token
        ):
            refreshed = await self._oauth.refresh(token.refresh_token)
            refreshed.email = token.email
            self._tokens[session_id] = refreshed
            return refreshed
        return token
