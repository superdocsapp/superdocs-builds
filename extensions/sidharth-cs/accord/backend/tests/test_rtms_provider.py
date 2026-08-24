"""Locks in RTMSTranscriptProvider's behavior against a fake websocket
connector — no real network, same discipline as FakeSuperDocsClient and
the rest of this suite. Protocol shapes (msg_type values, field names,
signature scheme) match app/transcript/rtms_provider.py's own sourcing —
see PROGRESS.md M4.

Every scenario here was first proven by hand against the real
implementation during development (not written blind, then hoped to pass)
— see the M4 section of PROGRESS.md for that trail, including one real bug
this exact process caught (a silently-stalled connection never reconnecting
because recv() alone never raised — fixed with read_timeout_seconds)."""

import asyncio
import json

import pytest

from app.transcript.provider import (
    STATUS_CONNECTING,
    STATUS_DEGRADED,
    STATUS_LIVE,
    STATUS_NOT_STARTED,
    STATUS_STOPPED,
)
from app.transcript.rtms_provider import RTMSTranscriptProvider
from app.core.security import build_rtms_signature


class _FakeSocket:
    """A live, queue-backed fake — recv() blocks until something is put on
    its queue, exactly like a real socket waiting for the next frame."""

    def __init__(self, recv_queue: asyncio.Queue) -> None:
        self.sent: list[dict] = []
        self._recv_queue = recv_queue
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        return await self._recv_queue.get()

    async def close(self) -> None:
        self.closed = True


class _DeadSocket:
    """Simulates a genuinely closed connection — every recv() raises,
    matching how the real `websockets` library behaves post-disconnect."""

    async def send(self, message: str) -> None:
        pass

    async def recv(self) -> str:
        raise ConnectionError("connection is dead")

    async def close(self) -> None:
        pass


class _SilentSocket:
    """Simulates a stalled-but-not-erroring connection (e.g. a network
    partition) — recv() never returns and never raises. Only a read
    timeout can detect this; a bare `except` around recv() cannot."""

    async def send(self, message: str) -> None:
        pass

    async def recv(self) -> str:
        await asyncio.sleep(100)

    async def close(self) -> None:
        pass


def _make_success_connector():
    """A connector that routes signaling vs. media URLs to two separate
    fake sockets, each backed by its own queue the test can push onto."""
    signaling_recv: asyncio.Queue = asyncio.Queue()
    media_recv: asyncio.Queue = asyncio.Queue()
    sockets: dict[str, _FakeSocket] = {}

    async def connector(url: str):
        key = "signaling" if "signal" in url else "media"
        socket = _FakeSocket(signaling_recv if key == "signaling" else media_recv)
        sockets[key] = socket
        return socket

    return connector, signaling_recv, media_recv, sockets


def test_build_rtms_signature_is_deterministic_hmac_sha256():
    sig = build_rtms_signature("cid", "secret", "meeting-1", "stream-1")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)
    assert sig == build_rtms_signature("cid", "secret", "meeting-1", "stream-1")
    assert sig != build_rtms_signature("cid", "secret", "meeting-1", "stream-2")


def test_status_starts_not_started():
    p = RTMSTranscriptProvider("cid", "secret")
    assert p.status() == STATUS_NOT_STARTED


def test_start_is_non_blocking_and_sets_connecting():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret", connect_timeout_seconds=10)
        await p.start({"meeting_uuid": "u1"})
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_CONNECTING


def test_connect_timeout_degrades_when_webhook_never_arrives():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret", connect_timeout_seconds=0.05)
        await p.start({"meeting_uuid": "u1"})
        await asyncio.sleep(0.15)
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_DEGRADED


def test_submit_works_before_during_and_after_degradation():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret", connect_timeout_seconds=0.05)
        await p.start({"meeting_uuid": "u1"})
        before = await p.submit("said while still connecting")
        await asyncio.sleep(0.15)
        assert p.status() == STATUS_DEGRADED
        after = await p.submit("said while degraded")
        return p, before, after

    p, before, after = asyncio.run(run())
    assert before.sequence == 1
    assert after.sequence == 2  # one shared counter, no collision with real frames
    assert before.is_final and after.is_final


def test_submit_rejects_blank_text():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret")
        with pytest.raises(ValueError):
            await p.submit("   ")

    asyncio.run(run())


def test_full_handshake_reaches_live_and_delivers_a_frame():
    async def run():
        connector, signaling_recv, media_recv, sockets = _make_success_connector()
        p = RTMSTranscriptProvider("cid", "secret", websocket_connector=connector)
        await p.start({"meeting_uuid": "muid-1"})

        task = asyncio.create_task(
            p.on_rtms_started(rtms_stream_id="stream-1", server_urls="wss://signal.example.com")
        )
        await asyncio.sleep(0.05)
        await signaling_recv.put(
            json.dumps(
                {
                    "msg_type": 2,
                    "status_code": 0,
                    "media_server": {"server_urls": {"transcript": "wss://media.example.com"}},
                }
            )
        )
        await asyncio.sleep(0.05)

        await media_recv.put(
            json.dumps({"msg_type": 17, "content": {"user_name": "Alice", "data": "hello"}})
        )
        event = await asyncio.wait_for(p.events().__anext__(), timeout=1)
        status_while_live = p.status()  # captured before stop() changes it
        await p.stop()
        task.cancel()
        return status_while_live, sockets, event

    status_while_live, sockets, event = asyncio.run(run())
    assert status_while_live == STATUS_LIVE
    # signaling: msg_type 1, correct fields
    assert sockets["signaling"].sent[0]["msg_type"] == 1
    assert sockets["signaling"].sent[0]["meeting_uuid"] == "muid-1"
    assert sockets["signaling"].sent[0]["rtms_stream_id"] == "stream-1"
    # media: handshake (msg_type 3, media_type 8) then ready (msg_type 7)
    assert sockets["media"].sent[0] == {
        "msg_type": 3,
        "protocol_version": 1,
        "sequence": 0,
        "meeting_uuid": "muid-1",
        "rtms_stream_id": "stream-1",
        "signature": sockets["media"].sent[0]["signature"],
        "media_type": 8,
    }
    assert sockets["media"].sent[1] == {"msg_type": 7}
    assert event.text == "hello"
    assert event.speaker == "Alice"
    assert event.is_final is True


def test_signaling_rejection_leaves_status_for_watchdog():
    async def run():
        connector, signaling_recv, _media_recv, _sockets = _make_success_connector()
        p = RTMSTranscriptProvider(
            "cid", "secret", connect_timeout_seconds=0.1, websocket_connector=connector
        )
        await p.start({"meeting_uuid": "u1"})
        task = asyncio.create_task(
            p.on_rtms_started(rtms_stream_id="s1", server_urls="wss://signal.example.com")
        )
        await asyncio.sleep(0.02)
        await signaling_recv.put(json.dumps({"msg_type": 2, "status_code": 1}))  # rejected
        await asyncio.sleep(0.2)  # past the connect timeout
        task.cancel()
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_DEGRADED  # never raised, watchdog resolved it


def test_missing_payload_fields_is_a_safe_noop():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret", connect_timeout_seconds=10)
        await p.start({"meeting_uuid": "u1"})
        await p.on_rtms_started(rtms_stream_id="", server_urls="")
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_CONNECTING  # untouched — no socket ever attempted


def test_double_webhook_delivery_is_idempotent():
    async def run():
        connector, signaling_recv, _media_recv, sockets = _make_success_connector()
        connect_count = {"signaling": 0, "media": 0}
        real_connector = connector

        async def counting_connector(url):
            key = "signaling" if "signal" in url else "media"
            connect_count[key] += 1
            return await real_connector(url)

        p = RTMSTranscriptProvider("cid", "secret", websocket_connector=counting_connector)
        await p.start({"meeting_uuid": "u1"})
        task = asyncio.create_task(
            p.on_rtms_started(rtms_stream_id="s1", server_urls="wss://signal.example.com")
        )
        await asyncio.sleep(0.05)
        await signaling_recv.put(
            json.dumps(
                {
                    "msg_type": 2,
                    "status_code": 0,
                    "media_server": {"server_urls": {"transcript": "wss://media.example.com"}},
                }
            )
        )
        await asyncio.sleep(0.05)
        assert p.status() == STATUS_LIVE

        # Zoom webhook retries are expected/documented — a second delivery
        # for the same meeting must not open a second socket.
        await p.on_rtms_started(rtms_stream_id="s1", server_urls="wss://signal.example.com")
        await p.stop()
        task.cancel()
        return connect_count

    connect_count = asyncio.run(run())
    assert connect_count == {"signaling": 1, "media": 1}


def test_dead_connection_reconnects_then_degrades_after_exhaustion():
    async def run():
        connect_calls = []

        async def always_failing_connector(url):
            connect_calls.append(url)
            raise ConnectionError("server unreachable")

        p = RTMSTranscriptProvider(
            "cid",
            "secret",
            reconnect_attempts=2,
            reconnect_backoff_seconds=0.01,
            websocket_connector=always_failing_connector,
        )
        p._media_socket = _DeadSocket()
        p._transcript_url = "wss://media.example.com"
        await asyncio.wait_for(p._read_frames(), timeout=2)
        return p, connect_calls

    p, connect_calls = asyncio.run(run())
    assert p.status() == STATUS_DEGRADED
    assert len(connect_calls) == 2  # matches reconnect_attempts


def test_silent_stall_is_caught_by_read_timeout_not_left_hanging():
    """The bug this test locks in: a connection that neither errors nor
    delivers data (network partition) must still be detected — only a read
    timeout can catch it, since recv() itself never raises. Found live
    during M4 development; see this file's own module docstring."""

    async def run():
        connect_calls = []

        async def always_failing_connector(url):
            connect_calls.append(url)
            raise ConnectionError("server unreachable")

        p = RTMSTranscriptProvider(
            "cid",
            "secret",
            read_timeout_seconds=0.1,
            reconnect_attempts=1,
            reconnect_backoff_seconds=0.01,
            websocket_connector=always_failing_connector,
        )
        p._media_socket = _SilentSocket()
        p._transcript_url = "wss://media.example.com"
        await asyncio.wait_for(p._read_frames(), timeout=2)
        return p, connect_calls

    p, connect_calls = asyncio.run(run())
    assert p.status() == STATUS_DEGRADED
    assert len(connect_calls) == 1


def test_keep_alive_ping_gets_a_timestamped_reply():
    async def run():
        connector, signaling_recv, media_recv, sockets = _make_success_connector()
        p = RTMSTranscriptProvider("cid", "secret", websocket_connector=connector)
        await p.start({"meeting_uuid": "u1"})
        task = asyncio.create_task(
            p.on_rtms_started(rtms_stream_id="s1", server_urls="wss://signal.example.com")
        )
        await asyncio.sleep(0.05)
        await signaling_recv.put(
            json.dumps(
                {
                    "msg_type": 2,
                    "status_code": 0,
                    "media_server": {"server_urls": {"transcript": "wss://media.example.com"}},
                }
            )
        )
        await asyncio.sleep(0.05)

        await media_recv.put(json.dumps({"msg_type": 12}))
        await asyncio.sleep(0.05)
        await p.stop()
        task.cancel()
        return sockets

    sockets = asyncio.run(run())
    replies = [m for m in sockets["media"].sent if m.get("msg_type") == 13]
    assert len(replies) == 1
    assert "timestamp" in replies[0]


def test_stop_is_safe_whether_or_not_ever_connected():
    async def run():
        p = RTMSTranscriptProvider("cid", "secret")
        await p.stop()  # never called start()
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_STOPPED
