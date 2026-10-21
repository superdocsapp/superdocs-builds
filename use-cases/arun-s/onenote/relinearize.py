"""Re-linearize a OneNote page into reading order.

OneNote's Graph API returns a page as absolutely-positioned blocks: every text
"outline" and image carries an inline `top`/`left` because a page is a freeform
canvas where anyone can drop a box anywhere. So the DOM order the API returns is
NOT the reading order. A naive HTML->doc conversion scrambles the moment two boxes
sit side by side.

This turns the canvas back into a clean top-to-bottom, left-to-right document —
clustering blocks into reading-order rows from their coordinates, then emitting the
inner HTML (headings/paragraphs/images intact) in that order, ready for SuperDocs.

Pure, dependency-free, and fully testable without a Microsoft account.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from html.parser import HTMLParser

VOID = {"img", "br", "hr"}
DEFAULT_H = 24.0  # px height assumed when a block declares none


def _px(style: str, key: str):
    m = re.search(rf"{key}\s*:\s*(-?\d+(?:\.\d+)?)px", style or "", re.I)
    return float(m.group(1)) if m else None


def _abs(style: str) -> bool:
    return "position:absolute" in (style or "").replace(" ", "").lower()


@dataclass
class Block:
    kind: str            # 'text' | 'image'
    top: float
    left: float
    height: float
    html: str = ""       # inner html (for text blocks)
    src: str = ""        # image source (for image blocks)

    @property
    def bottom(self) -> float:
        return self.top + (self.height or DEFAULT_H)


class _Extractor(HTMLParser):
    """Collect top-level absolutely-positioned blocks, keeping each text block's inner
    HTML (minus its own positioning) so headings and paragraphs survive."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._cur: Block | None = None
        self._depth = 0
        self._buf: list[str] = []

    def _img(self, attrs) -> None:
        a = dict(attrs)
        if self._cur is None and _abs(a.get("style", "")):
            self.blocks.append(Block("image", _px(a["style"], "top") or 0.0,
                                     _px(a["style"], "left") or 0.0,
                                     _px(a["style"], "height") or DEFAULT_H, src=a.get("src", "")))
        elif self._cur is not None:
            self._buf.append(f'<img src="{a.get("src", "")}"/>')

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            self._img(attrs)
            return
        if self._cur is None and _abs(a.get("style", "")):     # start a new text block
            self._cur = Block("text", _px(a["style"], "top") or 0.0,
                              _px(a["style"], "left") or 0.0, _px(a["style"], "height") or 0.0)
            self._depth, self._buf = 1, []
            return
        if self._cur is not None and tag not in VOID:          # inner tag of the current block
            self._depth += 1
            self._buf.append(f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        if tag == "img":
            self._img(attrs)

    def handle_endtag(self, tag):
        if self._cur is None or tag in VOID:
            return
        self._depth -= 1
        if self._depth == 0:                                   # the block closed
            self._cur.html = "".join(self._buf).strip()
            self.blocks.append(self._cur)
            self._cur = None
        else:
            self._buf.append(f"</{tag}>")

    def handle_data(self, data):
        if self._cur is not None and data.strip():
            self._buf.append(data)


def parse_blocks(html: str) -> list[Block]:
    e = _Extractor()
    e.feed(html)
    return e.blocks


def rows(blocks: list[Block]) -> list[list[Block]]:
    """Cluster blocks into reading-order rows by vertical overlap; order each row
    left-to-right and the rows top-to-bottom."""
    if not blocks:
        return []
    ordered = sorted(blocks, key=lambda b: (b.top, b.left))
    out: list[list[Block]] = [[ordered[0]]]
    bottom = ordered[0].bottom
    for b in ordered[1:]:
        if b.top < bottom:                 # vertically overlaps the current row
            out[-1].append(b)
            bottom = max(bottom, b.bottom)
        else:                              # clearly below -> a new row
            out.append([b])
            bottom = b.bottom
    for r in out:
        r.sort(key=lambda b: b.left)
    return out


def to_reading_order_html(page_html: str, title: str = "") -> str:
    """The whole job: a OneNote page's raw content HTML -> clean linear HTML."""
    parts = [f"<h1>{title}</h1>"] if title else []
    for row in rows(parse_blocks(page_html)):
        for b in row:
            if b.kind == "image":
                parts.append(f'<p><img src="{b.src}"/></p>')
            elif b.html:
                parts.append(b.html)
    return "\n".join(parts)
