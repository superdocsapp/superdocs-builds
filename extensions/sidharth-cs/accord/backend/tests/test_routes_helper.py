"""Control-channel route tests (Architecture B spike).

Covers the HTTP control routes. The WSS round-trip (helper ACK advancing
helper_status) is exercised live (see the spike's local verification) and
through the manual Zoom-panel test — a unit test of the WSS ACK would need
the authenticated helper socket interleaved with HTTP requests, which the
TestClient portal supports but adds little beyond the live proof.

No token is required by the HTTP routes (only the WSS handshake checks it).
"""

import base64
import os

# Same import-order discipline as test_routes_review: the first test module
# to import app.main fixes the lru-cached settings, so the webhook secret
# must be pinned here too or test_webhooks sees a stale token.
os.environ.setdefault("ZOOM_WEBHOOK_SECRET_TOKEN", "test-secret-token")

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def _enc(uuid: str) -> str:
    return base64.urlsafe_b64encode(uuid.encode()).decode().rstrip("=")


def test_helper_start_without_helper_returns_503_and_marks_disconnected():
    with TestClient(app) as client:
        enc = _enc("helper-test-1")
        r = client.post(f"/api/meetings/{enc}/helper/start")
        assert r.status_code == 503
        # No helper is connected, so the session must NOT claim listening.
        st = client.get(f"/api/meetings/{enc}/state").json()
        assert st["helper_status"] == "disconnected"
        assert st["helper_connected"] is False


def test_helper_stop_returns_200_even_without_helper():
    with TestClient(app) as client:
        enc = _enc("helper-test-2")
        r = client.post(f"/api/meetings/{enc}/helper/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "stopping"


def test_ws_helper_requires_auth_token():
    # Empty token → the handshake is refused with 4401, not accepted as an
    # open unauthenticated socket.
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/api/ws/helper?token="):
                pass
        assert excinfo.value.code == 4401
