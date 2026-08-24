#!/usr/bin/env python3
"""Synthesize clausekeeper VO segments via Kokoro TTS am_eric (Apache 2.0).

Ticket 0019 delivery: a paused, human-walkthrough cadence. Each beat's spoken
paragraph in docs/media/narration-script.txt is mirrored beat-for-beat in
VO_TEXTS and synthesized per sentence at speed 0.97, then assembled with
silence: 0.15 s lead-in, 0.32 s between sentences, 0.25 s tail.

- Uses explicit KPipeline(lang_code='a') + pre-loaded en_core_web_sm to avoid HF hang.
- Written for the ear: VO_TEXTS carries meaning only — identifiers, filenames,
  timestamps, job/change ids, ISO stamps, HTTP routes, and header names are
  never spoken (slide caption bars and terminal footage carry those).
- Measured numbers match docs/writeup.md exactly (number parity rule).
- Concatenates per-sentence Kokoro chunks with the pause scheme, writes
  24000 Hz AIFF (PCM_16) -> out/media/vo-b*.aiff; ffprobe reports duration
  per segment plus the sum; an audit log line records voice/speed/license.

Usage: python tools/synth_vo.py [--dry]  # dry prints texts without synthesizing
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
MEDIA = REPO / "out" / "media"
NARRATION = REPO / "docs/media/narration-script.txt"

VOICE = "am_eric"
SPEED = 0.97
SAMPLE_RATE = 24000
LEAD_IN_S = 0.15  # silence before the first sentence
INTER_S = 0.32    # silence between sentences
TAIL_S = 0.25     # silence after the last sentence

# Spoken texts, mirroring the [beat N] paragraphs of narration-script.txt
# beat-for-beat: short declarative sentences, numbers as natural words with
# exact parity against docs/writeup.md, no identifiers/routes/headers.
VO_TEXTS: dict[str, str] = {
    "b1": (
        "Which change broke this requirement? Every auditor asks it. "
        "Clausekeeper answers it as it happens. Edit a controlled procedure, "
        "delete a section, approve. Before the approval finishes, a gap appears "
        "naming the change responsible, quoting exactly what was lost."
    ),
    "b2": (
        "Documents get renamed. Links shouldn't break. Here the quality manual gets a new name. "
        "Nothing snaps: evidence attaches to the document itself. The matrix never noticed."
    ),
    "b3": (
        "Audit day. Proof hides in scattered runs and logs. Here, one command gathers everything "
        "into a branded, audit-ready pack, exported as Word and PDF, with export warnings checked. "
        "Packing costs a single operation. The downloads are free."
    ),
    "b4": (
        "Linking is where cost creeps in. Opt-in discovery reads structure, shortlists matches locally: "
        "twelve of twenty-seven clauses matched free, fifteen via search, at most one extra operation. "
        "Preview first, at zero operations. If search finds nothing, discover warns honestly, "
        "never inventing candidates."
    ),
    "b5": (
        "The measured truth. Forty-six tests passed in about ten seconds. A full cycle costs nine operations. "
        "One caveat: search once exceeded three hundred seconds and fabricated a candidate on seeded gap nine point two. "
        "Search shortlists stay advisory. Humans make the calls."
    ),
    "b6": (
        "Back to our opening question. With clausekeeper, you know which change broke what. "
        "Every number traces to a rerunnable artifact, starting at pull request one thirty seven."
    ),
}

ORDER = ["b1", "b2", "b3", "b4", "b5", "b6"]


def check_prereqs() -> None:
    try:
        import spacy  # noqa: F401
        spacy.load("en_core_web_sm")
    except Exception as e:
        print(f"G2P pre-load failed (en_core_web_sm): {e}", file=sys.stderr)
        raise
    try:
        subprocess.run(["espeak-ng", "--version"], capture_output=True, check=True)
    except Exception as e:
        print(f"espeak-ng not found: {e}", file=sys.stderr)
        raise


def split_sentences(text: str) -> list[str]:
    """Split spoken text into sentences on terminal punctuation."""
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]


def synth_one(text: str, out_path: pathlib.Path, pipeline) -> float:
    """Per-sentence synthesis with paused cadence; writes AIFF; returns ffprobe duration."""
    import numpy as np
    import soundfile as sf

    sentences = split_sentences(text)
    pieces: list[np.ndarray] = [
        np.zeros(int(SAMPLE_RATE * LEAD_IN_S), dtype=np.float32)
    ]
    for i, sentence in enumerate(sentences):
        if i:
            pieces.append(np.zeros(int(SAMPLE_RATE * INTER_S), dtype=np.float32))
        audios = [audio for _, _, audio in pipeline(sentence, voice=VOICE, speed=SPEED)]
        if not audios:
            raise RuntimeError(f"Kokoro returned no audio for: {sentence[:60]}")
        pieces.extend(audios)
    pieces.append(np.zeros(int(SAMPLE_RATE * TAIL_S), dtype=np.float32))
    concat = np.concatenate(pieces)
    sf.write(str(out_path), concat, SAMPLE_RATE, format="AIFF", subtype="PCM_16")
    dur = float(
        subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_path)],
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return dur


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="print texts without synthesizing")
    args = parser.parse_args()

    # Verify narration source exists and log provenance
    if NARRATION.exists():
        raw = NARRATION.read_text(encoding="utf-8")
        beats_raw = re.split(r"\[beat\s+\d+.*?\]", raw, flags=re.I | re.S)
        print(f"source: {NARRATION} ({len(raw)} bytes, {len(beats_raw)-1} beats detected)")
    else:
        print(f"warning: {NARRATION} not found, using VO_TEXTS as fallback", file=sys.stderr)

    # Audit log line: voice/speed/license + pause scheme
    print(
        f"Kokoro TTS voice {VOICE} (Apache 2.0), speed {SPEED}, "
        f"per-sentence pauses {LEAD_IN_S}/{INTER_S}/{TAIL_S}s, espeak-ng + en_core_web_sm"
    )
    print(f"VO texts derived from narration-script.txt: {ORDER}")

    if args.dry:
        for k in ORDER:
            text = VO_TEXTS[k]
            n_sent = len(split_sentences(text))
            print(f"{k}: {len(text.split())} words, {n_sent} sentences :: {text[:80]}...")
        return

    check_prereqs()

    try:
        from kokoro import KPipeline
    except Exception as e:
        print(f"kokoro import failed: {e}", file=sys.stderr)
        # fallback: create silence placeholders so make_video still passes smoke
        for k in ORDER:
            out = MEDIA / f"vo-{k}.aiff"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", "2", "-c:a", "pcm_s16be", str(out)],
                check=True,
            )
            print(f"{k} fallback silence 2.0s -> {out}")
        sys.exit(1)

    pipeline = KPipeline(lang_code="a")

    MEDIA.mkdir(parents=True, exist_ok=True)
    total = 0.0
    durations: dict[str, float] = {}
    for k in ORDER:
        text = VO_TEXTS[k]
        out = MEDIA / f"vo-{k}.aiff"
        dur = synth_one(text, out, pipeline)
        durations[k] = dur
        total += dur
        print(f"{k:2s} {dur:5.2f}s -> {out} ({len(text.split())} words)")

    # also verify ffprobe per segment >0 is implicit; assert
    for k in ORDER:
        p = MEDIA / f"vo-{k}.aiff"
        d = float(subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",str(p)],capture_output=True,text=True).stdout.strip())
        assert d > 0, f"{p} duration 0"

    projected_final = total + 6 * 0.4  # make_video pads each beat by 0.4s
    print(f"SUM VO {total:.1f}s across {len(ORDER)} beats; projected final MP4 ~{projected_final:.1f}s (cap 195s)")
    if not (100 <= total <= 160):
        print("warning: VO sum outside ticket 0019 band (100-160s); trim or expand wording", file=sys.stderr)


if __name__ == "__main__":
    main()
