"""VexaTranscriptProvider — Milestone 6. Satisfies the same
TranscriptProvider Protocol as ManualTranscriptProvider and
RTMSTranscriptProvider (provider.py): start/stop/status/events, plus a
submit() manual-override entry point exactly like the other two. Vexa's
ONLY job in this app is listening to the Zoom meeting and delivering
transcript data — every behavior downstream of the events() stream
(Batcher, classifier, MeetingSession, SuperDocs) is untouched and
provider-agnostic.

Built against the CURRENT Vexa source (Vexa-ai/vexa, v0.12, main @
fde7dfb7 — see PROGRESS.md M6 for the full verification trail):
  - Zoom join is a web-client guest join (no SDK setup): the bot's
    Playwright browser navigates the meeting URL, so the API REQUIRES a
    meeting_url for platform=zoom (core/meetings/.../bot_spawn/router.py:
    "meeting_url ... required for zoom/jitsi").
  - POST /bots {platform, native_meeting_id, meeting_url, passcode,
    bot_name, language, transcribe_enabled} → 201 MeetingResponse.
  - DELETE /bots/{platform}/{native_meeting_id} stops the bot.
  - GET /transcripts/{platform}/{native_meeting_id} → TranscriptionResponse
    {segments: [TranscriptionSegment{text, speaker, completed,
    absolute_start_time, ...}]} — completed:true marks a FINAL segment.
  - ws(s)://<gateway>/ws with `x-api-key: <key>` header, subscribe
    {action:"subscribe", meetings:[{platform, native_id}]}, live data
    {type:"transcript", confirmed[], pending[]} / {type:"transcription_segment", ...}
    / {type:"meeting.status", payload:{status}} (ws.v1 contract).

Realtime delivery: the /ws stream is preferred (genuine sub-second
pushes); if the websocket gives up (connect refused, exhausted reconnect
attempts) the consumer falls back to REST polling of GET /transcripts —
same segments, higher latency, same dedup. Status stays LIVE either way;
the transport is logged, never misrepresented.

Dedup: segments carry no stable id, so duplicates are recognized by
(speaker, text, absolute_start_time|created_at) — the natural key for
"the same finalized utterance" whether it arrives twice over WS or is
re-read by a later poll. pending/interim segments are dropped (the
Batcher's final-transcript-only rule, §14 — same reason TranscriptEvent
has is_final).

Degradation, one sentence, mirroring rtms_provider.py's policy: every
failure mode (not configured, spawn refused, WS exhausted, polls failing,
bot stuck needing human help) resolves to DEGRADED with submit() still
open — never a raised exception out of start()/begin_listening(), never
a crash for the session.

Zero imports from drafting/, superdocs/, or api/ — like the other two
providers, this module only acquires transcript.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

import httpx
import websockets

from app.transcript.provider import (
    STATUS_CONNECTING,
    STATUS_DEGRADED,
    STATUS_LIVE,
    STATUS_NOT_STARTED,
    STATUS_PASSCODE_REQUIRED,
    STATUS_STOPPED,
    TranscriptEvent,
)

logger = logging.getLogger("transcript.vexa")

# Vexa's own meeting status vocabulary (api.v1 MeetingStatus enum, sealed
# contract) — normalized to our provider statuses in _handle_meeting_status.
_VEXA_STATUS_ACTIVE = "active"
_VEXA_STATUS_FAILED = "failed"
_VEXA_STATUS_STOPPING = "stopping"
_VEXA_STATUS_COMPLETED = "completed"
# Bot can't proceed on its own — e.g. Zoom's reCAPTCHA or "automated bots
# aren't allowed / must use Zoom RTMS" wall (join.ts): honest DEGRADED, not
# a fake LIVE.
_VEXA_STATUS_NEEDS_HUMAN_HELP = "needs_human_help"

# How many consecutive failed transcript polls before calling it DEGRADED
# (a poll failure means the gateway is unreachable — not a meeting state).
_MAX_POLL_FAILURES = 5

WebSocketConnector = Callable[..., Awaitable[Any]]


# English stop words — excluded from Case 3 vocab-overlap so common
# function words cannot cause two unrelated utterances to be merged.
# Source: NLTK English stopwords (core set).
_STOP_WORDS = frozenset({
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "a", "an", "the", "and", "but", "if", "or", "because", "as",
    "until", "while", "of", "at", "by", "for", "with", "about",
    "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how", "all",
    "both", "each", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "can", "will", "just", "should", "now",
})


class _Utterance:
    """A single buffered utterance — may be replaced by progressive
    extensions from overlapping audio chunks. Emitted once stable."""

    __slots__ = ("speaker", "text", "timestamp", "first_seen", "last_extended", "word_count")

    def __init__(self, speaker: str | None, text: str, timestamp: float) -> None:
        self.speaker = speaker
        self.text = text
        self.timestamp = timestamp
        self.first_seen = time.time()
        self.last_extended = time.time()
        self.word_count = len(text.split())


class TranscriptStabilizer:
    """Merges progressive/extending transcript segments that arrive from
    Vexa's overlapping-chunk pipeline.  One utterance may arrive as five
    segments ("hello" → "hello world" → "hello world this is" → "hello
    world this is a" → "hello world this is a test") — the stabilizer
    keeps the latest and emits it ONCE when it stops growing.

    A segment is *not* delayed merely because it exists.  Emission is
    immediate when the new segment is clearly a DISTINCT utterance (no
    overlap with the previous one).  The stability window only applies to
    genuinely progressive segments — a replacement resets the timer; a
    different utterance causes the previous one to be flushed immediately.

    The stabilizer is per-provider-instance — one concurrent meeting."""

    def __init__(self, stability_seconds: float = 2.0):
        self._stability_seconds = stability_seconds
        self._pending: dict[str | int, _Utterance] = {}

    def add(self, text: str, speaker: str | None, timestamp: float) -> list[tuple[str, str | None, float]]:
        """Accept a confirmed segment.  Returns zero or more STABLE
        (text, speaker, timestamp) tuples ready for emission."""
        # Unknown-speaker segments share one buffer (we can't distinguish
        # speakers without attribution); known speakers each get their own.
        key: str | int = speaker if speaker is not None else id("__unknown__")
        prev = self._pending.get(key)
        if prev is None:
            self._pending[key] = _Utterance(speaker, text, timestamp)
            return []

        # --- progressive extension? ---
        if self._is_extension(prev.text, text):
            # Keep the LONGER version — overlapping chunks may deliver
            # the extended version FIRST and the shorter version SECOND.
            if len(text.split()) >= len(prev.text.split()):
                prev.text = text
            prev.last_extended = time.time()
            prev.word_count = len(prev.text.split())
            return []

        # --- different utterance: flush previous, buffer new ---
        del self._pending[key]
        emitted = [(prev.speaker, prev.text, prev.timestamp)]
        self._pending[key] = _Utterance(speaker, text, timestamp)
        return emitted

    def tick(self) -> list[tuple[str, str | None, float]]:
        """Called periodically.  Emits any buffered utterance whose
        stability window has expired."""
        now = time.time()
        flushed = []
        stale = [
            key
            for key, u in self._pending.items()
            if now - u.last_extended >= self._stability_seconds
        ]
        for key in stale:
            u = self._pending.pop(key)
            flushed.append((u.speaker, u.text, u.timestamp))
        return flushed

    def flush(self) -> list[tuple[str, str | None, float]]:
        """Emit ALL buffered utterances — used at stop/flush."""
        flushed = [(u.speaker, u.text, u.timestamp) for u in self._pending.values()]
        self._pending.clear()
        return flushed

    @staticmethod
    def _is_extension(prev_text: str, new_text: str) -> bool:
        """True when new_text is a likely progressive extension of prev_text
        (same utterance captured in an overlapping chunk)."""
        if not new_text or not prev_text:
            return False
        if new_text.casefold() == prev_text.casefold():
            return True
        # Normalize: lower-case + strip trailing sentence punctuation so
        # "the budget." extends into "the budget is"
        import string

        def _norm(s: str) -> str:
            return s.casefold().rstrip(string.punctuation)

        pn = _norm(prev_text)
        nn = _norm(new_text)
        if not pn or not nn:
            return False
        # Case 1: strict prefix extension (normalized) — either direction:
        # longer version extends shorter, or shorter is a prefix of longer
        if nn.startswith(pn) or pn.startswith(nn):
            return True
        # Case 2: word-level overlap — a common multi-word sequence
        # (≥2 words) appears in BOTH texts, and it appears early in
        # new_text (within the first half).  Not strictly suffix/prefix;
        # overlapping Vexa chunks may shift the window by a few words.
        pw = pn.split()
        nw = nn.split()
        if len(pw) < 2 or len(nw) < 2:
            return False
        best = 0
        # Search for the longest word sequence that appears anywhere in
        # both texts, occurring within the first half of new_text.
        for n in range(min(len(pw), len(nw)), 1, -1):
            for i in range(len(pw) - n + 1):
                seek = pw[i : i + n]
                for j in range(0, len(nw) - n + 1):
                    if nw[j : j + n] == seek:
                        best = n
                        break
                if best:
                    break
            if best:
                break
        if best >= 2:
            return True
        # Case 3: ≥40% of prev_text's meaningful (non-stop-word) vocabulary
        # appears in the FIRST HALF of new_text. Stop words are excluded so
        # common function words ("the", "is", "a") cannot cause unrelated
        # adjacent speech to be merged.
        pv = set(w for w in pw if w not in _STOP_WORDS)
        nv = set(w for w in nw[: max(2, len(nw) // 2)] if w not in _STOP_WORDS)
        if len(pv) < 2:
            return False  # not enough meaningful words to judge
        shared = len(pv & nv)
        if shared >= max(2, len(pv) * 0.4):
            return True
        return False


class VexaTranscriptProvider:
    name = "vexa"

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        *,
        bot_name: str = "Live Deliverable",
        language: str = "en",
        poll_interval_seconds: float = 3.0,
        connect_timeout_seconds: float = 20.0,
        read_timeout_seconds: float = 45.0,
        reconnect_attempts: int = 3,
        reconnect_backoff_seconds: float = 2.0,
        http_client: httpx.AsyncClient | None = None,
        websocket_connector: WebSocketConnector | None = None,
    ) -> None:
        self._api_base_url = (api_base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._bot_name = bot_name
        self._language = language
        self._poll_interval_seconds = poll_interval_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        # Same stall-detection rationale as rtms_provider.py's read timeout:
        # a silently stalled websocket never raises on its own, so recv()
        # must be bounded or the consumer hangs forever on one call.
        self._read_timeout_seconds = read_timeout_seconds
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_backoff_seconds = reconnect_backoff_seconds
        self._connect: WebSocketConnector = websocket_connector or websockets.connect

        self._status = STATUS_NOT_STARTED
        self._meeting_uuid = ""
        self._native_meeting_id = ""
        self._meeting_url = ""
        self._bot_spawned = False
        # Internal Vexa meeting row id (from POST /bots response) — used to
        # fetch the meeting detail where Vexa records the join-failure
        # reason (e.g. passcode_required). None until a bot has been asked
        # to join.
        self._meeting_id: int | None = None
        # Ephemeral, attempt-scoped Zoom passcode for Vexa's native
        # `passcode` field. Held only between begin_listening() and the
        # POST /bots result (success or failure) — never persisted, never
        # logged, cleared on stop().
        self._passcode: str | None = None

        self._queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._sequence = 0
        self._seen: set[tuple] = set()
        # TranscriptStabilizer: merges progressive/extending segments from
        # Vexa's overlapping audio chunks — each provider instance owns one,
        # lifetime = provider lifetime (one concurrent meeting).
        self._stabilizer = TranscriptStabilizer(stability_seconds=2.0)

        self._consumer_task: asyncio.Task | None = None
        self._socket: Any = None
        # Owned vs. injected: injected clients (tests) are never closed here.
        self._http_client: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

    # ---- TranscriptProvider Protocol ---------------------------------------

    async def start(self, meeting_context: dict) -> None:
        self._meeting_uuid = meeting_context.get("meeting_uuid", "")
        # Deliberately does NOT spawn a bot: Vexa listening is an explicit
        # user action ("Start listening" in the panel → begin_listening()),
        # not an automatic panel-load effect. start() only records the
        # meeting correlation key; status stays NOT_STARTED ("Ready").
        # begin_listening() is re-entrant from STOPPED, so a stopped
        # listening session can be started again without a new session.

    async def stop(self) -> None:
        # Flush the stabilizer: any buffered utterances still pending
        # (progressive segments that never received a final extension)
        # must be emitted before shutdown so no captured speech is lost.
        # Order: flush → drain queue → cancel consumer → close WS → delete bot.
        for stable_speaker, stable_text, _ in self._stabilizer.flush():
            await self._emit(stable_text, stable_speaker)
        if self._consumer_task is not None and not self._consumer_task.done():
            self._consumer_task.cancel()
        # Bounded drain: wait up to 5s for the MeetingSession consumer to
        # pick up any events just emitted. After 5s the session's own
        # lifecycle takes over — we don't own SuperDocs finalization.
        # Fixed: the unconditional `break` on the outer while meant the
        # drain ran at most ONE iteration regardless of queue size. Now
        # genuinely loops up to 50 × 0.1s = 5s.
        try:
            drained = 0
            while self._queue.qsize() > 0 and drained < 50:
                await asyncio.sleep(0.1)
                drained += 1
        except Exception:
            pass
        if self._socket is not None:
            await self._safe_close(self._socket)
        if self._bot_spawned:
            # Final REST poll BEFORE bot deletion: Vexa's collector
            # finalizes in-flight segments while the bot is still running.
            # Polling after deletion may miss segments finalized during
            # teardown.  Single poll with short timeout.
            try:
                doc = await asyncio.wait_for(
                    self._get_transcript(), timeout=self._poll_interval_seconds + 2
                )
                for segment in doc.get("segments", []) or []:
                    if isinstance(segment, dict):
                        await self._ingest_segment(segment, final=True)
                # Flush any segments the final poll filled into the
                # stabilizer.
                for stable_speaker, stable_text, _ in self._stabilizer.flush():
                    await self._emit(stable_text, stable_speaker)
            except Exception:
                pass
            # Delete the bot AFTER the final poll — segments finalized
            # during teardown are now captured.
            await self._request_bot_stop()
        if self._owns_client and self._http_client is not None:
            await self._safe_aclose(self._http_client)
            self._http_client = None
        self._passcode = None
        self._status = STATUS_STOPPED

    def status(self) -> str:
        return self._status

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            yield await self._queue.get()

    # ---- provider-specific entry points (not part of the Protocol, exactly
    # like ManualTranscriptProvider.submit() / RTMS's on_rtms_started) ------

    async def submit(self, text: str, speaker: str | None = None, is_correction: bool = False) -> TranscriptEvent:
        """Manual override / fallback input — same contract as
        ManualTranscriptProvider.submit(). Always available regardless of
        Vexa status: this IS the fallback without restarting the meeting,
        live from construction, exactly like RTMSTranscriptProvider's."""
        text = text.strip()
        if not text:
            raise ValueError("transcript text cannot be empty")
        return await self._emit(text, speaker, is_correction=is_correction)

    def clear_seen(self) -> None:
        """Clear the dedup set — called by MeetingSession.reset() so
        repeated speech after Clear is not silently dropped."""
        self._seen.clear()

    async def begin_listening(
        self,
        *,
        meeting_number: str | None = None,
        meeting_url: str | None = None,
        passcode: str | None = None,
    ) -> None:
        """Start the Vexa bot for this meeting. The panel's "Start
        listening" calls this via MeetingSession.start_listening(). Never
        raises — every failure resolves to DEGRADED (or PASSCODE_REQUIRED
        when Vexa reports the meeting needs a passcode); submit() stays
        open. `passcode` is the ephemeral, attempt-scoped Zoom passcode
        passed to Vexa's native `passcode` field — never persisted, never
        logged, cleared once the spawn request settles.

        Re-entrant from PASSCODE_REQUIRED/STOPPED: the panel retries with
        a passcode after Vexa reported passcode_required. No-op while a
        listen attempt is already in flight (CONNECTING/LIVE) so a double
        UI action never creates a second bot."""
        if self._status in (STATUS_CONNECTING, STATUS_LIVE):
            return
        self._passcode = (passcode or "").strip() or None
        new_meeting_id = (meeting_number or "").strip()
        # Same-meeting reuse: if the bot was stopped (not passcode-blocked),
        # restart the consumer without spawning a duplicate bot.
        # Passcode retry must still create a new bot with the passcode.
        if (self._bot_spawned and self._native_meeting_id == new_meeting_id
                and self._status in (STATUS_STOPPED, STATUS_DEGRADED)):
            self._status = STATUS_CONNECTING
            self._consumer_task = asyncio.create_task(self._consume())
            return
        self._meeting_id = None
        self._native_meeting_id = new_meeting_id
        self._meeting_url = (meeting_url or "").strip()
        if not self._meeting_url and self._native_meeting_id:
            self._meeting_url = f"https://zoom.us/j/{self._native_meeting_id}"
        if not self._meeting_url:
            logger.warning(
                "Vexa: begin_listening needs a meeting number or join URL (meeting_uuid=%r)",
                self._meeting_uuid,
            )
            self._passcode = None
            self._status = STATUS_DEGRADED
            return
        if not self._native_meeting_id:
            parsed = urlparse(self._meeting_url)
            digits = "".join(ch for ch in parsed.path if ch.isdigit())
            self._native_meeting_id = digits
        if not self._configured:
            logger.warning(
                "Vexa: live transcription unavailable — VEXA_API_BASE_URL/VEXA_API_KEY "
                "are not set; manual input remains available (meeting_uuid=%r)",
                self._meeting_uuid,
            )
            self._passcode = None
            self._status = STATUS_DEGRADED
            return

        self._status = STATUS_CONNECTING
        try:
            await self._spawn_bot()
        except Exception:
            logger.exception("Vexa: bot spawn failed for meeting_uuid=%r", self._meeting_uuid)
            self._passcode = None
            self._status = STATUS_DEGRADED
            return
        # Attempt-scoped: the passcode was only needed for POST /bots.
        self._passcode = None
        self._bot_spawned = True
        self._consumer_task = asyncio.create_task(self._consume())

    # ---- Vexa API calls ------------------------------------------------------

    @property
    def _configured(self) -> bool:
        return bool(self._api_base_url and self._api_key)

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            # Lazy, loop-bound construction — never at provider construction
            # (module/import time): httpcore binds its connection pool to the
            # running event loop, same rationale as main.py's lifespan note.
            self._http_client = httpx.AsyncClient(timeout=self._connect_timeout_seconds)
        return self._http_client

    async def _spawn_bot(self) -> None:
        client = await self._client()
        # POST /bots — the sealed MeetingCreate is an open object; these are
        # the fields this app genuinely needs (verified against bot_spawn/
        # router.py). transcribe_enabled must be true or the bot captures
        # and transcribes nothing (README: POST /bots 503s without STT).
        # passcode is Vexa's NATIVE field for passcode-protected meetings
        # (bot_spawn/router.py: body.get("passcode")) — sent only when the
        # user supplied one for this attempt; never persisted or logged.
        payload = {
            "platform": "zoom",
            "native_meeting_id": self._native_meeting_id,
            "meeting_url": self._meeting_url,
            "bot_name": self._bot_name,
            "language": self._language,
            "transcribe_enabled": True,
        }
        if self._passcode:
            payload["passcode"] = self._passcode
        response = await client.post(
            f"{self._api_base_url}/bots",
            headers={"X-API-Key": self._api_key},
            json=payload,
        )
        response.raise_for_status()
        # Internal meeting row id — the detail endpoint is where Vexa
        # records join-failure diagnostics (incl. passcode_required).
        try:
            self._meeting_id = (response.json() or {}).get("id")
        except Exception:
            self._meeting_id = None

    async def _get_meeting(self, meeting_id: int) -> dict:
        client = await self._client()
        response = await client.get(
            f"{self._api_base_url}/meetings/{meeting_id}",
            headers={"X-API-Key": self._api_key},
        )
        response.raise_for_status()
        return response.json()

    async def _check_passcode_required(self) -> bool:
        """Ask Vexa whether the current meeting ended up needing a
        passcode. Vexa's own join.ts throws a structured
        `passcode_required` error when the web client demands a passcode
        and none was provided; meeting-api records it in the meeting
        row's diagnostics, which the DETAIL endpoint (full data retained,
        collector/app.py GET /meetings/{id}) exposes. The marker string
        is exact — a generic join failure never matches it, so genuine
        errors still resolve to DEGRADED instead of being masked as
        passcode-required. Returns True when the status has been set."""
        if self._meeting_id is None or self._status == STATUS_PASSCODE_REQUIRED:
            return False
        try:
            meeting = await self._get_meeting(self._meeting_id)
        except Exception:
            return False
        if meeting.get("status") not in ("failed", "needs_human_help"):
            return False
        if "passcode_required" in json.dumps(meeting.get("data") or {}):
            logger.warning(
                "Vexa: meeting %s requires a passcode — the panel will ask the user "
                "for one (meeting_uuid=%r)",
                self._native_meeting_id,
                self._meeting_uuid,
            )
            self._status = STATUS_PASSCODE_REQUIRED
            return True
        return False

    async def _request_bot_stop(self) -> None:
        client = await self._client()
        try:
            response = await client.delete(
                f"{self._api_base_url}/bots/zoom/{self._native_meeting_id}",
                headers={"X-API-Key": self._api_key},
            )
            response.raise_for_status()
        except Exception:
            # Best effort — the bot also leaves when the meeting ends; the
            # lifecycle state on Vexa's side is not this app's to guarantee.
            logger.warning(
                "Vexa: bot stop request failed for meeting_uuid=%r (ignored)",
                self._meeting_uuid,
            )

    async def _get_transcript(self) -> dict:
        client = await self._client()
        response = await client.get(
            f"{self._api_base_url}/transcripts/zoom/{self._native_meeting_id}",
            headers={"X-API-Key": self._api_key},
        )
        response.raise_for_status()
        return response.json()

    # ---- consumption: websocket primary, polling fallback --------------------

    async def _consume(self) -> None:
        # WebSocket is the realtime transport; polling is a FALLBACK — it
        # must NOT re-read segments already delivered over WS (that doubles
        # every utterance).  When WS connects/subscribes successfully we
        # skip polling entirely; REST only runs when WS is unavailable.
        if self._api_base_url.startswith(("ws://", "wss://")):
            ws_base = self._api_base_url
        else:
            scheme = "wss" if self._api_base_url.startswith("https://") else "ws"
            ws_base = scheme + self._api_base_url[len("http") :]
        if self._configured:
            ws_ok = await self._consume_ws(f"{ws_base}/ws")
            if ws_ok:
                return  # WS delivered everything — no polling needed
            logger.warning(
                "Vexa: websocket stream unavailable for meeting_uuid=%r — "
                "falling back to transcript polling.",
                self._meeting_uuid,
            )
        await self._consume_polling()

    async def _consume_ws(self, ws_url: str) -> bool:
        attempt = 0
        while True:
            socket = None
            try:
                # websockets >= 14 renamed `extra_headers` to
                # `additional_headers` (the old name raises TypeError there,
                # which previously sent every connect straight to the
                # polling fallback — the realtime path silently degraded).
                # Try the new name first, fall back to the old one.
                try:
                    socket = await self._connect(
                        ws_url, additional_headers={"x-api-key": self._api_key}
                    )
                except TypeError:
                    socket = await self._connect(
                        ws_url, extra_headers={"x-api-key": self._api_key}
                    )
                self._socket = socket
                await socket.send(
                    json.dumps(
                        {
                            "action": "subscribe",
                            "meetings": [
                                {
                                    "platform": "zoom",
                                    "native_id": self._native_meeting_id,
                                }
                            ],
                        }
                    )
                )
                # NOTE: attempt is intentionally NOT reset here — the inner
                # loop below only exits via exception, so a reset on "connect
                # succeeded" would erase accumulated failures and reconnect
                # forever without ever giving up.
                while True:
                    raw = await asyncio.wait_for(socket.recv(), timeout=self._read_timeout_seconds)
                    try:
                        message = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    await self._handle_ws_message(message)
                    # Stabiliser tick: emit any utterance whose stability
                    # window has expired.  Without this the WS path — the
                    # primary realtime transport — never flushes buffered
                    # utterances until the next distinct utterance from the
                    # same speaker arrives, and the final utterance of each
                    # speaker is permanently buffered until stop().
                    for stable_speaker, stable_text, _ in self._stabilizer.tick():
                        await self._emit(stable_text, stable_speaker)
            except asyncio.CancelledError:
                return True  # stopping — caller exits the consume loop
            except Exception:
                attempt += 1
                if attempt > self._reconnect_attempts:
                    return False
                await asyncio.sleep(self._reconnect_backoff_seconds * attempt)
            finally:
                if socket is not None:
                    await self._safe_close(socket)
                    if self._socket is socket:
                        self._socket = None

    async def _handle_ws_message(self, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "transcript":
            # The per-speaker bundle: confirmed[] are finalized segments,
            # pending[] are interim hypotheses — emit only confirmed (the
            # Batcher's final-only rule).
            for segment in message.get("confirmed", []) or []:
                if isinstance(segment, dict):
                    await self._ingest_segment(segment, final=True)
        elif msg_type == "transcription_segment":
            if message.get("completed") is not False:
                await self._ingest_segment(message, final=True)
        elif msg_type == "meeting.status":
            await self._handle_meeting_status(
                (message.get("payload") or {}).get("status"), message.get("meeting") or {}
            )
        # Any other type is forwarded by the gateway untouched — ignored.

    async def _handle_meeting_status(self, status: str | None, meeting: dict) -> None:
        if status == _VEXA_STATUS_ACTIVE:
            self._status = STATUS_LIVE
        elif status in (_VEXA_STATUS_FAILED, _VEXA_STATUS_NEEDS_HUMAN_HELP):
            # Passcode detection must run on the WebSocket path too: with WS
            # primary the polling loop (which originally owned the check)
            # never runs, and a passcode-blocked meeting would otherwise be
            # mislabeled plain DEGRADED instead of prompting for a passcode.
            if await self._check_passcode_required():
                return
            logger.warning(
                "Vexa: bot status %r for meeting_uuid=%r — live transcription "
                "unavailable; manual input remains available.",
                status,
                self._meeting_uuid,
            )
            self._status = STATUS_DEGRADED
        elif status in (_VEXA_STATUS_STOPPING, _VEXA_STATUS_COMPLETED):
            if self._status not in (STATUS_STOPPED,):
                self._status = STATUS_STOPPED

    async def _consume_polling(self) -> None:
        failures = 0
        while True:
            try:
                # Passcode detection runs before the transcript read and is
                # independent of it: a passcode-blocked meeting has no
                # transcript rows, so the 404s below would otherwise win
                # the race and mislabel the failure as plain DEGRADED.
                if await self._check_passcode_required():
                    return  # panel asks the user; retry spawns a new consumer
                doc = await self._get_transcript()
                failures = 0
                for segment in doc.get("segments", []) or []:
                    if isinstance(segment, dict):
                        await self._ingest_segment(segment, final=True)
            except asyncio.CancelledError:
                return
            except Exception:
                failures += 1
                if failures >= _MAX_POLL_FAILURES:
                    logger.warning(
                        "Vexa: transcript polling failing for meeting_uuid=%r — "
                        "live transcription unavailable; manual input remains available.",
                        self._meeting_uuid,
                    )
                    self._status = STATUS_DEGRADED
                    return
            # Stabiliser tick: emit any utterance whose stability window
            # has expired (progressive segments that stopped extending).
            for stable_speaker, stable_text, _ in self._stabilizer.tick():
                await self._emit(stable_text, stable_speaker)
            await asyncio.sleep(self._poll_interval_seconds)

    # ---- normalization ---------------------------------------------------------

    async def _ingest_segment(self, segment: dict, *, final: bool) -> None:
        text = (segment.get("text") or "").strip()
        if not text:
            return
        if not final:
            return  # interim hypothesis — never reaches the Batcher
        # Content dedup: identical (speaker, text) pairs are blocked
        # regardless of minor timestamp differences — Vexa may deliver
        # the same segment via WS and REST with slightly different float
        # vs string timestamps that produce different dedup keys.
        speaker = segment.get("speaker")
        ts = segment.get("absolute_start_time") or segment.get("created_at") or segment.get("start")
        text_key = (text.casefold(),)  # dedup by text only — speaker varies on re-delivery
        if text_key in self._seen:
            return
        self._seen.add(text_key)
        # Route through the stabilizer: progressive extensions are merged;
        # distinct utterances are emitted immediately.
        for stable_speaker, stable_text, _stable_ts in self._stabilizer.add(
            text, speaker, ts
        ):
            await self._emit(stable_text, stable_speaker)

    async def _emit(self, text: str, speaker: str | None, is_correction: bool = False) -> TranscriptEvent:
        # First Vexa segment is the "transcript connectivity established"
        # signal: CONNECTING → LIVE. A manual submit after a deliberate stop
        # must NOT flip STOPPED back to LIVE — same convention as the other
        # two providers.
        if self._status == STATUS_CONNECTING:
            self._status = STATUS_LIVE
        self._sequence += 1
        event = TranscriptEvent(
            text=text, timestamp=time.time(), sequence=self._sequence, speaker=speaker, is_correction=is_correction
        )
        await self._queue.put(event)
        return event

    # ---- plumbing -----------------------------------------------------------------

    @staticmethod
    async def _safe_close(socket: Any) -> None:
        try:
            await socket.close()
        except Exception:
            pass

    @staticmethod
    async def _safe_aclose(client: httpx.AsyncClient) -> None:
        try:
            await client.aclose()
        except Exception:
            pass
