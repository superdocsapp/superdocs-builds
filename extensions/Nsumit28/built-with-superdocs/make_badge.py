#!/usr/bin/env python3
"""
Build the "built with SuperDocs" attribution badge as a self-contained SVG.

Why a generator and not a hand-drawn SVG: the badge carries no live text. Every
glyph is converted to an outline path, so the file depends on no font, no
stylesheet and no network request. That is not a stylistic choice — it is what
GitHub's image proxy requires. Measured from a real camo response:

    content-security-policy: default-src 'none'; img-src data:; style-src 'unsafe-inline'

`default-src 'none'` with no `font-src` means an @font-face of any kind is
blocked, and camo passes the origin bytes through byte-for-byte (verified by
diffing a camo-served badge against its origin). So the only two ways to put
text in a badge are a system font stack — which cannot render SuperDocs' own
typefaces, since Space Grotesk ships on no operating system — or outlines.
Outlines win: identical on every machine, and on-brand.

Fonts are downloaded on demand and checked against a pinned SHA-256 rather than
committed, so the build is reproducible without carrying 1 MB of binary. Both
are SIL OFL 1.1, which permits shipping outlines derived from them.

Usage:  python3 make_badge.py [--out badge/]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform
import uharfbuzz as hb

HERE = Path(__file__).resolve().parent
FONT_CACHE = HERE / ".fonts"

# --- brand, read out of superdocs.app's own stylesheet, not eyeballed --------
# https://superdocs.app/_next/static/chunks/03kd.8p0ksbwa.css
CORAL = "#f97766"       # --color-coral
NEAR_BLACK = "#110b0b"  # --color-near-black
CREAM = "#fbfaf6"       # --color-cream-white

FONTS = {
    "space-grotesk": {
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/"
               "spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
        "sha256": "acad6de1fc93436f5c0f1f4137751ef04f1aea3063e7036535970ffcfbd79f72",
        "file": "SpaceGrotesk-var.ttf",
    },
    "inter": {
        "url": "https://raw.githubusercontent.com/google/fonts/main/ofl/"
               "inter/Inter%5Bopsz,wght%5D.ttf",
        "sha256": "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
        "file": "Inter-var.ttf",
    },
}

# --- geometry ---------------------------------------------------------------
HEIGHT = 20        # the de-facto badge height; sits inline with shields badges
RADIUS = 3
PAD = 7            # horizontal breathing room either side of each label
FONT_SIZE = 11     # shields' size, kept so a row of badges looks like a row


def fetch_font(key: str) -> Path:
    spec = FONTS[key]
    FONT_CACHE.mkdir(exist_ok=True)
    path = FONT_CACHE / spec["file"]
    if not path.exists():
        with urllib.request.urlopen(spec["url"], timeout=60) as r:
            data = r.read()
        path.write_bytes(data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if spec["sha256"] and digest != spec["sha256"]:
        raise SystemExit(
            f"{spec['file']}: sha256 {digest} != pinned {spec['sha256']}. "
            "Upstream changed; re-pin deliberately."
        )
    spec["_digest"] = digest
    return path


def instance(path: Path, **axes) -> TTFont:
    """Freeze a variable font at one weight so glyph outlines are unambiguous."""
    font = TTFont(str(path))
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, axes, inplace=False)
    return font


def shape(font: TTFont, text: str, size: float):
    """Shape with HarfBuzz so kerning is real, not an advance-width sum.

    Returns (list of (glyph_name, x_px, y_px), total_advance_px).
    """
    buf = io.BytesIO()
    font.save(buf)
    blob = hb.Blob(buf.getvalue())
    face = hb.Face(blob)
    hb_font = hb.Font(face)

    upem = face.upem
    buf_hb = hb.Buffer()
    buf_hb.add_str(text)
    buf_hb.guess_segment_properties()
    hb.shape(hb_font, buf_hb, {"kern": True, "liga": True})

    order = font.getGlyphOrder()
    scale = size / upem
    placed, x = [], 0.0
    for info, pos in zip(buf_hb.glyph_infos, buf_hb.glyph_positions):
        placed.append((order[info.codepoint],
                       (x + pos.x_offset) * scale,
                       pos.y_offset * scale))
        x += pos.x_advance
    return placed, x * scale


def outline(font: TTFont, placed, size: float, baseline: float) -> str:
    """Convert shaped glyphs to one SVG path `d`, y-flipped into SVG space."""
    upem = font["head"].unitsPerEm
    glyphs = font.getGlyphSet()
    scale = size / upem
    parts = []
    for name, x_px, y_px in placed:
        if name not in glyphs:
            continue
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
        # y is negated: font space is y-up, SVG is y-down.
        tp = TransformPen(pen, Transform(scale, 0, 0, -scale,
                                         x_px, baseline - y_px))
        glyphs[name].draw(tp)
        d = pen.getCommands()
        if d:
            parts.append(d)
    return "".join(parts)


def cap_baseline(font: TTFont, size: float) -> float:
    """Baseline y that optically centres capitals in a HEIGHT-tall badge."""
    upem = font["head"].unitsPerEm
    os2 = font["OS/2"]
    cap = getattr(os2, "sCapHeight", None) or int(upem * 0.7)
    cap_px = cap * size / upem
    return (HEIGHT + cap_px) / 2


def build(label: str, message: str) -> str:
    grotesk = instance(fetch_font("space-grotesk"), wght=700)
    inter = instance(fetch_font("inter"), wght=500, opsz=14)

    label_placed, label_w = shape(inter, label, FONT_SIZE)
    msg_placed, msg_w = shape(grotesk, message, FONT_SIZE)

    left_w = round(label_w + PAD * 2)
    right_w = round(msg_w + PAD * 2)
    total = left_w + right_w

    label_path = outline(inter, label_placed, FONT_SIZE, cap_baseline(inter, FONT_SIZE))
    msg_path = outline(grotesk, msg_placed, FONT_SIZE, cap_baseline(grotesk, FONT_SIZE))

    alt = f"{label} {message}"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{HEIGHT}" \
viewBox="0 0 {total} {HEIGHT}" role="img" aria-label="{alt}">
<title>{alt}</title>
<clipPath id="bws-clip"><rect width="{total}" height="{HEIGHT}" rx="{RADIUS}"/></clipPath>
<g clip-path="url(#bws-clip)">
<rect width="{left_w}" height="{HEIGHT}" fill="{NEAR_BLACK}"/>
<rect x="{left_w}" width="{right_w}" height="{HEIGHT}" fill="{CORAL}"/>
</g>
<path transform="translate({PAD} 0)" fill="{CREAM}" d="{label_path}"/>
<path transform="translate({left_w + PAD} 0)" fill="{NEAR_BLACK}" d="{msg_path}"/>
<rect x=".5" y=".5" width="{total - 1}" height="{HEIGHT - 1}" rx="{RADIUS - 0.5}" \
fill="none" stroke="{CREAM}" stroke-opacity=".25"/>
</svg>
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--pin", action="store_true",
                    help="print sha256 of each font for pinning, then exit")
    args = ap.parse_args()

    if args.pin:
        for key in FONTS:
            fetch_font(key)
            print(f'{key}: "{FONTS[key]["_digest"]}"')
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    svg = build("built with", "SuperDocs")
    target = out / "badge.svg"
    target.write_text(svg, encoding="utf-8")
    print(f"{target}  {len(svg.encode()):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
