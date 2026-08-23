"""RTMSTranscriptProvider — Milestone 4. Satisfies the same TranscriptProvider
Protocol as ManualTranscriptProvider (provider.py), consuming Zoom's
Realtime Media Streams instead of typed input. Built against Zoom's
documented RTMS websocket protocol (developers.zoom.us/blog/
realtime-mediastreams-websockets/ — see PROGRESS.md M4 for the full trail
and which specific details are confirmed vs. a stated, reasonable
assumption where the source didn't fully specify one) — never live-verified
against a real Zoom meeting in this environment, since M0 already confirmed
`meeting.rtms_started` never arrives on this account. Covered by
tests/test_rtms_provider.py against an injected fake websocket connector.

Zero imports from drafting/, superdocs/, or api/ — this module only
acquires transcript, exactly like manual_provider.py; it never sees the
Batcher, classifier, or SuperDocs client.

Graceful degradation, in one sentence: every failure mode (never connects,
platform silently refuses, drops mid-meeting, times out) resolves to the
same DEGRADED status with submit() still open — not a different code path
per failure, and never a raised exception out of start() or the background
tasks. MeetingSession.start() has no try/except around `self._provider.
start(...)`, and get_or_create_session is on the panel's first-load path —
both are why start() must return immediately and never raise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable

import websockets

from app.core.security import build_rtms_signature
from app.transcript.provider import (
    STATUS_CONNECTING,
    STATUS_DEGRADED,
    STATUS_LIVE,
    STATUS_NOT_STARTED,
    STATUS_STOPPED,
    TranscriptEvent,
)

logger = logging.getLogger("transcript.rtms")

_PROTOCOL_VERSION = 1
_MEDIA_TYPE_TRANSCRIPT = 8

_MSG_SIGNALING_HANDSHAKE_REQ = 1
_MSG_MEDIA_HANDSHAKE_REQ = 3
_MSG_MEDIA_READY = 7
_MSG_KEEP_ALIVE_REQ = 12
_MSG_KEEP_ALIVE_RESP = 13
_MSG_MEDIA_DATA_TRANSCRIPT = 17

WebSocketConnector = Callable[[str], Awaitable[Any]]


class RTMSTranscriptProvider:
    name = "rtms"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        connect_timeout_seconds: float = 20.0,
        read_timeout_seconds: float = 45.0,
        reconnect_attempts: int = 3,
        reconnect_backoff_seconds: float = 1.0,
        websocket_connector: WebSocketConnector | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._connect_timeout_seconds = connect_timeout_seconds
        # Comfortably longer than the documented keep-alive ping (msg_type
        # 12) — a silently stalled connection (no error, no data, network
        # partition) never raises on its own, so recv() alone can't detect
        # it; without this bound, _read_frames would hang forever on one
        # call, never incrementing a reconnect attempt. Found via this
        # provider's own live-fixture testing during M4, not guessed at.
        self._read_timeout_seconds = read_timeout_seconds
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_backoff_seconds = reconnect_backoff_seconds
        self._connect: WebSocketConnector = websocket_connector or websockets.connect

        self._status = STATUS_NOT_STARTED
        self._meeting_uuid = ""
        self._rtms_stream_id = ""
        self._transcript_url: str | None = None
        self._queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._sequence = 0

        self._watchdog_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        self._media_socket: Any = None

    # ---- TranscriptProvider Protocol ---------------------------------------

    async def start(self, meeting_context: dict) -> None:
        self._meeting_uuid = meeting_context.get("meeting_uuid", "")
        self._status = STATUS_CONNECTING
        self._watchdog_task = asyncio.create_task(self._watchdog())

    async def stop(self) -> None:
        for task in (self._watchdog_task, self._reader_task):
            if task is not None and not task.done():
                task.cancel()
        if self._media_socket is not None:
            await self._safe_close(self._media_socket)
        self._status = STATUS_STOPPED

    def status(self) -> str:
        return self._status

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            yield await self._queue.get()

    # ---- provider-specific entry points (not part of the Protocol,
    # exactly like ManualTranscriptProvider.submit()) ------------------------

    async def submit(self, text: str, speaker: str | None = None, is_correction: bool = False) -> TranscriptEvent:
        """Manual override / fallback input — same contract as
        ManualTranscriptProvider.submit(). Always available regardless of
        RTMS status: this *is* the "fallback without restarting the
        meeting" mechanism, live from construction, not wired up only on
        failure."""
        text = text.strip()
        if not text:
            raise ValueError("transcript text cannot be empty")
        return await self._emit(text, speaker)

    async def on_rtms_started(self, *, rtms_stream_id: str, server_urls: str) -> None:
        """Called by zoom/webhooks.py when meeting.rtms_started arrives for
        this session. Idempotent — re-entry from DEGRADED is deliberate
        (lets a later webhook, after a drop or once the platform issue
        resolves, recover the session without restarting the meeting);
        no-ops if already LIVE, so a duplicate webhook delivery (Zoom
        retries are expected) never opens a second socket. Never raises —
        the webhook handler that calls this must not 500 regardless of
        what happens here."""
        if self._status not in (STATUS_NOT_STARTED, STATUS_CONNECTING, STATUS_DEGRADED):
            return
        if not rtms_stream_id or not server_urls:
            logger.warning("RTMS: on_rtms_started called with missing rtms_stream_id/server_urls")
            return

        self._rtms_stream_id = rtms_stream_id
        try:
            transcript_url = await self._signaling_handshake(server_urls)
            if transcript_url is None:
                return  # already logged; the watchdog resolves this to DEGRADED
            self._transcript_url = transcript_url
            await self._connect_media_socket(transcript_url)
        except Exception:
            logger.exception(
                "RTMS: on_rtms_started failed for meeting_uuid=%r", self._meeting_uuid
            )
            return  # never raise into the webhook handler; watchdog covers status

        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._status = STATUS_LIVE
        self._reader_task = asyncio.create_task(self._read_frames())

    # ---- internals ------------------------------------------------------------

    async def _watchdog(self) -> None:
        try:
            await asyncio.sleep(self._connect_timeout_seconds)
        except asyncio.CancelledError:
            return
        if self._status == STATUS_CONNECTING:
            logger.warning(
                "RTMS is unavailable in this Zoom environment after %.0fs — "
                "falling back to ManualTranscriptProvider-style input for meeting_uuid=%r.",
                self._connect_timeout_seconds,
                self._meeting_uuid,
            )
            self._status = STATUS_DEGRADED

    async def _signaling_handshake(self, server_url: str) -> str | None:
        signature = build_rtms_signature(
            self._client_id, self._client_secret, self._meeting_uuid, self._rtms_stream_id
        )
        request = {
            "msg_type": _MSG_SIGNALING_HANDSHAKE_REQ,
            "protocol_version": _PROTOCOL_VERSION,
            "sequence": 0,
            "meeting_uuid": self._meeting_uuid,
            "rtms_stream_id": self._rtms_stream_id,
            "signature": signature,
        }
        socket = await self._connect(server_url)
        try:
            await socket.send(json.dumps(request))
            raw = await asyncio.wait_for(socket.recv(), timeout=self._connect_timeout_seconds)
            response = json.loads(raw)
            if response.get("status_code") != 0:
                logger.warning(
                    "RTMS: signaling handshake rejected, status_code=%r for meeting_uuid=%r",
                    response.get("status_code"),
                    self._meeting_uuid,
                )
                return None
            # Assumption, stated plainly rather than guessed silently (not
            # confirmed against a real response — see PROGRESS.md M4): the
            # signaling socket's only job is handing back the media URL, so
            # it's closed here rather than held open alongside the media
            # socket for the rest of the meeting.
            return response.get("media_server", {}).get("server_urls", {}).get("transcript")
        finally:
            await self._safe_close(socket)

    async def _connect_media_socket(self, transcript_url: str) -> None:
        signature = build_rtms_signature(
            self._client_id, self._client_secret, self._meeting_uuid, self._rtms_stream_id
        )
        socket = await self._connect(transcript_url)
        handshake = {
            "msg_type": _MSG_MEDIA_HANDSHAKE_REQ,
            "protocol_version": _PROTOCOL_VERSION,
            "sequence": 0,
            "meeting_uuid": self._meeting_uuid,
            "rtms_stream_id": self._rtms_stream_id,
            "signature": signature,
            "media_type": _MEDIA_TYPE_TRANSCRIPT,
        }
        await socket.send(json.dumps(handshake))
        # No distinct media-handshake-ACK shape was surfaced by the source
        # this was built against — sending the ready signal immediately
        # rather than guessing at an ack format to wait for. Flagged in
        # PROGRESS.md M4 as an assumption to revisit if it's ever provably
        # wrong.
        await socket.send(json.dumps({"msg_type": _MSG_MEDIA_READY}))
        self._media_socket = socket

    async def _read_frames(self) -> None:
        attempt = 0
        while True:
            try:
                raw = await asyncio.wait_for(
                    self._media_socket.recv(), timeout=self._read_timeout_seconds
                )
            except asyncio.CancelledError:
                return
            except Exception:
                # Covers both an explicit ConnectionClosed-style raise and a
                # silent stall (TimeoutError, a subclass of Exception, from
                # the wait_for above) — same remedy either way, see the
                # constructor's read_timeout_seconds comment.
                attempt += 1
                if attempt > self._reconnect_attempts:
                    logger.warning(
                        "RTMS: media socket lost, reconnect attempts exhausted for "
                        "meeting_uuid=%r — falling back to manual input.",
                        self._meeting_uuid,
                    )
                    self._status = STATUS_DEGRADED
                    return
                await asyncio.sleep(self._reconnect_backoff_seconds * attempt)
                if self._transcript_url is not None:
                    try:
                        # Reconnects the media socket only — the signaling
                        # URL isn't re-fetched, and rtms_stream_id stays
                        # valid for this meeting instance per the
                        # documented "static authentication, no token
                        # refresh" signature scheme.
                        await self._connect_media_socket(self._transcript_url)
                    except Exception:
                        pass
                continue

            attempt = 0
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            await self._handle_media_message(message)

    async def _handle_media_message(self, message: dict) -> None:
        msg_type = message.get("msg_type")
        if msg_type == _MSG_MEDIA_DATA_TRANSCRIPT:
            content = message.get("content", {})
            text = content.get("data", "")
            if text.strip():
                await self._emit(text, content.get("user_name"))
        elif msg_type == _MSG_KEEP_ALIVE_REQ:
            await self._safe_send(
                self._media_socket, {"msg_type": _MSG_KEEP_ALIVE_RESP, "timestamp": time.time()}
            )
        # Any other msg_type (session state updates, etc. — see the mock
        # server's own description) is intentionally ignored, not an error.

    async def _emit(self, text: str, speaker: str | None) -> TranscriptEvent:
        self._sequence += 1
        event = TranscriptEvent(
            text=text, timestamp=time.time(), sequence=self._sequence, speaker=speaker
        )
        await self._queue.put(event)
        return event

    @staticmethod
    async def _safe_close(socket: Any) -> None:
        try:
            await socket.close()
        except Exception:
            pass

    @staticmethod
    async def _safe_send(socket: Any, message: dict) -> None:
        try:
            await socket.send(json.dumps(message))
        except Exception:
            pass
