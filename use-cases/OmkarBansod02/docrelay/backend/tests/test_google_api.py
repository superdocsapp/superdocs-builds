import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from docrelay.api.google import GoogleConnectionResponse, GoogleConnectionsResponse
from docrelay.app import create_app
from docrelay.core.config import Settings
from docrelay.core.logging import JsonFormatter, OAuthCallbackAccessLogFilter
from docrelay.domain.enums import ConnectionStatus


class StubDatabase:
    async def dispose(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


async def test_unconfigured_status_and_error_contracts_are_safe() -> None:
    app = create_app(settings=_settings(), database=StubDatabase())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status_response = await client.get("/api/v1/google/connections")
        authorize_response = await client.get(
            "/api/v1/google/oauth/authorize", follow_redirects=False
        )

    assert status_response.status_code == 200
    assert status_response.json() == {
        "oauth_configured": False,
        "selected_scopes": [
            "openid",
            "https://www.googleapis.com/auth/drive.file",
        ],
        "watch_scopes": [
            "openid",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "connections": [],
    }
    assert authorize_response.status_code == 503
    assert authorize_response.json()["error"]["code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"
    serialized = f"{status_response.text}{authorize_response.text}".lower()
    for forbidden in ("access_token", "refresh_token", "client_secret", "authorization: bearer"):
        assert forbidden not in serialized


def test_connection_api_model_has_no_credential_or_principal_fields() -> None:
    response = GoogleConnectionsResponse(
        oauth_configured=True,
        connections=(
            GoogleConnectionResponse(
                connection_id=uuid4(),
                status=ConnectionStatus.CONNECTED,
                granted_scopes=("openid", "https://www.googleapis.com/auth/drive.file"),
                last_validated_at=datetime.now(UTC),
            ),
        ),
    )
    payload = response.model_dump(mode="json")
    encoded = json.dumps(payload).lower()

    assert "connection_id" in encoded
    for forbidden in (
        "access_token",
        "refresh_token",
        "client_secret",
        "credential_reference",
        "provider_account_subject",
    ):
        assert forbidden not in encoded


def test_oauth_callback_access_log_filter_redacts_code_and_state() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/api/v1/google/oauth/callback?code=secret-code&state=secret-state",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    assert OAuthCallbackAccessLogFilter().filter(record)
    formatted = JsonFormatter().format(record)

    assert "secret-code" not in formatted
    assert "secret-state" not in formatted
    assert "[REDACTED]" in formatted


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> bool:
        return False


class CallbackDatabase:
    async def dispose(self) -> None:
        return None

    def sessions(self) -> _SessionContext:
        return _SessionContext()


async def test_successful_watch_oauth_callback_redirects_to_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    from docrelay.api import google as google_api

    class Service:
        async def complete_authorization(self, **_kwargs: object) -> object:
            return object()

    monkeypatch.setattr(google_api, "_runtime", lambda _request: object())
    monkeypatch.setattr(google_api, "_service", lambda **_kwargs: Service())

    app = create_app(settings=_settings(), database=CallbackDatabase())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/google/oauth/callback",
            params={"code": "ok", "state": "ok"},
            cookies={
                "docrelay_google_oauth_return": "/watch",
                "docrelay_google_oauth_nonce": "nonce",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/watch"
    assert "Google connection established" not in response.text
