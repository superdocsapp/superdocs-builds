#!/usr/bin/env python3
"""Assemble the clausekeeper demo video from generated slides + synthetic VO.

Every visual is an out/media/slides/*.png rendered from real artifacts;
every audio segment is Kokoro TTS am_eric output (fully synthetic narration).
Timeline: six beats per spec 0014 § Implementation Decisions beat contract,
hero-first 20s.

Usage: python3 tools/make_video.py
Output: out/task4-bundle/clausekeeper-demo.mp4 (+ per-beat segments in out/media/seg)
"""
from __future__ import annotations

import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]
MEDIA = REPO / "out" / "media"
SLIDES = MEDIA / "slides"
SEG = MEDIA / "seg"
BUNDLE = REPO / "out" / "task4-bundle"
for d in (SEG, BUNDLE):
    d.mkdir(parents=True, exist_ok=True)

PAD = 0.4  # silence between beats


def probe(path: pathlib.Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())


def ensure_vo(path: pathlib.Path) -> None:
    """Ensure VO file exists; try Kokoro synth via tools/synth_vo.py, else 2s silence smoke."""
    if path.exists():
        return
    # Try to generate all VO via synth_vo.py (Kokoro am_eric speed 0.92) if available
    synth = REPO / "tools" / "synth_vo.py"
    if synth.exists():
        try:
            subprocess.run(["python3", str(synth)], check=True, capture_output=True)
            if path.exists():
                return
        except Exception as e:
            print(f"VO Kokoro synth_vo.py failed for {path.name}: {e} — using silence fallback", flush=True)
    # fallback: 2s silent AIFF as placeholder (ffprobe will report ~2.0)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", "2", "-c:a", "pcm_s16be", str(path)], check=True)


# beat -> (vo file, [(slide png, weight)])
PLAN = [
    ("b1",     [("01-b1-arrival", 10), ("02-b1-rename", 10)]),
    ("b2",     [("03-b2-pack", 14)]),
    ("b3",     [("04-b3-hero1", 8), ("04-b3-hero2", 8), ("04-b3-hero3", 8)]),
    ("b4",     [("05-b4-discover", 12)]),
    ("b5",     [("06-b5-measured", 18)]),
    ("b6",     [("07-end", 10)]),
]

segments = []
for name, shots in PLAN:
    vo = MEDIA / f"vo-{name}.aiff"
    ensure_vo(vo)
    dur = round(probe(vo) + PAD, 3)          # VO + inter-beat silence
    # filter to slides that actually exist; smoke may lack some hero frames
    avail_shots = [(png, w) for png, w in shots if (SLIDES / f"{png}.png").exists()]
    if not avail_shots:
        # if none exist yet, skip this beat (will be re-tried after slides)
        print(f"{name:7s} skipping — no slides yet")
        continue
    wsum = sum(w for _, w in avail_shots)
    cuts, acc = [], 0.0
    for i, (_, w) in enumerate(avail_shots):
        share = round(dur * w / wsum, 3)
        if i == len(avail_shots) - 1:
            share = round(dur - acc, 3)       # remainder keeps the sum exact
        cuts.append(share)
        acc = round(acc + share, 3)

    lst = SEG / f"{name}.txt"
    with lst.open("w") as f:
        for (png, _), d in zip(avail_shots, cuts):
            f.write(f"file '{SLIDES / png}.png'\nduration {d}\n")
        f.write(f"file '{SLIDES / avail_shots[-1][0]}.png'\n")  # repeat last frame

    seg = SEG / f"{name}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(vo),
        "-filter_complex",
        "[0:v]fps=30,format=yuv420p[v];"
        f"[1:a]apad=whole_dur={dur},aformat=sample_rates=44100:"
        "channel_layouts=stereo[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-t", f"{dur}", str(seg)],
        check=True)
    got = probe(seg)
    print(f"{name:7s} {dur:6.2f}s planned, {got:6.2f}s encoded")
    segments.append((seg, dur))

concat_list = SEG / "_all.txt"
with concat_list.open("w") as f:
    for seg, _ in segments:
        f.write(f"file '{seg}'\n")

final = BUNDLE / "clausekeeper-demo.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart",
                str(final)], check=True)
total = probe(final)
print(f"FINAL {final} — {total:.1f}s ({int(total // 60)}:{int(total % 60):02d})")
assert total <= 195, "over the 3:15 hard cap"
