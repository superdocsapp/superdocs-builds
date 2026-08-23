#!/usr/bin/env python3
"""Deterministic SOW benchmark harness.

Feeds the committed 58-second ElevenLabs SOW audio through the SAME
production pipeline the Swift audio-fetcher uses — same pause-bounded
chunking (12s ceiling @ 48k),
same RMS gate (0.008), same POST /audio wire format — against a LOCAL
backend (make dev, :8010). No microphone, no live playback, no DNS.

Run:  python benchmarks/run_benchmark.py [audio.mp3] [meeting-name]
"""

import base64
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from urllib.error import URLError
import wave

AUDIO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "sow-58s.mp3")
# Fresh meeting per run — a reused name collides with the previous run's
# still-live session (events from both runs interleave; SuperDocs 409s).
MEETING = sys.argv[2] if len(sys.argv) > 2 else f"benchmark-sow-{int(time.time())}"
BACKEND = os.environ.get("BENCHMARK_BACKEND", "http://localhost:8010")


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sslctx import ssl_context_for  # noqa: E402

_SSL_CTX = ssl_context_for(BACKEND)

RATE = 48000
CHUNK = 576000          # 12s @ 48k — CEILING, matches audio-fetcher
MIN_CHUNK = 144000      # 3s — never end a chunk shorter than this
SILENCE_TAIL = 28800    # 0.6s of trailing samples inspected for a pause
SILENCE_AMPLITUDE = 500 # |sample| below this counts as silence
RMS_MIN = 0.008         # matches audio-fetcher
OVERLAP = 72000         # 1.5s replayed head — matches AudioChunkSender.overlapSize
SETTLE_POLLS = 240   # up to ~40 min — gated batches take minutes each


def b64u(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def decode_to_int16(path: str) -> list[int]:
    """MP3/M4A/etc → 48kHz mono Int16 via ffmpeg. Returns raw samples."""
    wav = path + ".wav"
    if not os.path.exists(wav):
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ar", str(RATE), "-ac", "1",
             "-c:a", "pcm_s16le", wav],
            check=True, capture_output=True,
        )
    with wave.open(wav) as wf:
        assert wf.getframerate() == RATE, wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    return [int.from_bytes(raw[i:i + 2], "little", signed=True) for i in range(0, len(raw), 2)]


def rms(chunk: list[int]) -> float:
    return math.sqrt(sum((s / 32767.0) ** 2 for s in chunk) / len(chunk))


# Local DNS on this machine is documented-flaky (see HANDOVER.md) —
# transient getaddrinfo failures, not a backend problem. 3 attempts, short
# backoff, mirrors the retry the real Swift audio-fetcher already does on
# its own POSTs.
def _retry(fn, attempts=3, delay=2.0):
    for attempt in range(attempts):
        try:
            return fn()
        except (URLError, OSError):
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def post_audio(samples: list[int]) -> dict:
    body = json.dumps({"samples": samples, "sample_rate": RATE}).encode()

    def _do():
        req = urllib.request.Request(
            f"{BACKEND}/api/meetings/{b64u(MEETING)}/audio",
            data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=_SSL_CTX) as r:
            return json.loads(r.read())

    return _retry(_do)


def get_state() -> dict:
    def _do():
        with urllib.request.urlopen(f"{BACKEND}/api/meetings/{b64u(MEETING)}/state", context=_SSL_CTX) as r:
            return json.loads(r.read())

    return _retry(_do)


def main() -> int:
    samples = decode_to_int16(AUDIO)
    seconds = len(samples) / RATE
    print(f"decoded {AUDIO}: {seconds:.1f}s @ {RATE}Hz mono Int16 ({len(samples)} samples)")

    # Mirror the audio-fetcher exactly (AudioChunkSender.endsOnAPause):
    # a chunk ends at a PAUSE, and at CHUNK only when the speaker has not
    # drawn breath for that long. A fixed slice cuts mid-sentence, and
    # Whisper answers a half sentence by inventing an ending for it. Each
    # chunk still carries the previous chunk's last 1.5s so a word on the
    # boundary is heard whole at least once.
    raw, buf = [], []
    step = int(0.2 * RATE)
    for i in range(0, len(samples), step):
        buf.extend(samples[i:i + step])
        paused = (
            len(buf) >= MIN_CHUNK
            and max((abs(x) for x in buf[-SILENCE_TAIL:]), default=0) < SILENCE_AMPLITUDE
        )
        if len(buf) >= CHUNK or paused:
            raw.append(buf)
            buf = []
    if buf:
        raw.append(buf)
    chunks = []
    for i, c in enumerate(raw):
        chunks.append((raw[i - 1][-OVERLAP:] if i else []) + c)
    print(f"chunks: {len(chunks)} (pause-bounded, {CHUNK/RATE:.0f}s ceiling)")
    sent = skipped = 0
    for i, chunk in enumerate(chunks):
        r = rms(chunk)
        if r <= RMS_MIN:
            skipped += 1
            print(f"chunk {i}: SKIP rms={r:.4f}")
            continue
        resp = post_audio(chunk)
        sent += 1
        secs = len(chunk) / RATE
        print(f"chunk {i}: SENT {secs:.1f}s rms={r:.4f} text={resp.get('text', '')[:60]!r}")
        # Real time, not a fixed gap: the fetcher emits a chunk only after
        # capturing it, so a 4s chunk arrives 4s later, not 6s later.
        time.sleep(secs)

    print(f"\nchunks sent={sent} skipped={skipped}")
    print("waiting for drafting pipeline to settle...")

    # Settle = every event consumed into an activity entry AND a terminal
    # job status. 'polling' means a batch is still mid-gate — waiting on a
    # stable version alone stops the harness in the middle of the run.
    final = None
    for _ in range(SETTLE_POLLS):
        try:
            st = get_state()
        except Exception:
            time.sleep(5)
            continue
        done = len(st["activity"]) >= len(st["transcript_history"])
        terminal = st["job_status"] in ("completed", "error", "blocked")
        if done and terminal:
            final = st
            break
        time.sleep(10)

    if final is None:
        final = get_state()
    print(f"\n=== SETTLED: v{final['draft_version']} {final['job_status']} "
          f"({len(final['activity'])} batches) error={final.get('error') or 'none'!r} ===")
    for a in final["activity"]:
        print(f"  batch: {a['classification']:10} {a['summary'][:70]!r}")
    print("\n=== FINAL DOCUMENT HTML ===")
    print(final["current_draft_html"])
    with open(os.path.join(os.path.dirname(__file__), "last_result.json"), "w") as f:
        json.dump(final, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
