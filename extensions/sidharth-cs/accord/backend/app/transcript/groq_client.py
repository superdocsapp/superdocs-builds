"""Minimal Groq STT client — OpenAI-compatible audio transcription endpoint.
Uses httpx (already a project dependency). No groq SDK needed."""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave

import httpx

logger = logging.getLogger("groq")

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Full large-v3, not turbo — turbo trades accuracy for speed; on 4s chunks
# with no cross-chunk context, the accuracy loss shows up as wrong words
# (e.g. "cart" cut into "car" at a chunk boundary, or a name mis-heard
# entirely). Slower per chunk, but chunks are already processed async
# relative to capture, so this doesn't block audio capture itself.
GROQ_MODEL = "whisper-large-v3"

# Bounded retry budget for transient 429 rate limits. A 429 is recoverable;
# the budget keeps one slow client from hammering the API forever. After
# exhaustion the caller gets GroqRateLimitExhausted and decides (503 vs drop).
_MAX_429_RETRIES = 3


class GroqRateLimitExhausted(Exception):
    """Raised after the bounded 429 retry budget is spent. Distinct from
    other Groq failures so the API layer can map it to a transient status."""


def _retry_delay_seconds(headers: httpx.Headers, attempt: int) -> float:
    """Respect Retry-After when present (superior to guessing), else
    exponential backoff 1s, 2s, 4s."""
    raw = headers.get("retry-after")
    if raw and raw.isdigit():
        return min(float(raw), 30.0)
    return float(2 ** attempt)


class GroqSTTClient:
    def __init__(self, api_key: str, timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url="https://api.groq.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout, connect=15.0),
            transport=transport,
        )
        self._api_key = api_key

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(
        self,
        pcm_samples: list[int],
        sample_rate: int = 16000,
        prompt: str | None = None,
    ) -> str:
        """Transcribe 16-bit PCM audio samples.  Returns the transcript text,
        or raises on error.

        `prompt` is optional Whisper continuation/vocabulary context only —
        a bounded recent transcript (proper nouns, domain terms) that helps
        the model stay consistent across independent 2s chunks. It never
        replaces the audio itself: the model still transcribes what it
        hears. Omitted entirely when empty (no previous speech), since an
        empty prompt field is meaningless to Whisper."""
        # Build a WAV in memory from raw PCM samples
        wav_bytes = _pcm_to_wav(pcm_samples, sample_rate)

        files: dict[str, tuple] = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
            "model": (None, GROQ_MODEL),
            "response_format": (None, "json"),
            # Explicit language: short 2s chunks otherwise pay a
            # per-chunk auto-detection pass, and auto-detection on a
            # fragment can pick a wrong language. The meeting is English.
            "language": (None, "en"),
        }
        if prompt:
            files["prompt"] = (None, prompt)

        for attempt in range(_MAX_429_RETRIES):
            start = time.monotonic()
            response = await self._client.post(
                "/openai/v1/audio/transcriptions",
                files=files,
            )
            elapsed = time.monotonic() - start
            if response.status_code == 429:
                # Transient rate limit — bounded backoff, then give up
                # explicitly (never a silent drop, never an unbounded loop).
                if attempt < _MAX_429_RETRIES - 1:
                    delay = _retry_delay_seconds(response.headers, attempt)
                    logger.warning(
                        "Groq 429 attempt %d/%d — retrying in %.1fs",
                        attempt + 1, _MAX_429_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("Groq 429 exhausted after %d attempts", _MAX_429_RETRIES)
                raise GroqRateLimitExhausted(
                    f"Groq rate limit exceeded after {_MAX_429_RETRIES} attempts"
                )
            response.raise_for_status()
            data = response.json()
            text = (data.get("text") or "").strip()
            logger.info("Groq: %.1fs -> %r", elapsed, text[:80])
            return text
        raise GroqRateLimitExhausted("Groq rate limit exceeded")


def _pcm_to_wav(samples: list[int], sample_rate: int = 16000) -> bytes:
    """Convert 16-bit mono PCM samples to a WAV byte buffer."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(
            max(-32768, min(32767, s)).to_bytes(2, "little", signed=True)
            for s in samples
        ))
    return buf.getvalue()
