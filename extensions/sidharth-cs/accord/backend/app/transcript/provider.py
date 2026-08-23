"""The TranscriptProvider abstraction (design doc §14) — directly analogous
to Task 1's ModelAdapter protocol. Everything downstream (Batcher,
classifier, MeetingSession) depends only on this shape, never on a concrete
provider, so transcript origin is irrelevant past this module.

ManualTranscriptProvider (this milestone) and RTMSTranscriptProvider
(Milestone 4, not built here — M0 already found RTMS unavailable on this
account, and building it now would be exactly the RTMS-integration work
this milestone is explicitly not) both satisfy this same Protocol. Nothing
below imports either concrete provider.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from pydantic import BaseModel

# Polled by the session state machine and surfaced to the panel — mirrors
# the plan's own NOT_STARTED / CONNECTING / LIVE / DEGRADED / STOPPED / ERROR
# vocabulary exactly.
STATUS_NOT_STARTED = "not_started"
STATUS_CONNECTING = "connecting"
STATUS_LIVE = "live"
STATUS_DEGRADED = "degraded"
# Milestone 6: Vexa reported the Zoom meeting needs a passcode (its own
# join.ts `passcode_required` reason, surfaced through the meeting's
# diagnostics). The panel shows an ephemeral passcode input and retries
# with Vexa's native `passcode` field — never persisted, never logged.
STATUS_PASSCODE_REQUIRED = "passcode_required"
STATUS_STOPPED = "stopped"
STATUS_ERROR = "error"


class TranscriptEvent(BaseModel):
    """What the Batcher consumes. Only what it genuinely needs — see
    PROGRESS.md M3 for the fields deliberately left out."""

    text: str
    timestamp: float
    sequence: int
    speaker: str | None = None
    is_final: bool = True
    # Phase 4: explicit correction flag.  When True, the batcher flushes
    # immediately and the instruction is framed as a correction.
    is_correction: bool = False


class TranscriptProvider(Protocol):
    name: str

    async def start(self, meeting_context: dict) -> None: ...

    async def stop(self) -> None: ...

    def status(self) -> str: ...

    def events(self) -> AsyncIterator[TranscriptEvent]: ...
