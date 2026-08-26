"""Parse SuperDocs chunked HTML into an ordered list of top-level blocks.

SuperDocs returns flat HTML where every top-level block (p, h1..h6, table,
ul, ...) carries a data-chunk-id. Chunk ids are the stable handles the whole
pipeline keys on: matching, edits, byte-identity verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

VOID_TAGS = {"br", "hr", "img", "col", "input", "meta", "link"}


@dataclass
class Chunk:
    chunk_id: str
    tag: str
    outer_html: str

    @property
    def text(self) -> str:
        return unescape(re.sub(r"<[^>]+>", " ", self.outer_html)).strip()

    @property
    def norm_text(self) -> str:
        return " ".join(self.text.lower().split())


class _BlockSplitter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[Chunk] = []
        self._depth = 0
        self._buf: list[str] = []
        self._tag = ""
        self._chunk_id = ""

    def _attrs_str(self, attrs) -> str:
        return "".join(f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs)

    def handle_starttag(self, tag, attrs):
        if self._depth == 0:
            self._tag = tag
            self._chunk_id = dict(attrs).get("data-chunk-id", "")
            self._buf = []
        self._buf.append(f"<{tag}{self._attrs_str(attrs)}>")
        if tag not in VOID_TAGS:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self._depth == 0:
            self.blocks.append(Chunk(dict(attrs).get("data-chunk-id", ""), tag, f"<{tag}{self._attrs_str(attrs)}/>"))
        else:
            self._buf.append(f"<{tag}{self._attrs_str(attrs)}/>")

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        self._buf.append(f"</{tag}>")
        self._depth -= 1
        if self._depth == 0:
            self.blocks.append(Chunk(self._chunk_id, self._tag, "".join(self._buf)))
            self._buf = []

    def handle_data(self, data):
        if self._depth > 0:
            self._buf.append(data)

    def handle_entityref(self, name):
        if self._depth > 0:
            self._buf.append(f"&{name};")

    def handle_charref(self, name):
        if self._depth > 0:
            self._buf.append(f"&#{name};")


def parse_chunks(html: str) -> list[Chunk]:
    splitter = _BlockSplitter()
    splitter.feed(html)
    splitter.close()
    return [b for b in splitter.blocks if b.chunk_id or b.text]


def chunks_to_html(chunks: list[Chunk]) -> str:
    return "\n".join(c.outer_html for c in chunks)
