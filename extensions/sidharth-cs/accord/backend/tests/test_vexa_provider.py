"""VexaTranscriptProvider unit coverage — against an injected httpx
transport (httpx.MockTransport) and a fake websocket connector, NEVER a
real Vexa service. Locks in the adapter's half of the Milestone 6
contract, exactly like test_rtms_provider.py does for RTMS's websocket
flow with its own fake connector.

The HTTP payloads asserted here are the ones verified against the CURRENT
Vexa source (Vexa-ai/vexa v0.12, bot_spawn/router.py + the sealed api.v1
schemas) — see PROGRESS.md M6 for the trail.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.transcript.provider import (
    STATUS_CONNECTING,
    STATUS_DEGRADED,
    STATUS_LIVE,
    STATUS_NOT_STARTED,
    STATUS_STOPPED,
    TranscriptEvent,
)
from app.transcript.vexa_provider import TranscriptStabilizer, VexaTranscriptProvider

BASE = "https://vexa.example"


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)


class FakeSocket:
    """Minimal websocket stand-in: yields canned JSON frames, records sends,
    blocks on recv once the frame list is exhausted (so the provider's read
    timeout is what ends a quiet connection, like a real stalled socket)."""

    def __init__(self, frames: list[dict]) -> None:
        self._frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if self._frames:
            return json.dumps(self._frames.pop(0))
        await asyncio.sleep(3600)

    async def close(self) -> None:
        self.closed = True


def _ws_connector(socket: FakeSocket):
    async def connect(url, **kwargs):
        return socket

    return connect


def _provider(
    *,
    transport_handler=None,
    socket=None,
    base_url=BASE,
    api_key="test-key",
    poll_interval_seconds=0.01,
    read_timeout_seconds=0.05,
    reconnect_attempts=0,
    reconnect_backoff_seconds=0.01,
) -> VexaTranscriptProvider:
    p = VexaTranscriptProvider(
        base_url,
        api_key,
        poll_interval_seconds=poll_interval_seconds,
        read_timeout_seconds=read_timeout_seconds,
        reconnect_attempts=reconnect_attempts,
        reconnect_backoff_seconds=reconnect_backoff_seconds,
        http_client=_transport(transport_handler) if transport_handler else None,
        websocket_connector=_ws_connector(socket) if socket else None,
    )
    p._stabilizer._stability_seconds = 0.0  # immediate emit for tests
    return p


def _ok_handler(**overrides):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=overrides.get("bots_response", {"id": 7, "status": "requested"}))

    return handler


# ---- initialization / configuration ---------------------------------------


def test_name_and_initial_status():
    provider = _provider()
    assert provider.name == "vexa"
    assert provider.status() == STATUS_NOT_STARTED


def test_missing_config_reports_degraded_without_any_http_call():
    calls = []
    handler = _ok_handler()
    provider = _provider(transport_handler=lambda req: calls.append(req) or handler(req))
    provider._api_base_url = ""
    provider._api_key = ""
    assert provider._configured is False

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="1234567890")

    asyncio.run(run())
    assert provider.status() == STATUS_DEGRADED
    assert calls == []  # never touched the network
    # Manual fallback stays open even in the degraded state.
    event = asyncio.run(provider.submit("still works"))
    assert isinstance(event, TranscriptEvent)


def test_start_records_meeting_but_does_not_spawn_a_bot():
    """Opening the panel must NOT start listening — the bot lifecycle is
    the explicit Start-listening action's job."""
    calls = []
    provider = _provider(
        transport_handler=lambda req: calls.append(req) or httpx.Response(201, json={"id": 1})
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert provider.status() == STATUS_NOT_STARTED
    assert calls == []


def test_begin_listening_requires_meeting_identifier():
    provider = _provider(transport_handler=_ok_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening()

    asyncio.run(run())
    assert provider.status() == STATUS_DEGRADED


# ---- bot spawn -------------------------------------------------------------


def test_begin_listening_posts_the_verified_bots_payload():
    requests = []
    provider = _provider(
        transport_handler=lambda req: requests.append(req)
        or httpx.Response(201, json={"id": 7, "status": "requested"})
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        await provider.stop()

    asyncio.run(run())
    spawn = next(r for r in requests if r.method == "POST" and r.url.path == "/bots")
    assert json.loads(spawn.content) == {
        "platform": "zoom",
        "native_meeting_id": "84335626851",
        "meeting_url": "https://zoom.us/j/84335626851",
        "bot_name": "Live Deliverable",
        "language": "en",
        "transcribe_enabled": True,
    }
    assert spawn.headers["x-api-key"] == "test-key"


def test_spawn_failure_degrades_without_raising():
    provider = _provider(transport_handler=lambda req: httpx.Response(500, text="boom"))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")

    asyncio.run(run())
    assert provider.status() == STATUS_DEGRADED


def test_stop_deletes_the_bot_and_returns_to_stopped():
    requests = []
    provider = _provider(
        transport_handler=lambda req: requests.append(req)
        or httpx.Response(201, json={"id": 7, "status": "requested"})
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.02)
        await provider.stop()

    asyncio.run(run())
    stop = next(r for r in requests if r.method == "DELETE")
    assert stop.url.path == "/bots/zoom/84335626851"
    assert provider.status() == STATUS_STOPPED


# ---- transcript ingestion ---------------------------------------------------


def test_ws_confirmed_segments_reach_the_stream_in_order():
    socket = FakeSocket(
        [
            {"type": "transcript", "confirmed": [{"speaker": "Client", "text": "First."}]},
            {
                "type": "transcript",
                "confirmed": [{"speaker": "Consultant", "text": "Second."}],
            },
        ]
    )
    provider = _provider(socket=socket, transport_handler=_ok_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        stream = provider.events()
        first = await asyncio.wait_for(anext(stream), timeout=1)
        second = await asyncio.wait_for(anext(stream), timeout=1)
        await provider.stop()
        return first, second

    first, second = asyncio.run(run())
    assert isinstance(first, TranscriptEvent)
    assert first.speaker == "Client"
    assert first.text == "First."
    assert second.text == "Second."
    assert second.sequence > first.sequence
    assert first.is_final is True
    assert socket.sent[0]["action"] == "subscribe"
    assert socket.sent[0]["meetings"] == [{"platform": "zoom", "native_id": "84335626851"}]


def test_first_segment_flips_connecting_to_live():
    socket = FakeSocket(
        [{"type": "transcript", "confirmed": [{"speaker": "Client", "text": "Hello."}]}]
    )
    provider = _provider(socket=socket, transport_handler=_ok_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        assert provider.status() == STATUS_CONNECTING
        await asyncio.wait_for(anext(provider.events()), timeout=1)
        await asyncio.sleep(0.02)
        status = provider.status()
        await provider.stop()
        return status

    assert asyncio.run(run()) == STATUS_LIVE


def test_pending_segments_are_never_emitted():
    socket = FakeSocket(
        [
            {
                "type": "transcript",
                "pending": [{"speaker": "Client", "text": "November fif..."}],
                "confirmed": [{"speaker": "Client", "text": "November 15th."}],
            },
            {"type": "transcript", "pending": [{"speaker": "Client", "text": "Corr..."}]},
        ]
    )
    provider = _provider(socket=socket, transport_handler=_ok_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        stream = provider.events()
        only = await asyncio.wait_for(anext(stream), timeout=1)
        await provider.stop()
        return only

    only = asyncio.run(run())
    assert only.text == "November 15th."


def test_polling_fallback_emits_completed_segments_and_skips_duplicates():
    """WS unavailable → polling takes over; the same segment returned by
    repeated polls is emitted exactly once (dedup by speaker/text/start)."""
    doc = {
        "segments": [
            {"speaker": "Client", "text": "Workday.", "completed": True, "start": 1.0},
            {
                "speaker": "Client",
                "text": "November 15th.",
                "completed": True,
                "absolute_start_time": "2026-08-08T10:00:05Z",
            },
        ]
    }
    provider = _provider(
        transport_handler=lambda req: httpx.Response(200, json=doc),
        reconnect_attempts=0,
        poll_interval_seconds=0.01,
    )
    provider._stabilizer._stability_seconds = 0.0  # emit immediately for test

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        stream = provider.events()
        first = await asyncio.wait_for(anext(stream), timeout=1)
        second = await asyncio.wait_for(anext(stream), timeout=1)
        await asyncio.sleep(0.03)  # several polls re-read the same doc
        await provider.stop()
        return first, second

    first, second = asyncio.run(run())
    assert first.text == "Workday."
    assert second.text == "November 15th."
    assert provider.status() == STATUS_STOPPED


def test_ws_drop_with_exhausted_reconnects_falls_back_to_polling():
    class DroppingSocket:
        async def send(self, raw):
            pass

        async def recv(self):
            raise ConnectionError("refused")

        async def close(self):
            pass

    doc = {"segments": [{"speaker": "Client", "text": "AWS.", "completed": True}]}
    provider = _provider(
        socket=DroppingSocket(),
        transport_handler=lambda req: httpx.Response(200, json=doc),
        reconnect_attempts=1,
        reconnect_backoff_seconds=0.01,
    )

    async def run():
        provider._stabilizer._stability_seconds = 0.0
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        stream = provider.events()
        event = await asyncio.wait_for(anext(stream), timeout=1)
        await provider.stop()
        return event

    event = asyncio.run(run())
    assert event.text == "AWS."  # arrived via the polling fallback


def test_repeated_poll_failures_degrades():
    provider = _provider(transport_handler=lambda req: httpx.Response(503, text="no"))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.2)
        await provider.stop()

    asyncio.run(run())
    assert provider.status() == STATUS_STOPPED  # stop wins over degrade


def test_poll_failures_alone_reach_degraded():
    provider = _provider(transport_handler=lambda req: httpx.Response(503, text="no"))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        # Let the poll loop exceed _MAX_POLL_FAILURES (5 × 0.01s sleeps).
        await asyncio.sleep(0.15)

    asyncio.run(run())
    assert provider.status() == STATUS_DEGRADED


def test_meeting_status_message_drives_live_and_degraded():
    socket = FakeSocket(
        [
            {"type": "meeting.status", "meeting": {"id": 7}, "payload": {"status": "active"}},
            {"type": "transcript", "confirmed": [{"speaker": "A", "text": "hi"}]},
        ]
    )
    provider = _provider(socket=socket, transport_handler=_ok_handler())

    async def run():
        provider._stabilizer._stability_seconds = 0.0
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.wait_for(anext(provider.events()), timeout=1)
        await asyncio.sleep(0.02)
        status_after_live = provider.status()
        await provider.stop()
        return status_after_live

    assert asyncio.run(run()) == STATUS_LIVE


def test_needs_human_help_status_is_degraded():
    socket = FakeSocket(
        [{"type": "meeting.status", "payload": {"status": "needs_human_help"}}]
    )
    provider = _provider(socket=socket, transport_handler=_ok_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        status = provider.status()
        await provider.stop()
        return status

    assert asyncio.run(run()) == STATUS_DEGRADED


# ---- passcode handling (Milestone 6: passcode-protected meetings) -----------


def _router_handler(**overrides):
    """Routes by method+path: /bots → 201 with meeting id, transcripts →
    404, /meetings/{id} → overridable meeting detail (default: active)."""

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "POST" and p == "/bots":
            return httpx.Response(201, json=overrides.get("bots_response", {"id": 7, "status": "requested"}))
        if p == "/transcripts/zoom/84335626851":
            return httpx.Response(404, json={"detail": "not found"})
        if p == "/meetings/7":
            return httpx.Response(
                200,
                json=overrides.get(
                    "meeting_detail",
                    {"id": 7, "status": "joining", "data": {}},
                ),
            )
        return httpx.Response(200, json={})

    return handler


def test_no_passcode_keeps_request_unchanged():
    """Without a passcode the POST /bots payload must be exactly as before
    (no passcode key at all)."""
    requests = []
    provider = _provider(transport_handler=lambda req: requests.append(req) or httpx.Response(201, json={"id": 7}))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        await provider.stop()

    asyncio.run(run())
    spawn = next(r for r in requests if r.method == "POST" and r.url.path == "/bots")
    payload = json.loads(spawn.content)
    assert "passcode" not in payload


def test_passcode_is_sent_in_payload_and_cleared_after_spawn():
    requests = []
    provider = _provider(transport_handler=lambda req: requests.append(req) or httpx.Response(201, json={"id": 7}))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851", passcode="s3cret-pwd")
        payload_after_spawn = provider._passcode
        await asyncio.sleep(0.05)
        await provider.stop()
        payload_after_stop = provider._passcode
        return payload_after_spawn, payload_after_stop

    after_spawn, after_stop = asyncio.run(run())
    spawn = next(r for r in requests if r.method == "POST" and r.url.path == "/bots")
    assert json.loads(spawn.content)["passcode"] == "s3cret-pwd"
    # Attempt-scoped: cleared the moment the spawn request settled, and on stop.
    assert after_spawn is None
    assert after_stop is None


def test_passcode_never_appears_in_logs(caplog):
    provider = _provider(transport_handler=_router_handler())

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851", passcode="super-secret-value")
        await asyncio.sleep(0.2)
        await provider.stop()

    asyncio.run(run())
    assert "super-secret-value" not in caplog.text


def test_passcode_required_detection_via_meeting_detail():
    provider = _provider(
        transport_handler=_router_handler(
            meeting_detail={
                "id": 7,
                "status": "failed",
                "data": {
                    "failure_stage": "joining",
                    "completion_reason": "failed",
                    "diagnostics": "[Zoom Web] passcode_required: meeting requires a passcode",
                },
            }
        )
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        for _ in range(200):
            if provider.status() == "passcode_required":
                break
            await asyncio.sleep(0.02)
        status = provider.status()
        await provider.stop()
        return status

    assert asyncio.run(run()) == "passcode_required"


def test_generic_join_failure_stays_degraded_not_passcode_required():
    """A failed meeting WITHOUT the passcode_required marker must resolve
    to DEGRADED, never be masked as passcode-required."""
    provider = _provider(
        transport_handler=_router_handler(
            meeting_detail={
                "id": 7,
                "status": "failed",
                "data": {"failure_stage": "joining", "completion_reason": "failed"},
            }
        )
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.15)
        status = provider.status()
        await provider.stop()
        return status

    assert asyncio.run(run()) == "degraded"


def test_retry_from_passcode_required_sends_passcode():
    """The panel retries with the passcode; the provider spawns a new bot
    carrying Vexa's native passcode field. Stateful fake: like a real Vexa,
    once the retry carries a passcode the meeting stops reporting
    passcode_required and goes back to joining."""
    requests = []
    state = {"attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path == "/bots":
            state["attempts"] += 1
            return httpx.Response(201, json={"id": 7})
        if request.url.path == "/meetings/7":
            if state["attempts"] > 1:
                return httpx.Response(200, json={"id": 7, "status": "joining", "data": {}})
            return httpx.Response(
                200,
                json={"id": 7, "status": "failed", "data": {"diagnostics": "passcode_required"}},
            )
        return httpx.Response(200, json={})

    provider = _provider(transport_handler=handler)

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        for _ in range(200):
            if provider.status() == "passcode_required":
                break
            await asyncio.sleep(0.02)
        await provider.begin_listening(meeting_number="84335626851", passcode="retry-pwd")
        await asyncio.sleep(0.1)
        status = provider.status()
        await provider.stop()
        return status

    status = asyncio.run(run())
    assert status == "connecting"  # retry spawned a new attempt
    spawns = [r for r in requests if r.method == "POST" and r.url.path == "/bots"]
    assert json.loads(spawns[-1].content)["passcode"] == "retry-pwd"


def test_begin_listening_is_idempotent_while_connecting():
    """A double UI action while connecting must not spawn a second bot."""
    requests = []
    provider = _provider(transport_handler=lambda req: requests.append(req) or httpx.Response(201, json={"id": 7}))

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        await provider.stop()

    asyncio.run(run())
    spawns = [r for r in requests if r.method == "POST" and r.url.path == "/bots"]
    assert len(spawns) == 1


def test_ws_connect_sends_key_via_additional_headers():
    """websockets >= 14 uses additional_headers (extra_headers was removed
    there — the old kwarg made every WS connect raise TypeError and silently
    degrade the realtime path to polling)."""
    kwargs_seen = {}

    class RecordingSocket:
        async def send(self, raw):
            pass

        async def recv(self):
            await asyncio.sleep(3600)

        async def close(self):
            pass

    async def connect(url, **kwargs):
        kwargs_seen.update(kwargs)
        return RecordingSocket()

    provider = _provider(
        socket=None,
        transport_handler=_ok_handler(),
    )
    provider._connect = connect

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        await provider.stop()

    asyncio.run(run())
    assert kwargs_seen.get("additional_headers", {}).get("x-api-key") == "test-key"


def test_ws_connect_falls_back_to_extra_headers_on_typeerror():
    """Older websockets (<14) only accept extra_headers — the TypeError
    from the additional_headers attempt must fall back, not fail."""
    received = {}

    class RecordingSocket:
        async def send(self, raw):
            pass

        async def recv(self):
            await asyncio.sleep(3600)

        async def close(self):
            pass

    async def connect(url, **kwargs):
        if "additional_headers" in kwargs:
            raise TypeError("got an unexpected keyword argument 'additional_headers'")
        received.update(kwargs)
        return RecordingSocket()

    provider = _provider(socket=None, transport_handler=_ok_handler())
    provider._connect = connect

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        await asyncio.sleep(0.05)
        await provider.stop()

    asyncio.run(run())
    assert received.get("extra_headers", {}).get("x-api-key") == "test-key"


def test_ws_meeting_status_failed_with_passcode_marker_prompts_passcode():
    """The passcode check must run on the WebSocket path (primary transport),
    not only in the polling fallback — a failed meeting with the marker must
    become passcode_required, never plain degraded."""
    socket = FakeSocket(
        [
            {
                "type": "meeting.status",
                "meeting": {"id": 7, "platform": "zoom", "native_id": "84335626851"},
                "payload": {"status": "failed"},
            }
        ]
    )
    provider = _provider(
        socket=socket,
        transport_handler=_router_handler(
            meeting_detail={
                "id": 7,
                "status": "failed",
                "data": {"diagnostics": "[Zoom Web] passcode_required: ..."},
            }
        ),
    )

    async def run():
        await provider.start({"meeting_uuid": "u1"})
        await provider.begin_listening(meeting_number="84335626851")
        for _ in range(200):
            if provider.status() in ("passcode_required", "degraded"):
                break
            await asyncio.sleep(0.02)
        status = provider.status()
        await provider.stop()
        return status

    assert asyncio.run(run()) == "passcode_required"


# ---- TranscriptStabilizer tests (Phase 3: progressive merge) ---------------


def test_stabilizer_progressive_extensions_merged_to_one():
    s = TranscriptStabilizer(stability_seconds=999.0)  # never auto-flush
    assert s.add("hello", None, 1.0) == []
    assert s.add("hello world", None, 1.0) == []
    assert s.add("hello world this is", None, 1.0) == []
    # flush must produce exactly one utterance — the latest
    emitted = s.flush()
    assert len(emitted) == 1
    assert emitted[0][0] is None
    assert emitted[0][1] == "hello world this is"


def test_stabilizer_distinct_utterance_emits_immediately():
    s = TranscriptStabilizer(stability_seconds=999.0)
    r = s.add("hello world", None, 1.0)
    assert r == []  # nothing buffered yet
    r = s.add("goodbye moon", None, 2.0)
    # different utterance → previous flushed immediately
    assert len(r) == 1
    assert r[0][1] == "hello world"


def test_stabilizer_suffix_prefix_overlap_is_extension():
    s = TranscriptStabilizer(stability_seconds=999.0)
    assert s.add("the art of type", None, 1.0) == []
    assert s.add("art of typing magic words into a text box", None, 1.0) == []
    emitted = s.flush()
    assert len(emitted) == 1
    assert "art of typing magic words" in emitted[0][1]


def test_stabilizer_stability_timer_emits_after_expiry():
    s = TranscriptStabilizer(stability_seconds=0.0)  # expires immediately
    s.add("progressive chunk A", None, 1.0)
    emitted = s.tick()
    assert len(emitted) == 1
    assert "progressive chunk A" in emitted[0][1]


def test_stabilizer_per_speaker_buffering():
    """Two speakers producing independent utterances — must NOT merge."""
    s = TranscriptStabilizer(stability_seconds=999.0)
    s.add("speaker one says A", "A", 1.0)
    s.add("speaker two says B", "B", 1.0)
    # B is a DIFFERENT speaker, so A's utterance is flushed immediately
    emitted = s.flush()
    texts = {t for _, t, _ in emitted}
    assert "speaker one says A" in texts
    assert "speaker two says B" in texts


def test_stabilizer_exact_duplicate_is_noop():
    s = TranscriptStabilizer(stability_seconds=999.0)
    assert s.add("same", None, 1.0) == []
    assert s.add("same", None, 1.0) == []
    emitted = s.flush()
    assert any(t == "same" for _, t, _ in emitted)


def test_stabilizer_flush_on_stop_emits_all():
    s = TranscriptStabilizer(stability_seconds=999.0)
    s.add("speaker A says X", "A", 1.0)
    s.add("speaker B says Y", "B", 1.0)
    emitted = s.flush()
    assert len(emitted) == 2


def test_stop_words_do_not_cause_false_extension_merge():
    """Two distinct utterances sharing only stop words must remain separate."""
    s = TranscriptStabilizer(stability_seconds=999.0)
    assert s.add("The client is Acme Corp.", None, 1.0) == []
    r = s.add("The project is migrating their website.", None, 2.0)
    # Must flush "Acme Corp." because "migrating" is NOT an extension
    assert len(r) == 1
    assert "Acme Corp." in r[0][1]
    # The second utterance is now buffered
    emitted = s.flush()
    assert any("migrating" in t for _, t, _ in emitted)


def test_progressive_with_stop_words_still_merges():
    """Progressive extension that shares content words must still merge."""
    s = TranscriptStabilizer(stability_seconds=999.0)
    assert s.add("the budget", None, 1.0) == []
    # "the" is a stop word but "budget" is not — the overlap should work
    assert s.add("the budget is", None, 1.0) == []
    emitted = s.flush()
    assert len(emitted) == 1
    assert "the budget is" in emitted[0][1]


def test_content_dedup_blocks_duplicate_text_different_timestamps():
    """Identical (speaker, text) with different timestamps must be deduped."""
    from app.transcript.vexa_provider import VexaTranscriptProvider
    p = VexaTranscriptProvider("https://x.example", "k")
    p._stabilizer._stability_seconds = 0.0

    async def run():
        await p._ingest_segment({"speaker": "A", "text": "five internal pages,", "start": 1.0}, final=True)
        await p._ingest_segment({"speaker": "A", "text": "five internal pages,", "start": 1.1}, final=True)
        await p.stop()
        events = []
        while not p._queue.empty():
            events.append(p._queue.get_nowait())
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert texts.count("five internal pages,") == 1


# ---- Final-turn drain regression tests (STOP drain fix + WS tick) ----------


def test_ws_path_tick_emits_stable_utterance_without_waiting_for_next_utterance():
    """A healthy WS stream must emit the stabilizer's buffered utterance
    when its stability window expires — not wait for the next utterance.
    After the WS frame is consumed, the WS falls back to polling (no more
    frames); the polling path runs tick and emits the stale utterance."""
    socket = FakeSocket(
        [
            {"type": "transcription_segment", "text": "The client is Acme Corp.",
             "speaker": "A", "completed": True, "absolute_start_time": 1.0},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url).replace(BASE, "")
        if path.startswith("/transcripts/zoom/"):
            return httpx.Response(200, json={"segments": []})
        return httpx.Response(404)

    provider = _provider(
        transport_handler=handler,
        socket=socket,
        reconnect_attempts=1,
        read_timeout_seconds=0.02,
        poll_interval_seconds=0.02,
    )
    provider._stabilizer._stability_seconds = 0.0  # emit immediately on tick

    async def run():
        await provider._spawn_and_listen_mock("84194315528")
        # Wait for WS → fallback → polling tick to emit
        await asyncio.sleep(0.3)
        events = []
        while not provider._queue.empty():
            events.append(provider._queue.get_nowait())
        await provider.stop()
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert any("Acme Corp" in t for t in texts), (
        f"WS path + polling fallback must emit stable utterance; got: {texts}"
    )


def test_final_utterance_not_permanently_buffered_on_ws_path():
    """Without a second utterance, the final utterance must still be emitted
    via the polling fallback's tick. Verified against the bug where WS path
    never called tick()."""
    socket = FakeSocket(
        [
            {"type": "transcription_segment", "text": "Only thing said",
             "speaker": "A", "completed": True, "absolute_start_time": 1.0},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url).replace(BASE, "")
        if path.startswith("/transcripts/zoom/"):
            return httpx.Response(200, json={"segments": []})
        return httpx.Response(404)

    provider = _provider(
        transport_handler=handler,
        socket=socket,
        reconnect_attempts=1,
        read_timeout_seconds=0.02,
        poll_interval_seconds=0.02,
    )
    provider._stabilizer._stability_seconds = 0.0

    async def run():
        await provider._spawn_and_listen_mock("84194315528")
        await asyncio.sleep(0.3)
        await provider.stop()
        events = []
        while not provider._queue.empty():
            events.append(provider._queue.get_nowait())
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert any("Only thing said" in t for t in texts), (
        f"Final utterance must be emitted; got: {texts}"
    )


def test_stop_drain_waits_for_queue_to_empty():
    """The STOP drain loop must genuinely wait (up to 5s) for the session
    consumer to pick up events — not break after one iteration. Simulates
    a slow consumer that drains the queue after 0.3s."""
    import time

    p = VexaTranscriptProvider("https://x.example", "k", poll_interval_seconds=3.0)
    p._stabilizer._stability_seconds = 0.0

    async def run():
        # Put events on the queue — simulating the provider emitted them
        # and is waiting for the session consumer to pick them up.
        for i in range(3):
            await p._queue.put(TranscriptEvent(
                text=f"event {i}", timestamp=float(i), sequence=i
            ))
        # Simulate a slow consumer that will drain the queue after a delay
        async def slow_consumer():
            await asyncio.sleep(0.25)
            while not p._queue.empty():
                p._queue.get_nowait()

        consumer_task = asyncio.create_task(slow_consumer())
        start = time.monotonic()
        # Drain: wait up to 5s for consumer to pick up events (the real
        # stop() pattern — fixed version without the unconditional break).
        drained = 0
        while p._queue.qsize() > 0 and drained < 50:
            await asyncio.sleep(0.1)
            drained += 1
        elapsed = time.monotonic() - start
        await consumer_task
        return elapsed, p._queue.qsize(), drained

    elapsed, remaining, drained = asyncio.run(run())
    assert remaining == 0, f"Queue should be empty after drain; {remaining} remaining"
    # Should have waited multiple iterations — not the old single-iteration bug
    assert drained >= 2, f"Drain loop ran {drained} iterations — old bug would be 1"


def test_final_poll_before_bot_delete_captures_late_segment():
    """The final REST poll must happen BEFORE bot deletion. Segments from
    the collector finalized after bot delete would be lost."""
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        path = str(request.url).replace(BASE, "")
        if path == "/bots" and request.method == "POST":
            return httpx.Response(201, json={"id": 99, "platform": "zoom",
                                              "native_meeting_id": "84194315528"})
        if path.startswith("/transcripts/zoom/"):
            poll_count += 1
            # First poll (final pre-stop): return a late-finalized segment
            if poll_count == 1:
                return httpx.Response(200, json={"segments": [
                    {"speaker": "A", "text": "late segment", "completed": True,
                     "absolute_start_time": 99.0}
                ]})
            return httpx.Response(200, json={"segments": []})
        if path.startswith("/bots/zoom/"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    provider = _provider(
        transport_handler=handler,
        reconnect_attempts=0,
        poll_interval_seconds=0.01,
    )
    provider._stabilizer._stability_seconds = 0.0

    async def run():
        await provider._spawn_and_listen_mock("84194315528")
        # Simulate what happens after WS fails → fallback to polling
        # (consumer already cancelled, queue drained)
        provider._consumer_task.cancel()
        await asyncio.sleep(0.05)
        # Now execute the pre-bot-delete final poll (same logic as stop())
        doc = await provider._get_transcript()
        for seg in doc.get("segments", []) or []:
            if isinstance(seg, dict):
                await provider._ingest_segment(seg, final=True)
        for sp, st, _ in provider._stabilizer.flush():
            await provider._emit(st, sp)
        await provider._request_bot_stop()
        events = []
        while not provider._queue.empty():
            events.append(provider._queue.get_nowait())
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert any("late segment" in t for t in texts), (
        f"Final poll before bot delete must capture late segment; got: {texts}"
    )
    assert poll_count >= 1, "Final REST poll must have executed"


def test_live_transcript_does_not_wait_for_stop():
    """Segments emitted during live WS consumption must appear in the queue
    immediately — they are NOT gated on stop() being called."""
    socket = FakeSocket(
        [
            {"type": "transcription_segment", "text": "live utterance",
             "speaker": "A", "completed": True, "absolute_start_time": 1.0},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url).replace(BASE, "")
        if path.startswith("/transcripts/zoom/"):
            return httpx.Response(200, json={"segments": []})
        return httpx.Response(404)

    provider = _provider(
        transport_handler=handler,
        socket=socket,
        reconnect_attempts=1,
        read_timeout_seconds=0.02,
        poll_interval_seconds=0.02,
    )
    provider._stabilizer._stability_seconds = 0.0

    async def run():
        await provider._spawn_and_listen_mock("84194315528")
        # Wait for WS → fallback → polling tick to emit
        await asyncio.sleep(0.3)
        # Check queue BEFORE calling stop — live content must already be present
        live_events = []
        while not provider._queue.empty():
            live_events.append(provider._queue.get_nowait())
        # Now stop (should flush remainder)
        await provider.stop()
        post_stop = []
        while not provider._queue.empty():
            post_stop.append(provider._queue.get_nowait())
        return live_events, post_stop

    live, post_stop = asyncio.run(run())
    live_texts = [e.text for e in live]
    assert any("live utterance" in t for t in live_texts), (
        f"Live utterance must appear BEFORE stop(); got live: {live_texts}"
    )


# ---- spawn helper (used by final-turn drain tests) --------------------------


async def _spawn_and_listen_mock(self, native_meeting_id):
    """Minimal begin_listening for tests — spawns bot and starts consumer
    without needing a real HTTP transport (FakeSocket is the source)."""
    self._native_meeting_id = native_meeting_id
    self._meeting_url = f"https://zoom.us/j/{native_meeting_id}"
    self._bot_spawned = True
    self._status = STATUS_CONNECTING
    self._consumer_task = asyncio.create_task(self._consume())


VexaTranscriptProvider._spawn_and_listen_mock = _spawn_and_listen_mock


def test_dedup_keys_on_text_only_not_speaker():
    """Same text with different speakers must be deduplicated."""
    p = VexaTranscriptProvider("https://x.example", "k")
    p._stabilizer._stability_seconds = 0.0

    async def run():
        await p._ingest_segment({"speaker": "A", "text": "deliverables are five pages", "absolute_start_time": 1.0}, final=True)
        await p._ingest_segment({"speaker": "B", "text": "deliverables are five pages", "absolute_start_time": 1.5}, final=True)
        await p.stop()
        events = []
        while not p._queue.empty():
            events.append(p._queue.get_nowait())
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert texts.count("deliverables are five pages") == 1


def test_clear_seen_empties_dedup_set():
    """clear_seen() must reset dedup so repeated speech after clear works."""
    p = VexaTranscriptProvider("https://x.example", "k")
    p._stabilizer._stability_seconds = 0.0

    async def run():
        await p._ingest_segment({"speaker": "A", "text": "hello", "absolute_start_time": 1.0}, final=True)
        assert len(p._seen) == 1
        p.clear_seen()
        assert len(p._seen) == 0
        # Different speaker so stabilizer doesn't merge as extension
        await p._ingest_segment({"speaker": "B", "text": "hello", "absolute_start_time": 2.0}, final=True)
        await p.stop()
        events = []
        while not p._queue.empty():
            events.append(p._queue.get_nowait())
        return events

    events = asyncio.run(run())
    texts = [e.text for e in events]
    assert texts.count("hello") == 2  # emitted twice — clear allowed re-emission
