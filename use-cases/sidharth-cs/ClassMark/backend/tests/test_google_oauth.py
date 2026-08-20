"""Google OAuth tests — URL construction and token exchange, no network."""

import asyncio
import time
import urllib.parse

import httpx

from app.google.oauth import AuthStore, GoogleOAuth, SCOPES, TokenData


def _token(access_token, expires_at, refresh_token=None) -> TokenData:
    return TokenData(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def test_build_auth_url_contains_all_scopes_and_redirect():
    oauth = GoogleOAuth("cid", "csecret", "http://localhost:8020/api/auth/callback")
    url = oauth.build_auth_url("state123")
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))

    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == "cid"
    assert params["redirect_uri"] == "http://localhost:8020/api/auth/callback"
    assert params["response_type"] == "code"
    assert params["state"] == "state123"
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    for scope in SCOPES:
        assert scope in params["scope"]


def test_exchange_code_posts_to_token_endpoint():
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "access_token": "at1",
                "refresh_token": "rt1",
                "expires_in": 3600,
            },
        )

    async def run():
        oauth = GoogleOAuth(
            "cid",
            "csecret",
            "http://localhost:8020/api/auth/callback",
            transport=httpx.MockTransport(handler),
        )
        oauth._fetch_email = _fake_fetch_email  # avoid the userinfo network call
        token = await oauth.exchange_code("code123")
        assert token.access_token == "at1"
        assert token.refresh_token == "rt1"
        assert token.email == "teacher@test.edu"

    asyncio.run(run())
    assert seen["url"].startswith("https://oauth2.googleapis.com/token")


async def _fake_fetch_email(access_token: str) -> str:
    return "teacher@test.edu"


async def test_auth_store_hands_out_fresh_token_without_refresh():
    oauth = GoogleOAuth("cid", "csecret", "http://localhost:8020/api/auth/callback")

    class _NoRefreshOAuth:
        async def refresh(self, refresh_token):
            raise AssertionError("refresh must not be called for a fresh token")

    store = AuthStore(oauth)
    store._oauth = _NoRefreshOAuth()
    store.set("s1", _token("fresh", time.time() + 3600, refresh_token="rt1"))

    got = await store.get("s1")
    assert got.access_token == "fresh"


async def test_auth_store_refreshes_expired_token():
    oauth = GoogleOAuth("cid", "csecret", "http://localhost:8020/api/auth/callback")

    class _RefreshingOAuth:
        async def refresh(self, refresh_token):
            return _token("refreshed", time.time() + 3600, refresh_token=refresh_token)

    store = AuthStore(oauth)
    store._oauth = _RefreshingOAuth()
    store.set("s2", _token("stale", time.time() - 10, refresh_token="rt2"))

    got = await store.get("s2")
    assert got.access_token == "refreshed"


async def test_auth_store_expired_token_without_refresh_token_stays_stale():
    """No refresh token (e.g. a re-consent was revoked) — the store must
    hand back the stale token rather than crash; the API call will fail
    with 401 and the route will prompt re-auth."""
    oauth = GoogleOAuth("cid", "csecret", "http://localhost:8020/api/auth/callback")

    class _NoRefreshOAuth:
        async def refresh(self, refresh_token):
            raise AssertionError("refresh must not be called without a refresh token")

    store = AuthStore(oauth)
    store._oauth = _NoRefreshOAuth()
    store.set("s3", _token("stale", time.time() - 10, refresh_token=None))

    got = await store.get("s3")
    assert got.access_token == "stale"


async def test_auth_store_returns_none_for_unknown_session():
    oauth = GoogleOAuth("cid", "csecret", "http://localhost:8020/api/auth/callback")
    store = AuthStore(oauth)
    assert await store.get("missing") is None
