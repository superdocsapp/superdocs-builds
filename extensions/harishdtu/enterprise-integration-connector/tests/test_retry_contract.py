"""
Retry contract tests. Each test hits the http_client directly (not through an
operation) so the retry behavior itself is isolated from any operation-level
logic. The infra-429/500 cases fall back to the hardcoded exponential-backoff-
with-cap in http_client._backoff (not itself configurable -- see that method)
so those two tests do take a couple of real seconds; every other case is
near-instant.
"""
import time

import httpx
import pytest

from connector.config import ConnectorConfig
from connector.errors import (
    AuthenticationError,
    NotFoundError,
    PayloadTooLargeError,
    ServerError,
    ValidationError,
)
from connector.errors import (
    TimeoutError as SDTimeoutError,
)
from connector.http_client import SuperDocsHTTPClient
from tests.conftest import FAKE_API_KEY, json_response


def _client_with(fake_server, **config_overrides) -> SuperDocsHTTPClient:
    config_overrides.setdefault("max_retries", 2)
    config = ConnectorConfig(api_key=FAKE_API_KEY, **config_overrides)
    return SuperDocsHTTPClient(config, transport=httpx.MockTransport(fake_server))


@pytest.mark.asyncio
async def test_429_application_honors_retry_after_exactly(fake_server):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.05"}, json={"detail": "quota exceeded"})
        return json_response(200, {"ok": True})

    fake_server.on("GET", "/v1/sessions", handler)
    client = _client_with(fake_server)

    started = time.monotonic()
    result = await client.get_json("/v1/sessions")
    elapsed = time.monotonic() - started

    assert result == {"ok": True}
    assert calls["n"] == 2
    assert elapsed >= 0.045  # honored the 0.05s Retry-After, not a shorter backoff


@pytest.mark.asyncio
async def test_429_infrastructure_no_retry_after_falls_back_to_backoff(fake_server):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="Rate exceeded")  # plain text, no Retry-After, no JSON body
        return json_response(200, {"ok": True})

    fake_server.on("GET", "/v1/sessions", handler)
    client = _client_with(fake_server)

    result = await client.get_json("/v1/sessions")
    assert result == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_500_retries_with_bounded_backoff(fake_server):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return json_response(500, {"detail": "internal error"})
        return json_response(200, {"ok": True})

    fake_server.on("GET", "/v1/sessions", handler)
    client = _client_with(fake_server, max_retries=3)

    result = await client.get_json("/v1/sessions")
    assert result == {"ok": True}
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_500_exhausts_retries_and_raises_typed_error(fake_server):
    fake_server.on("GET", "/v1/sessions", lambda r: json_response(500, {"detail": "still broken"}))
    client = _client_with(fake_server, max_retries=1)

    with pytest.raises(ServerError) as exc_info:
        await client.get_json("/v1/sessions")
    assert exc_info.value.status_code == 500
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_504_maps_to_typed_timeout_error(fake_server):
    fake_server.on("POST", "/v1/chat", lambda r: json_response(504, {"detail": "AI processing exceeded 30 minutes"}))
    client = _client_with(fake_server, max_retries=0)

    with pytest.raises(SDTimeoutError) as exc_info:
        await client.post_json("/v1/chat", {"message": "hi", "session_id": "s1"})
    assert exc_info.value.status_code == 504
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("status,error_cls", [
    (400, ValidationError),
    (401, AuthenticationError),
    (404, NotFoundError),
    (422, ValidationError),
])
@pytest.mark.asyncio
async def test_client_errors_are_not_retried(fake_server, status, error_cls):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return json_response(status, {"detail": "client error"})

    fake_server.on("GET", "/v1/sessions", handler)
    client = _client_with(fake_server, max_retries=3)

    with pytest.raises(error_cls) as exc_info:
        await client.get_json("/v1/sessions")

    assert calls["n"] == 1, f"status {status} should fail immediately, not retry"
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_413_is_not_blindly_retried_and_carries_suggested_action(fake_server):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return json_response(413, {
            "error_code": "request_too_large", "message_user": "File too large",
            "suggested_action": "split_request",
        })

    fake_server.on("POST", "/v1/documents/upload-base64", handler)
    client = _client_with(fake_server, max_retries=3)

    with pytest.raises(PayloadTooLargeError) as exc_info:
        await client.post_json("/v1/documents/upload-base64", {"filename": "x.pdf", "file_base64": "..."})

    assert calls["n"] == 1
    assert "split_request" in exc_info.value.detail
    assert exc_info.value.retryable is False
