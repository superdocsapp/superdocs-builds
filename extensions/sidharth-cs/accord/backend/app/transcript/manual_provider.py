"""ManualTranscriptProvider — a normal TranscriptProvider, the only
difference being where events come from: `submit()`, called by the
transcript-submission API route, instead of an RTMS websocket frame.

`submit()` is not part of the TranscriptProvider Protocol — it's this
provider's own ingestion method, the Manual equivalent of the websocket
consumer a future RTMSTranscriptProvider would run internally. The Draft
Engine never calls it and never imports this class directly; it only ever
sees the Protocol (start/stop/status/events), which is exactly what makes
this provider swappable for RTMS later without touching the Draft Engine.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from app.transcript.provider import (
    STATUS_LIVE,
    STATUS_NOT_STARTED,
    STATUS_STOPPED,
    TranscriptEvent,
)


class ManualTranscriptProvider:
    name = "manual"

    def __init__(self) -> None:
        self._status = STATUS_NOT_STARTED
        self._queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._sequence = 0

    async def start(self, meeting_context: dict) -> None:
        # Nothing to connect to — typed input is available the instant the
        # panel is. Async and takes meeting_context for Protocol
        # conformance with RTMSTranscriptProvider, which genuinely needs
        # both (a webhook round-trip; the meeting to attach RTMS to).
        self._status = STATUS_LIVE

    async def stop(self) -> None:
        self._status = STATUS_STOPPED

    def status(self) -> str:
        return self._status

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            yield await self._queue.get()

    async def submit(self, text: str, speaker: str | None = None, is_correction: bool = False) -> TranscriptEvent:
        text = text.strip()
        if not text:
            raise ValueError("transcript text cannot be empty")
        self._sequence += 1
        event = TranscriptEvent(
            text=text, timestamp=time.time(), sequence=self._sequence, speaker=speaker, is_correction=is_correction
        )
        await self._queue.put(event)
        return event
