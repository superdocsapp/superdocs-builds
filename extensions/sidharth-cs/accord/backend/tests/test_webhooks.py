"""Milestone 0's one load-bearing check: the webhook handshake and signature
verification actually do what Zoom's docs say, since a mistake here either
locks Zoom out permanently (handshake) or lets a forged request be logged and
trusted (signature) — see zoom-app/backend/app/core/security.py.
"""

import hashlib
import hmac
import json
import os

os.environ["ZOOM_WEBHOOK_SECRET_TOKEN"] = "test-secret-token"

from fastapi.testclient import TestClient

from app.drafting.session import MeetingSession, _sessions
from app.main import app
from app.transcript.rtms_provider import RTMSTranscriptProvider

client = TestClient(app)
SECRET = "test-secret-token"


def _signed_post(body: dict, timestamp: str = "1700000000"):
    raw = json.dumps(body).encode()
    message = f"v0:{timestamp}:{raw.decode()}"
    signature = "v0=" + hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/zoom",
        content=raw,
        headers={
            "content-type": "application/json",
            "x-zm-request-timestamp": timestamp,
            "x-zm-signature": signature,
        },
    )


def test_url_validation_handshake_returns_correct_encrypted_token():
    body = {"event": "endpoint.url_validation", "payload": {"plainToken": "abc123"}}
    response = client.post("/webhooks/zoom", json=body)

    assert response.status_code == 200
    expected_encrypted = hmac.new(SECRET.encode(), b"abc123", hashlib.sha256).hexdigest()
    assert response.json() == {"plainToken": "abc123", "encryptedToken": expected_encrypted}


def test_correctly_signed_event_is_accepted():
    body = {"event": "meeting.rtms_started", "payload": {"meeting_uuid": "u1"}}
    response = _signed_post(body)
    assert response.status_code == 200


def test_missing_signature_is_rejected():
    body = {"event": "meeting.rtms_started", "payload": {"meeting_uuid": "u1"}}
    response = client.post("/webhooks/zoom", json=body)
    assert response.status_code == 401


def test_tampered_body_is_rejected():
    raw = json.dumps({"event": "meeting.rtms_started", "payload": {"meeting_uuid": "u1"}}).encode()
    message = f"v0:1700000000:{raw.decode()}"
    signature = "v0=" + hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    tampered = json.dumps({"event": "meeting.rtms_started", "payload": {"meeting_uuid": "attacker"}}).encode()
    response = client.post(
        "/webhooks/zoom",
        content=tampered,
        headers={
            "content-type": "application/json",
            "x-zm-request-timestamp": "1700000000",
            "x-zm-signature": signature,
        },
    )
    assert response.status_code == 401


# ---- Milestone 4: meeting.rtms_started/rtms_stopped dispatch --------------


def _register_rtms_session(meeting_uuid: str) -> RTMSTranscriptProvider:
    """Registers a session with a real RTMSTranscriptProvider active,
    bypassing get_or_create_session's factory (not what's under test
    here) — same direct-construction pattern test_session.py already uses
    for MeetingSession. client=None is fine: webhook dispatch never
    touches it."""
    provider = RTMSTranscriptProvider("cid", "csecret")
    session = MeetingSession(meeting_uuid, client=None, provider=provider, manual_provider=provider)
    _sessions[meeting_uuid] = session
    return provider


def test_rtms_started_dispatches_to_the_active_rtms_provider():
    provider = _register_rtms_session("rtms-dispatch-1")
    calls = []

    async def fake_on_rtms_started(*, rtms_stream_id, server_urls):
        calls.append((rtms_stream_id, server_urls))

    provider.on_rtms_started = fake_on_rtms_started

    body = {
        "event": "meeting.rtms_started",
        "payload": {
            "meeting_uuid": "rtms-dispatch-1",
            "rtms_stream_id": "stream-42",
            "server_urls": "wss://signal.example.com",
        },
    }
    response = _signed_post(body)

    assert response.status_code == 200
    assert calls == [("stream-42", "wss://signal.example.com")]


def test_rtms_started_for_manual_active_session_is_a_safe_noop():
    # No session registered for this meeting_uuid at all — matches what
    # get_session already returns (None) for any meeting whose panel never
    # loaded, Manual-active or otherwise.
    body = {"event": "meeting.rtms_started", "payload": {"meeting_uuid": "no-such-meeting"}}
    response = _signed_post(body)
    assert response.status_code == 200  # unchanged from before M4 — see test above it


def test_rtms_stopped_only_stops_an_rtms_shaped_provider():
    provider = _register_rtms_session("rtms-dispatch-2")
    calls = []

    async def fake_stop():
        calls.append("stopped")

    provider.stop = fake_stop

    body = {"event": "meeting.rtms_stopped", "payload": {"meeting_uuid": "rtms-dispatch-2"}}
    response = _signed_post(body)

    assert response.status_code == 200
    assert calls == ["stopped"]


def test_rtms_dispatch_never_crashes_on_a_malformed_payload():
    _register_rtms_session("rtms-dispatch-3")
    body = {"event": "meeting.rtms_started", "payload": {"meeting_uuid": "rtms-dispatch-3"}}
    # payload has no rtms_stream_id/server_urls — RTMSTranscriptProvider's
    # own on_rtms_started() logs and no-ops for this (see test_rtms_provider.py);
    # the webhook route must still return 200, not crash.
    response = _signed_post(body)
    assert response.status_code == 200
