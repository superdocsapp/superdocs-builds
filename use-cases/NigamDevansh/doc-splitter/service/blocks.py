"""The master document as an addressable sequence of blocks.

SuperDocs' upload returns parsed HTML with a `data-chunk-id` on every top-level
block (and `data-part-type` on out-of-flow ones). Splitting is slicing this
list, and every claim — nothing dropped, nothing duplicated — is about it.

Top-level only: a `<header>` wrapping a `<p>` is one block, not two. Descending
would count the same text twice and void the coverage proof.

See use-cases/doc-splitter/README.md § "How it splits".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "col", "source", "wbr"})
"""Elements with no closing tag. Counting a `<br/>` as open would nest every
following block into one."""

HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


@dataclass(frozen=True, slots=True)
class Block:
    index: int
    chunk_id: str
    tag: str
    html: str
    """The block's markup, verbatim — slicing reassembles these, so anything lost
    here is lost from the part."""
    part_type: str
    """`body`, or `header`/`footer` for page furniture — see `is_flow`."""

    @property
    def text(self) -> str:
        return _WS.sub(" ", unescape(_TAG.sub("", self.html))).strip()

    @property
    def heading_level(self) -> int:
        """0 when not a heading. `structure.headings[]` is populated only for
        real Word heading styles — a .pdf/.md master yields none (a stated
        limit)."""
        return int(self.tag[1]) if self.tag in HEADINGS else 0

    @property
    def is_flow(self) -> bool:
        """True for content, false for page furniture — the distinction the
        completeness claim depends on. A header repeats on every page, so it is
        copied into every part; flow blocks are partitioned. Coverage counts them
        separately so "nothing duplicated" stays true of the content."""
        return self.part_type == "body"


class _Blocks(HTMLParser):
    """Depth-aware: a new block starts only at depth zero."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[Block] = []
        self._depth = 0
        self._open: list[str] = []
        self._buffer: list[str] = []
        self._tag = ""
        self._chunk = ""
        self._part = "body"

    # ── collecting ───────────────────────────────────────────────────────
    def _emit(self, text: str) -> None:
        if self._depth:
            self._buffer.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        if self._depth == 0:
            if "data-chunk-id" not in values:
                # Markup between blocks (a stray SuperDocs wrapper). Ignored: a
                # block with no id can't be addressed or split at.
                return
            self._tag = tag
            self._chunk = values["data-chunk-id"]
            self._part = values.get("data-part-type", "body") or "body"
            self._buffer = []
        self._buffer.append(self.get_starttag_text() or "")
        if tag not in VOID:
            self._depth += 1
            self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._emit(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if not self._depth or tag not in self._open:
            return
        self._buffer.append(f"</{tag}>")
        self._open.pop()
        self._depth -= 1
        if self._depth == 0:
            self.blocks.append(
                Block(
                    index=len(self.blocks),
                    chunk_id=self._chunk,
                    tag=self._tag,
                    html="".join(self._buffer),
                    part_type=self._part,
                )
            )
            self._buffer = []

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def handle_entityref(self, name: str) -> None:
        self._emit(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._emit(f"&#{name};")


def parse(html: str) -> list[Block]:
    """SuperDocs' parsed HTML → the blocks a split is made of."""
    parser = _Blocks()
    parser.feed(html)
    parser.close()
    return parser.blocks


def flow(blocks: list[Block]) -> list[Block]:
    return [block for block in blocks if block.is_flow]


def furniture(blocks: list[Block]) -> list[Block]:
    return [block for block in blocks if not block.is_flow]
