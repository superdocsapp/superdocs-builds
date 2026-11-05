"""Placeholder concept art, generated in pure Python.

No Pillow, no binary blobs in the repo, no downloading someone else's art.
`zlib` and `struct` are in the standard library and a PNG is a short file
format, so the demo can generate its own images on a fresh clone with nothing
installed.

These are honestly labelled as placeholders everywhere they appear. They are
not concept art; they are a deterministic gradient with a silhouette on it,
sized and captioned like concept art, so the image path through the API is
exercised with real bytes.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, width: int, height: int, pixels: list[list[tuple[int, int, int]]]) -> Path:
    raw = b"".join(
        b"\x00" + b"".join(struct.pack("3B", *px) for px in row) for row in pixels
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def concept_plate(
    path: Path,
    *,
    width: int = 320,
    height: int = 180,
    top: tuple[int, int, int] = (13, 71, 161),
    bottom: tuple[int, int, int] = (55, 71, 79),
    accent: tuple[int, int, int] = (232, 163, 61),
    seed: int = 1,
) -> Path:
    """A vertical gradient with a deterministic wreck silhouette on it.

    The silhouette is drawn from a tiny integer hash of `seed`, so two plates
    with different seeds look different and the same seed always reproduces the
    same bytes - which matters, because these files are committed and a demo
    that regenerates them must not churn the diff.
    """
    rows: list[list[tuple[int, int, int]]] = []
    heights = [
        int(height * (0.55 + 0.30 * (((x * 7919 + seed * 104729) % 97) / 97.0)))
        for x in range(0, width, 16)
    ]
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        base = _lerp(top, bottom, y / max(1, height - 1))
        for x in range(width):
            silhouette_top = height - heights[min(x // 16, len(heights) - 1)]
            if y > silhouette_top:
                row.append((26, 32, 39))
            elif abs(y - silhouette_top) <= 1:
                row.append(accent)
            else:
                row.append(base)
        rows.append(row)
    return write_png(path, width, height, rows)


def ensure_demo_images(out_dir: Path) -> dict[str, Path]:
    """The two plates the demo embeds. Idempotent: regenerating is byte-stable."""
    out_dir = Path(out_dir)
    return {
        "drift-belt": concept_plate(out_dir / "concept-drift-belt.png", seed=3),
        "foundry": concept_plate(
            out_dir / "concept-foundry.png", seed=11,
            top=(38, 50, 56), bottom=(84, 110, 122), accent=(61, 111, 232),
        ),
    }
