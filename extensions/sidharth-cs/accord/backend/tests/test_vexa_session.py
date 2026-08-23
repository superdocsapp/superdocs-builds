"""Vexa end-to-end-at-session-layer coverage: Vexa segments entering the
EXISTING MeetingSession pipeline (Batcher → classifier → SuperDocs →
draft), the explicit start/stop-listening lifecycle on the session, the
provider exposure in state_snapshot, and the HTTP listen routes.

Same fakes as test_session.py (FakeSuperDocsClient — no network, no key)
plus the same injected httpx transport / fake websocket as
test_vexa_provider.py (never a real Vexa service). The route tests use
the same TestClient + direct _sessions registration pattern as
test_routes_review.py.
"""

from __future__ import annotations

import asyncio
import base64
import os

os.environ.setdefault("ZOOM_WEBHOOK_SECRET_TOKEN", "test-secret-token")

import httpx
from fastapi.testclient import TestClient

from app.drafting.session import MeetingSession, _sessions
from app.main import app
from app.superdocs.schemas import (
    ChatAsyncResponse,
    ChunkDiff,
    DocumentChanges,
    JobResult,
    JobStatusResponse,
    UploadResponse,
)
from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.vexa_provider import VexaTranscriptProvider

BASE = "https://vexa.example"


class FakeSocket:
    """Minimal websocket stand-in, same as test_vexa_provider.py's.
    frame_delay spaces deliveries out so the Batcher's silence-gap flush
    (0.05s in these tests) separates them into distinct batches."""

    def __init__(self, frames: list[dict], frame_delay: float = 0.0) -> None:
        self._frames = list(frames)
        self._frame_delay = frame_delay

    async def send(self, raw: str) -> None:
        pass

    async def recv(self) -> str:
        if self._frames:
            if self._frame_delay:
                await asyncio.sleep(self._frame_delay)
            return __import__("json").dumps(self._frames.pop(0))
        await asyncio.sleep(3600)

    async def close(self) -> None:
        pass


class DroppingSocket:
    """WS connector that fails instantly — keeps route tests off the
    network: the consumer falls back to the injected httpx transport."""

    async def send(self, raw: str) -> None:
        pass

    async def recv(self):
        raise ConnectionError("no network in tests")

    async def close(self) -> None:
        pass


def _ws_connector(socket):
    async def connect(url, **kwargs):
        return socket

    return connect


class FakeSuperDocsClient:
    """Stands in for app.superdocs.client.SuperDocsClient — same shape as
    test_session.py's fake; only the chat/upload surface is needed here."""

    def __init__(self) -> None:
        self.chat_messages: list[str] = []
        self.next_updated_html = "<h1>Meeting Draft</h1><p>Drafting begins.</p>"

    async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
        await asyncio.sleep(0)
        return UploadResponse(session_id=session_id, html=self.next_updated_html)

    async def chat_async(self, *, message, session_id, approval_mode="auto", model_tier=None, thinking_depth=None):
        await asyncio.sleep(0)
        self.chat_messages.append(message)
        return ChatAsyncResponse(job_id=f"job{len(self.chat_messages)}", session_id=session_id)

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        # Same wire shape as test_session.py's fake: real pydantic schemas,
        # because _handle_batch calls .model_dump() on each change.
        return JobStatusResponse(
            job_id=job_id,
            status="completed",
            result=JobResult(
                document_changes=DocumentChanges(
                    updated_html=self.next_updated_html,
                    changes=[ChunkDiff(operation="update", chunk_id="c1")],
                )
            ),
        )


def _vexa_provider(socket=None) -> VexaTranscriptProvider:
    return VexaTranscriptProvider(
        BASE,
        "test-key",
        poll_interval_seconds=0.01,
        # Longer than the 0.1s frame_delay the pipeline test uses, so a
        # delivery gap between frames isn't mistaken for a stalled socket.
        read_timeout_seconds=0.5,
        reconnect_attempts=0,
        reconnect_backoff_seconds=0.01,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(201, json={"id": 7})),
            base_url=BASE,
        ),
        websocket_connector=_ws_connector(socket or DroppingSocket()),
    )


def _vexa_session(
    client: FakeSuperDocsClient, socket=None
) -> tuple[MeetingSession, VexaTranscriptProvider]:
    provider = _vexa_provider(socket)
    session = MeetingSession(
        "test-meeting-uuid",
        client,
        provider,
        manual_provider=provider,
        silence_gap_seconds=0.05,
        size_ceiling_chars=10_000,
        max_wait_seconds=10,
        poll_interval_seconds=0.01,
    )
    return session, provider


def test_vexa_segments_drive_the_existing_draft_pipeline():
    """The correction flow at session level: two spoken utterances enter
    via Vexa and the untouched M3 pipeline turns each into a draft edit —
    no manual input involved."""
    client = FakeSuperDocsClient()
    client.next_updated_html = "<h1>Meeting Draft</h1><p>Start date: November 15th.</p>"
    socket = FakeSocket(
        [
            {"type": "transcript", "confirmed": [{"speaker": "Client", "text": "November 1st."}]},
            {
                "type": "transcript",
                "confirmed": [{"speaker": "Client", "text": "Correction. November 15th."}],
            },
        ],
        frame_delay=0.1,  # > silence_gap_seconds, so they are two batches
    )

    async def run():
        session, provider = _vexa_session(client, socket)
        provider._stabilizer._stability_seconds = 0.0
        await session.start()
        await session.start_listening(meeting_number="84335626851")
        # Wait for both WS segments to flush through Batcher + pipeline.
        for _ in range(300):
            if len(session.activity) >= 2:
                break
            await asyncio.sleep(0.02)
        await session.stop_listening()
        return session

    session = asyncio.run(run())
    assert [e.text for e in session.transcript_history] == [
        "November 1st.",
        "Correction. November 15th.",
    ]
    assert len(client.chat_messages) == 2  # two batches, two SuperDocs edits
    assert session.draft_version == 2
    assert session.activity[-1]["summary"] == "Correction. November 15th."
    # The final draft reflects the correction (the fake's post-edit HTML).
    assert "November 15th." in session.current_draft_html


def test_manual_submit_stays_open_on_a_vexa_session():
    """manual_provider is set because Vexa supports submit() — the manual
    fallback route keeps working without any provider change."""
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _vexa_session(client)
        await session.start()
        event = await provider.submit("typed fallback input")
        return event.text

    assert asyncio.run(run()) == "typed fallback input"


def test_start_listening_returns_connecting_and_snapshot_exposes_provider():
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _vexa_session(client)
        await session.start()
        status = await session.start_listening(meeting_number="84335626851")
        status_before_stop = provider.status()
        snapshot = session.state_snapshot()
        await session.stop_listening()
        return status, snapshot, session, provider, status_before_stop

    status, snapshot, session, provider, status_before_stop = asyncio.run(run())
    assert status == "connecting"
    assert status_before_stop == "connecting"
    # manual_provider is set (Vexa supports submit()) — that is what makes
    # the /state route expose {"name": "vexa", "status": "connecting"}.
    assert session.manual_provider is provider
    assert snapshot["meeting_uuid"] == "test-meeting-uuid"


def test_stop_listening_returns_stopped():
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _vexa_session(client)
        await session.start()
        await session.start_listening(meeting_number="84335626851")
        status = await session.stop_listening()
        return status

    assert asyncio.run(run()) == "stopped"


# ---- HTTP routes -------------------------------------------------------------


def _encode(meeting_uuid: str) -> str:
    return base64.urlsafe_b64encode(meeting_uuid.encode()).decode().rstrip("=")


client = TestClient(app)
client.__enter__()


def test_listen_route_returns_connecting_for_vexa_session():
    _register_vexa("routes-listen-1")
    response = client.post(
        f"/api/meetings/{_encode('routes-listen-1')}/listen",
        json={"meeting_number": "84335626851"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "connecting"}


def test_state_route_exposes_vexa_provider_and_status():
    _register_vexa("routes-state-1")
    response = client.get(f"/api/meetings/{_encode('routes-state-1')}/state")
    assert response.status_code == 200
    assert response.json()["provider"] == {"name": "vexa", "status": "not_started"}


def test_listen_route_without_meeting_number_degrades_honestly():
    _register_vexa("routes-listen-2")
    response = client.post(f"/api/meetings/{_encode('routes-listen-2')}/listen", json={})
    # Provider requires a meeting number/URL — never a silent no-op.
    assert response.json()["status"] == "degraded"


def test_listen_route_409_on_manual_session():
    provider = ManualTranscriptProvider()
    _sessions["routes-listen-3"] = MeetingSession(
        "routes-listen-3", FakeSuperDocsClient(), provider, manual_provider=provider
    )
    response = client.post(f"/api/meetings/{_encode('routes-listen-3')}/listen", json={})
    assert response.status_code == 409


def test_listen_stop_route_returns_stopped():
    _register_vexa("routes-listen-4")
    response = client.post(f"/api/meetings/{_encode('routes-listen-4')}/listen/stop")
    assert response.status_code == 200
    assert response.json() == {"status": "stopped"}


def _register_vexa(meeting_uuid: str) -> MeetingSession:
    provider = _vexa_provider()
    session = MeetingSession(
        meeting_uuid, FakeSuperDocsClient(), provider, manual_provider=provider
    )
    _sessions[meeting_uuid] = session
    return session


def test_start_listening_passes_passcode_through_to_vexa():
    """Session-level passthrough: passcode from the route body reaches the
    provider's POST /bots payload (Vexa's native field) and is cleared after
    the attempt settles."""
    import json as _json

    sent = []

    async def run():
        provider = VexaTranscriptProvider(
            BASE,
            "test-key",
            poll_interval_seconds=0.01,
            read_timeout_seconds=0.5,
            reconnect_attempts=0,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda req: sent.append(req) or httpx.Response(201, json={"id": 7})
                ),
                base_url=BASE,
            ),
            websocket_connector=_ws_connector(DroppingSocket()),
        )
        session = MeetingSession(
            "test-pwd-meeting",
            FakeSuperDocsClient(),
            provider,
            manual_provider=provider,
        )
        await session.start()
        await session.start_listening(
            meeting_number="84335626851", passcode="ephemeral-pwd"
        )
        await asyncio.sleep(0.05)
        await session.stop_listening()
        return provider

    provider = asyncio.run(run())
    spawn = next(r for r in sent if r.method == "POST" and r.url.path == "/bots")
    assert _json.loads(spawn.content)["passcode"] == "ephemeral-pwd"
    assert provider._passcode is None  # cleared — nothing persisted


def test_listen_route_accepts_optional_passcode():
    _register_vexa("routes-pwd-1")
    response = client.post(
        f"/api/meetings/{_encode('routes-pwd-1')}/listen",
        json={"meeting_number": "84335626851", "passcode": "route-pwd"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "connecting"}
