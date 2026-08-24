from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import (
    GOOGLE_DRIVE_FILE_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_TOKEN_ENDPOINT,
    GOOGLE_WATCH_SCOPES,
    GoogleAuthorizationProfile,
    GoogleOAuthHTTPClient,
    build_authorization_url,
    frontend_oauth_redirect_url,
    new_pkce_verifier,
    oauth_return_path_for_profile,
    safe_oauth_return_path,
)


def test_authorization_url_uses_state_offline_access_least_privilege_and_pkce() -> None:
    verifier = new_pkce_verifier()
    url = build_authorization_url(
        client_id="client-id",
        redirect_uri="http://localhost:8000/api/v1/google/oauth/callback",
        state="unguessable-state",
        code_verifier=verifier,
    )
    query = parse_qs(urlparse(url).query)

    assert query["state"] == ["unguessable-state"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent select_account"]
    assert query["scope"] == [" ".join(GOOGLE_OAUTH_SCOPES)]
    assert query["scope"] == [f"openid {GOOGLE_DRIVE_FILE_SCOPE}"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] != verifier
    assert 43 <= len(verifier) <= 128


def test_watch_authorization_is_an_explicit_restricted_scope_upgrade() -> None:
    verifier = new_pkce_verifier()
    url = build_authorization_url(
        client_id="client-id",
        redirect_uri="http://localhost/callback",
        state="watch-state",
        code_verifier=verifier,
        scopes=GOOGLE_WATCH_SCOPES,
    )
    query = parse_qs(urlparse(url).query)

    assert query["scope"] == [" ".join(GOOGLE_WATCH_SCOPES)]
    assert GOOGLE_DRIVE_READONLY_SCOPE in query["scope"][0]
    assert query["include_granted_scopes"] == ["true"]
    assert GoogleAuthorizationProfile.WATCH.value == "watch"


def test_successful_watch_oauth_callback_returns_to_watch_page() -> None:
    assert oauth_return_path_for_profile(GoogleAuthorizationProfile.WATCH) == "/watch"
    assert oauth_return_path_for_profile(GoogleAuthorizationProfile.SINGLE_FILE) == "/"
    assert frontend_oauth_redirect_url(
        origins=["http://localhost:3000"],
        path="/watch",
    ) == "http://localhost:3000/watch"
    assert frontend_oauth_redirect_url(
        origins=["http://localhost:3000"],
        path="/",
    ) == "http://localhost:3000/"
    assert safe_oauth_return_path("https://evil.example/watch") == "/"
    assert safe_oauth_return_path("//localhost:3000/watch") == "/"
    assert safe_oauth_return_path(None) == "/"


async def test_refresh_accepts_unchanged_scope_omission() -> None:
    observed_form = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_form
        assert str(request.url) == GOOGLE_TOKEN_ENDPOINT
        observed_form = (await request.aread()).decode()
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleOAuthHTTPClient(
            http=http,
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
            redirect_uri="http://localhost/callback",
        )
        grant = await client.refresh_access_token(refresh_token=SecretStr("refresh-secret"))

    assert grant.access_token.get_secret_value() == "new-access-token"
    assert grant.scopes == ()
    assert "grant_type=refresh_token" in observed_form
    assert "refresh_token=refresh-secret" in observed_form


@pytest.mark.parametrize(
    ("oauth_error", "expected"),
    [
        ("invalid_grant", GoogleErrorCode.REAUTH_REQUIRED),
        ("temporarily_unavailable", GoogleErrorCode.UNAVAILABLE),
    ],
)
async def test_refresh_provider_errors_are_safely_classified(
    oauth_error: str, expected: GoogleErrorCode
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": oauth_error, "error_description": "secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleOAuthHTTPClient(
            http=http,
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
            redirect_uri="http://localhost/callback",
        )
        with pytest.raises(GoogleIntegrationError) as raised:
            await client.refresh_access_token(refresh_token=SecretStr("refresh-secret"))

    assert raised.value.code is expected
    assert "secret" not in raised.value.safe_message


async def test_expired_authorization_code_is_a_restartable_client_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleOAuthHTTPClient(
            http=http,
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
            redirect_uri="http://localhost/callback",
        )
        with pytest.raises(GoogleIntegrationError) as raised:
            await client.exchange_code(code="expired-code", code_verifier=new_pkce_verifier())

    assert raised.value.code is GoogleErrorCode.INVALID_OAUTH_STATE
