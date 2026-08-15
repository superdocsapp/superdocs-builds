"""
All tests mock at the HTTP transport boundary via httpx.MockTransport, which
SuperDocsHTTPClient accepts as an injectable `transport` (see http_client.py's
constructor). This exercises the connector's real request-building, response-
parsing, retry, and error-mapping logic end to end -- only the actual network
call is faked. No test requires a real SUPERDOCS_API_KEY.

`FakeSuperDocsServer` is a tiny request router: register a handler per
(method, path) and it dispatches based on what the connector actually sends,
including reading the request body -- so tests can assert on exactly what the
connector serialized, not just what it claims to have sent.
"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from connector.config import ConnectorConfig
from connector.http_client import SuperDocsHTTPClient

FAKE_API_KEY = "sk_test_0000000000000000000000000000"


class FakeSuperDocsServer:
    """A minimal request router used as an httpx.MockTransport handler."""

    def __init__(self):
        self._handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handlers[(method.upper(), path)] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method.upper(), request.url.path)
        handler = self._handlers.get(key)
        if handler is None:
            return httpx.Response(404, json={"detail": f"no fake handler registered for {key}"})
        return handler(request)

    def last_request_json(self) -> dict:
        return json.loads(self.requests[-1].content)


def json_response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body)


@pytest.fixture
def fake_server() -> FakeSuperDocsServer:
    return FakeSuperDocsServer()


@pytest.fixture
def client(fake_server: FakeSuperDocsServer):
    config = ConnectorConfig(api_key=FAKE_API_KEY, max_retries=2)
    transport = httpx.MockTransport(fake_server)
    c = SuperDocsHTTPClient(config, transport=transport)
    yield c


@pytest.fixture
def fast_config() -> ConnectorConfig:
    """A ConnectorConfig with tiny poll/backoff intervals so retry/poll tests
    run in milliseconds instead of real seconds."""
    return ConnectorConfig(
        api_key=FAKE_API_KEY,
        max_retries=2,
        poll_initial_interval_seconds=0.01,
        poll_max_interval_seconds=0.02,
        poll_backoff_factor=1.5,
        poll_jitter_ratio=0.1,
        max_poll_seconds=2,
        callback_max_attempts=3,
        callback_initial_interval_seconds=0.01,
        callback_max_interval_seconds=0.02,
        callback_backoff_factor=2.0,
    )


@pytest.fixture
def mock_callback_transport():
    """
    WebhookCallbackDispatcher intentionally builds its own short-lived
    httpx.AsyncClient per delivery attempt (see callbacks.py) rather than
    accepting an injected client, since a real dispatcher has no reason to
    share a client instance with the SuperDocs API client. For tests, this
    fixture monkeypatches connector.callbacks.httpx.AsyncClient for its
    duration so those short-lived clients use a given httpx.MockTransport
    instead of touching the real network, then restores the real AsyncClient
    afterward regardless of test outcome.
    """
    import httpx as _httpx

    import connector.callbacks as callbacks_module
    real_async_client = _httpx.AsyncClient

    def _install(transport: httpx.AsyncBaseTransport):
        callbacks_module.httpx.AsyncClient = lambda *a, **kw: real_async_client(*a, **{**kw, "transport": transport})

    yield _install
    callbacks_module.httpx.AsyncClient = real_async_client
