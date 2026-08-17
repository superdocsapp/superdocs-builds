#!/usr/bin/env python3
"""
Check a badge SVG against the constraints GitHub's image proxy actually imposes.

The rules below are not read off a blog post. They are the Content-Security-Policy
that camo.githubusercontent.com returns on a real proxied badge, measured
2026-08-16 by pulling a camo URL out of a rendered README on github.com:

    content-security-policy: default-src 'none'; img-src data:; style-src 'unsafe-inline'
    content-type: image/svg+xml;charset=utf-8
    x-content-type-options: nosniff

and by diffing the camo response against the origin file — **byte-identical**,
so camo alters nothing and rejects nothing after the fetch. Everything that can
go wrong therefore goes wrong inside the file:

  default-src 'none'   no script, no external image, no external <use>, no fetch
  (no font-src at all)  @font-face is blocked -> live text needs an installed font
  img-src data:        raster is allowed only as a data: URI
  style-src unsafe-inline   inline <style> and style="" are fine
  nosniff              the origin must serve exactly image/svg+xml

Plus camo's own ceiling: CAMO_LENGTH_LIMIT defaults to 5 MiB.

Run before any publish:  python3 verify_badge.py badge.svg
Exit status is 0 only if every check passes.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
CAMO_LIMIT = 5 * 1024 * 1024
SANE_BADGE_BYTES = 100 * 1024

# Elements that either execute, fetch, or need a layout engine camo won't give.
FORBIDDEN_TAGS = {
    "script", "foreignObject", "iframe", "image", "audio", "video",
    "animate", "animateMotion", "animateTransform", "set",
}
EXTERNAL_URL = re.compile(r"""(?:https?:)?//|url\(\s*['"]?(?!#)""", re.I)
AT_RULES = re.compile(r"@(font-face|import)", re.I)


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
            self.failures.append(label)

    def note(self, text: str) -> None:
        print(f"  note  {text}")
        self.notes.append(text)


def localname(tag: str) -> str:
    return tag.split("}", 1)[-1]


def verify(path: Path) -> int:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    r = Report()
    print(f"\n{path}  ({len(raw):,} bytes)\n")

    # --- parses at all -----------------------------------------------------
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        # Report a verdict, never a traceback: this runs in a publish gate, and
        # a crash there reads as "the tool is broken", not "the badge is broken".
        r.check(False, "well-formed XML", str(e))
        print("\nFAILED 1 check(s): well-formed XML")
        return 1

    r.check(True, "well-formed XML")
    r.check(root.tag == f"{{{SVG_NS}}}svg", "root is svg in the SVG namespace",
            f"got {root.tag}")

    # --- sizing: GitHub lays the <img> out from these, a missing one collapses
    w, h = root.get("width"), root.get("height")
    r.check(bool(w and h), "explicit width and height on <svg>",
            f"width={w!r} height={h!r}")
    r.check(bool(root.get("viewBox")), "viewBox present (scales cleanly on retina)")

    # --- nothing that executes or fetches ----------------------------------
    tags = {localname(el.tag) for el in root.iter()}
    bad = sorted(tags & FORBIDDEN_TAGS)
    r.check(not bad, "no scripting, animation, or embedded-media elements",
            f"found {bad}")

    # --- no reference leaves the file --------------------------------------
    offenders = []
    for el in root.iter():
        for key, val in el.attrib.items():
            if EXTERNAL_URL.search(val or ""):
                offenders.append(f"{localname(el.tag)}@{localname(key)}={val[:60]}")
    for el in root.iter():
        if el.text and EXTERNAL_URL.search(el.text):
            offenders.append(f"{localname(el.tag)} text content")
    r.check(not offenders, "every reference is internal (default-src 'none')",
            "; ".join(offenders[:3]))

    r.check(not AT_RULES.search(text), "no @font-face / @import (camo sets no font-src)")

    # --- the font-independence guarantee -----------------------------------
    # A badge that renders live text is at the mercy of the reader's installed
    # fonts, and SuperDocs' own typeface ships on no operating system. Outlines
    # are the only way to be both on-brand and identical everywhere; this check
    # is what stops a future edit from quietly reintroducing <text>.
    has_text = bool({"text", "tspan", "textPath"} & tags)
    has_font_attr = "font-family" in text
    r.check(not has_text and not has_font_attr,
            "text is outlined, not live (no <text>, no font-family)",
            f"text elements={has_text} font-family={has_font_attr}")

    # --- accessibility ------------------------------------------------------
    has_title = any(localname(el.tag) == "title" and (el.text or "").strip()
                    for el in root.iter())
    r.check(has_title and bool(root.get("aria-label")),
            "carries <title> and aria-label",
            f"title={has_title} aria-label={root.get('aria-label')!r}")
    r.check(root.get("role") == "img", "role=\"img\"")

    # --- size ---------------------------------------------------------------
    r.check(len(raw) < CAMO_LIMIT, f"under camo's {CAMO_LIMIT:,}-byte ceiling")
    if len(raw) > SANE_BADGE_BYTES:
        r.note(f"{len(raw):,} bytes is large for a badge; outlines should stay under "
               f"{SANE_BADGE_BYTES:,}")

    # --- ids are namespaced so an inlined copy can't collide ----------------
    ids = [el.get("id") for el in root.iter() if el.get("id")]
    generic = [i for i in ids if len(i) < 4]
    r.check(not generic, "element ids are namespaced, not single letters",
            f"generic ids {generic}")

    print()
    if r.failures:
        print(f"FAILED {len(r.failures)} check(s): {', '.join(r.failures)}")
        return 1
    print("All checks passed. Safe to serve through camo — provided the host "
          "returns Content-Type: image/svg+xml (nosniff makes that mandatory).")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1
                  else Path(__file__).parent / "badge.svg")
    sys.exit(verify(target))
