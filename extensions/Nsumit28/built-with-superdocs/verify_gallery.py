#!/usr/bin/env python3
"""
Check that the gallery page is genuinely standalone.

"Standalone" is a claim that is easy to make and easy to break — one webfont
import, one CDN script, one hotlinked logo, and the page silently depends on
somebody else's uptime and quietly reports its readers to them. So it is checked
rather than asserted.

The distinction that matters: an <a href> is a link the reader chooses to
follow. An <img src>, <script src>, <link href> or @import is a request the page
makes on the reader's behalf, before they have decided anything. Outbound links
are fine and expected. Subresources are not — there must be zero.

Run:  python3 verify_gallery.py [index.html]
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Attributes that cause the browser to fetch something without being asked.
SUBRESOURCE_ATTRS = {
    "img": ("src", "srcset"),
    "script": ("src",),
    "link": ("href",),
    "iframe": ("src",),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "object": ("data",),
    "embed": ("src",),
    "use": ("href", "xlink:href"),
    "input": ("src",),
    "track": ("src",),
}
REMOTE = re.compile(r"^\s*(?:https?:)?//|^\s*(?:https?):", re.I)
CSS_FETCH = re.compile(r"@import|url\(\s*['\"]?(?!#|data:)", re.I)


class Scanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.subresources: list[str] = []
        self.links: list[str] = []
        self.in_style = False
        self.styles: list[str] = []
        self.has_title = False
        self.has_viewport = False
        self.has_lang = False
        self.imgs_without_alt = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.has_lang = True
        if tag == "title":
            self._in_title = True
        if tag == "meta" and a.get("name") == "viewport":
            self.has_viewport = True
        if tag == "style":
            self.in_style = True
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img" and a.get("alt") is None:
            self.imgs_without_alt += 1
        for attr in SUBRESOURCE_ATTRS.get(tag, ()):
            val = a.get(attr)
            if val and not val.startswith("data:"):
                self.subresources.append(f"<{tag} {attr}={val[:60]}>")
        # inline style="" can fetch too
        if a.get("style") and CSS_FETCH.search(a["style"]):
            self.subresources.append(f"<{tag} style=…url()>")

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)
        if self._in_title and data.strip():
            self.has_title = True


def verify(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    s = Scanner()
    s.feed(text)
    failures = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" +
              ("" if ok or not detail else f" — {detail}"))
        if not ok:
            failures.append(label)

    print(f"\n{path}  ({len(text.encode()):,} bytes)\n")

    check(not s.subresources, "zero subresource requests",
          "; ".join(s.subresources[:3]))

    css = "\n".join(s.styles)
    check(not CSS_FETCH.search(css), "inline CSS fetches nothing (no @import, no url())")

    check("<svg" in text, "badge is inlined as SVG, not linked")

    remote_links = [l for l in s.links if REMOTE.match(l)]
    print(f"  note  {len(s.links)} outbound link(s), {len(remote_links)} off-site — "
          "links are the reader's choice, not the page's request")

    check(s.has_title, "has a <title>")
    check(s.has_lang, "html carries lang")
    check(s.has_viewport, "has a viewport meta (readable on a phone)")
    check(s.imgs_without_alt == 0, "every <img> has alt text",
          f"{s.imgs_without_alt} missing")

    # Round rails that apply to anything published.
    lowered = text.lower()
    check("candidate" in lowered and "superdocsapp" in lowered,
          "discloses candidate affiliation and tags @superdocsapp")

    # Prose only: strip <style>/<script>/<svg> bodies first, or the CSS values and
    # path coordinates drown the signal and the check becomes noise to skip past.
    prose = re.sub(r"<(style|script|svg)\b.*?</\1>", " ", text,
                   flags=re.S | re.I)
    prose = re.sub(r"<[^>]+>", " ", prose)
    prose = re.sub(r"\d{4}-\d{2}-\d{2}", " ", prose)          # dates are not claims
    prose_numbers = re.findall(r"(?<![\w#-])\d[\d,.]*(?![\w%-])", prose)
    print(f"  note  numbers in prose (excluding dates): {prose_numbers or 'none'} — "
          "the round allows at most one, drawn from what SuperDocs publishes")

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("Standalone: the page makes no request on the reader's behalf.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "index.html"
    sys.exit(verify(target))
