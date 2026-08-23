"""POST /api/meetings/{uuid}/audio — accept PCM audio, transcribe via Groq,
feed transcript into the existing MeetingSession pipeline."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.encoding import decode_meeting_uuid
from app.core.config import get_settings
from app.drafting.classifier import strip_asr_hallucinations
from app.drafting.session import get_or_create_session
from app.transcript.groq_client import GroqRateLimitExhausted, GroqSTTClient

logger = logging.getLogger("routes.audio")
router = APIRouter()


class AudioChunkRequest(BaseModel):
    """PCM 16-bit mono audio samples as a list of integers."""
    samples: list[int]
    sample_rate: int = 16000


# Lazy-constructed Groq client — bound to the running event loop
_groq_client: GroqSTTClient | None = None


def _get_groq_client() -> GroqSTTClient:
    global _groq_client
    if _groq_client is None:
        settings = get_settings()
        key = settings.groq_api_key
        if not key:
            raise HTTPException(500, "Groq API key not configured")
        _groq_client = GroqSTTClient(api_key=key)
    return _groq_client


_WORD_RE = re.compile(r"[a-z0-9']+")

# Most words the replayed tail can account for. 1.5s of speech is ~5 words;
# the ceiling keeps a genuine repetition ("very, very tight") from being
# mistaken for overlap and silently deleted.
_MAX_OVERLAP_WORDS = 12


def _norm_words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


# How close the replayed tail must be to count as the same speech. Exact
# word equality is too strict: Whisper transcribes the SAME audio
# differently on either side of a boundary — one live run produced
# "...on September 15th, and the final" followed by "15, and the final
# website...", so an exact match saw no overlap and the phrase was written
# into the document twice.
_OVERLAP_SIMILARITY = 0.75


def _dedupe_overlap(session, text: str) -> str:
    """Drop the leading words of `text` that merely repeat the tail of the
    previous chunk.

    Finds the longest suffix of the previous transcript that also opens this
    one and removes it. Matching is fuzzy, on normalised words, because the
    replayed audio is re-transcribed rather than copied. Nothing is removed
    when no alignment is confident enough — a missed dedupe leaves a
    duplicated phrase, which the gate catches, while an over-eager one would
    delete real speech."""
    previous = getattr(session, "_last_chunk_words", None)
    session._last_chunk_words = _norm_words(text)[-_MAX_OVERLAP_WORDS:]
    if not previous:
        return text

    words = _norm_words(text)
    for n in range(min(len(previous), len(words), _MAX_OVERLAP_WORDS), 0, -1):
        tail, head = previous[-n:], words[:n]
        if tail == head or (
            n >= 2
            and SequenceMatcher(None, " ".join(tail), " ".join(head)).ratio()
            >= _OVERLAP_SIMILARITY
        ):
            # Skip n words in the ORIGINAL string, preserving its casing
            # and punctuation for everything that remains.
            pos, seen = 0, 0
            for m in _WORD_RE.finditer(text.lower()):
                seen += 1
                if seen == n:
                    pos = m.end()
                    break
            return text[pos:].lstrip(" ,.;:-").strip()
    return text


# How long a quiet tail has to be before it counts as the speaker pausing
# rather than drawing breath. Word gaps run ~200ms; a topic boundary is much
# longer. 1.2s sits clearly between the two.
# 1.2s caught ordinary gaps BETWEEN PHRASES, not just topic boundaries — a
# live run fragmented into one-clause batches because of it. A deliberate
# topic pause is nearer 2s; normal sentence gaps sit below that.
_PAUSE_TAIL_SECONDS = 2.0
# 16-bit PCM. Room tone and mic noise sit well under this; speech does not.
_SILENCE_AMPLITUDE = 500


def ends_with_silence(samples: list[int], sample_rate: int) -> bool:
    """Does this chunk end with a pause long enough to be a topic boundary?

    The batcher's silence gap measures time between chunk ARRIVALS, and on the
    audio path chunks arrive on a fixed 6s clock regardless of content — so a
    speaker pausing produces no signal and the gap can never open. The pause is
    only visible in the samples themselves.

    A chunk that is silent throughout is NOT a pause: those are a muted mic or
    a dropout, and flushing on them would fire repeatedly on an empty room.
    """
    tail = int(_PAUSE_TAIL_SECONDS * sample_rate)
    if len(samples) < tail * 2:
        return False
    if all(abs(s) <= _SILENCE_AMPLITUDE for s in samples):
        return False
    return all(abs(s) <= _SILENCE_AMPLITUDE for s in samples[-tail:])


@router.post("/api/meetings/{meeting_uuid}/audio")
async def ingest_audio(meeting_uuid: str, body: AudioChunkRequest, request: Request):
    """Accept a chunk of 16-bit mono PCM audio, transcribe via Groq, and feed
    the resulting transcript text into the meeting session pipeline."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)

    if not body.samples or len(body.samples) < 100:
        raise HTTPException(422, "audio chunk too small — send at least 100 samples")

    try:
        client = _get_groq_client()
        # Still no dynamic Whisper prompt: feeding the previous transcript
        # back as context made Whisper treat corrupted boundary splits as
        # confirmed prior speech, compounding them into a self-reinforcing
        # hallucination ("Nothar Go. Goods. A massive website." ×4 in the
        # 65s benchmark). Boundary context now comes from overlapping the
        # AUDIO instead — the model re-hears the real sound rather than
        # being told what it previously guessed.
        text = await client.transcribe(body.samples, body.sample_rate)
    except GroqRateLimitExhausted as exc:
        # Bounded 429 retries spent — transient, retryable by a client that
        # understands 503. Deliberately distinct from 502 (permanent-failure)
        # so the audiofetcher can retry the same chunk without duplicating.
        logger.warning("Groq rate limit exhausted for meeting %r", meeting_uuid)
        raise HTTPException(503, "Transcription temporarily unavailable — retry") from exc
    except Exception as exc:
        logger.exception("Groq transcription failed for meeting %r", meeting_uuid)
        raise HTTPException(502, f"Groq transcription failed: {exc}") from exc

    if not text:
        return {"text": "", "note": "no speech detected"}

    # Each chunk replays the previous chunk's last 1.5s so a word spanning
    # the boundary is heard whole (see AudioChunkSender.overlapSize). That
    # makes the first few words of every transcript a repeat of the last
    # few of the one before, which is removed here.
    text = _dedupe_overlap(session, text)
    if not text:
        return {"text": "", "note": "overlap only — no new speech"}

    # Whisper answers near-silence with caption-style sign-offs rather than
    # an empty string ("we'll see you next time", "thanks for watching").
    # Dropped here, at the boundary, so an artifact can never become a fact:
    # one reached a live export as "We expect weekly progress updates and
    # we'll see you next time."
    cleaned = strip_asr_hallucinations(text)
    if cleaned != text:
        logger.info("ASR artifact removed: %r -> %r", text[:80], cleaned[:80])
    if not cleaned:
        return {"text": "", "note": "no speech detected"}
    text = cleaned

    # Feed into the existing session pipeline via manual_provider.submit()
    if session.manual_provider is None:
        raise HTTPException(409, "active provider does not accept transcript input")

    event = await session.manual_provider.submit(text)
    logger.info("AUDIO->TRANSCRIPT: uuid=%r queue=%d subs=%d seq=%d text=%r",
        meeting_uuid,
        session.manual_provider._queue.qsize() if hasattr(session.manual_provider, '_queue') else -1,
        len(session._subscribers),
        event.sequence,
        text[:60])

    # The speaker paused. Close the batch here rather than letting it run on
    # into the next topic — this is the ONLY place a pause is visible, because
    # chunks arrive on a fixed clock and the batcher's silence gap measures
    # arrival time, not audio. Best-effort: a failure here costs a
    # topic-aligned boundary, never the transcript.
    paused = ends_with_silence(body.samples, body.sample_rate)
    if paused:
        try:
            await session.batcher.flush_on_pause()
            logger.info("PAUSE detected — batch closed on a topic boundary")
        except Exception:
            logger.warning("pause flush failed (non-fatal)", exc_info=True)

    return {"text": text, "sequence": event.sequence, "paused": paused}
