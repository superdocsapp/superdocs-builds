"""Chunks: the unit SuperDocs actually addresses, and the unit we verify.

Measured rather than assumed (PROGRESS.md 2026-08-09): an HTML upload chunks at
the top-level element - every paragraph, every heading, and **the entire table as
one chunk**. Rows and cells carry no id. So the blank form is built to match that
granularity: whatever we intend to replace later is its own top-level element,
so a list of granted powers is one `<ul>` and therefore one chunk, and the
signature block is one table and therefore one chunk (Decision 37).

Copied as an idea from `builds/statutory-statements/` and rebuilt here rather
than imported (Decision 31, and hard rule: a shared idea gets copied). The
divergence is real: this package reads clause headings, not note headings, and
it carries `strip_markup`, which the notice gate needs and the statutory build
has no use for.

`canonical()` is what "the expected bytes" means in practice. A document editor
is entitled to re-serialise whitespace, attribute order and character entities,
and treating that as a failure would make the verifier cry wolf on every step.
Everything that carries meaning - the tag sequence, every attribute value, and
every character of text including every digit - is compared exactly. The chunk
id is dropped because it is the address, not the content.

The entity and void-element rules were measured, not assumed: we uploaded
`&middot;` and got back the character it stands for, and we uploaded `<br>` and
got back `<br/>`. The first live run
stopped on it, which is the verbatim check doing exactly its job; the honest
resolution is to define "verbatim" at the level of content rather than of bytes,
and to say so here.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

CHUNK_ID = re.compile(r'\sdata-chunk-id="[^"]*"')
CLAUSE_HEADING = re.compile(r"^(?P<number>\d+)\.\s+(?P<title>.+)$")
MARKUP = re.compile(r"<[^>]+>")
TAG = re.compile(r"<(/?)([a-zA-Z0-9]+)((?:\s+[a-zA-Z0-9:-]+\s*=\s*\"[^\"]*\")*)\s*(/?)>")
ATTR = re.compile(r"([a-zA-Z0-9:-]+)\s*=\s*\"([^\"]*)\"")
WS = re.compile(r"\s+")
TOP_LEVEL = ("h1", "h2", "h3", "h4", "p", "table", "ul", "ol", "div", "section", "blockquote")
VOID = {"br", "meta", "hr", "img", "link", "input", "col"}
# HTML parsers insert these whether or not the source had them. Measured: we
# uploaded a table with no <tbody> and it came back wrapped in one.
IMPLICIT = {"tbody", "thead", "tfoot"}


def canonical(fragment: str) -> str:
    """Whitespace-collapsed, attribute-sorted, chunk-id-free form of an HTML fragment."""
    out: list[str] = []
    cursor = 0
    for match in TAG.finditer(fragment):
        text = fragment[cursor : match.start()]
        if text:
            out.append(WS.sub(" ", _html.unescape(text)))
        closing, tag, attrs, selfclose = match.groups()
        pairs = sorted(
            (k.lower(), WS.sub(" ", v).strip())
            for k, v in ATTR.findall(attrs)
            if k.lower() != "data-chunk-id"
        )
        if tag.lower() in IMPLICIT:
            cursor = match.end()
            continue
        rendered = "".join(f' {k}="{v}"' for k, v in pairs)
        # `<br>` and `<br/>` are the same element; the product re-serialises the
        # one we send as the other, and that is punctuation, not content.
        marker = "/" if selfclose and tag.lower() not in VOID else ""
        out.append(f"<{closing}{tag.lower()}{rendered}{marker}>")
        cursor = match.end()
    tail = fragment[cursor:]
    if tail:
        out.append(WS.sub(" ", _html.unescape(tail)))
    return WS.sub(" ", "".join(out)).replace("> <", "><").strip()


def strip_markup(fragment: str) -> str:
    """The text a reader sees: tags removed, entities resolved, spaces collapsed.

    The notice check compares against this rather than against raw HTML, because
    a document editor is entitled to re-serialise an entity and that is
    punctuation, not content - the same argument `canonical()` makes one level
    up. What it may not do is change a word, and that is what this preserves.
    """
    return WS.sub(" ", _html.unescape(MARKUP.sub(" ", fragment))).strip()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    tag: str
    html: str

    @property
    def canonical(self) -> str:
        return canonical(self.html)


class _Scanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.spans: list[tuple[str, str, int, int]] = []
        self._depth = 0
        self._tag: str | None = None
        self._start = 0
        self._chunk_id = ""
        self._text = ""

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_start[line - 1] + col

    def feed_text(self, text: str) -> None:
        self._text = text
        self._line_start = [0]
        offset = 0
        for line in text.splitlines(keepends=True):
            offset += len(line)
            self._line_start.append(offset)
        self.feed(text)
        self.close()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in VOID:
            return
        if self._tag is None:
            if tag in TOP_LEVEL:
                self._tag = tag
                self._depth = 1
                self._start = self._offset()
                self._chunk_id = dict(attrs).get("data-chunk-id") or ""
            return
        if tag == self._tag:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._tag is None or tag != self._tag:
            return
        self._depth -= 1
        if self._depth == 0:
            end = self._offset() + len(f"</{tag}>")
            self.spans.append((self._chunk_id, self._tag, self._start, end))
            self._tag = None


class ChunkMap:
    """An ordered map of chunk id -> chunk, as the document currently stands."""

    def __init__(self, html: str) -> None:
        scanner = _Scanner()
        scanner.feed_text(html)
        self.chunks: list[Chunk] = [
            Chunk(chunk_id, tag, html[start:end]) for chunk_id, tag, start, end in scanner.spans
        ]
        self.by_id = {c.chunk_id: c for c in self.chunks if c.chunk_id}

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def ids(self) -> list[str]:
        return [c.chunk_id for c in self.chunks]

    def headings(self) -> dict[int, str]:
        """Clause number -> heading text, read back from the document itself.

        Read from the live document rather than from our own tree, because the
        point of reading it back is to find out whether the numbering we
        computed is the numbering the document actually carries.
        """
        found: dict[int, str] = {}
        for chunk in self.chunks:
            if chunk.tag != "h2":
                continue
            text = strip_markup(chunk.html).strip()
            match = CLAUSE_HEADING.match(text)
            if match:
                found[int(match.group("number"))] = text
        return found

    def text_of(self, chunk_id: str) -> str:
        return strip_markup(self.by_id[chunk_id].html).strip()

    def text(self) -> str:
        """The whole document as text, whitespace collapsed. What a reader reads."""
        return strip_markup(" ".join(c.html for c in self.chunks))


def strip_chunk_ids(html: str) -> str:
    return CHUNK_ID.sub("", html)


def tidy(fragment: str) -> str:
    """Drop the whitespace an HTML serialiser drops, before we ever send it.

    Measured: we sent `<br>\nPrepared in accordance...` and the edited chunk came
    back as `<br>Prepared in accordance...`. Rather than keep widening
    `canonical()` until it forgives everything, the document we compute is
    written the way a serialiser would write it, so there is less for the
    comparison to forgive. Whitespace *inside* a line is left alone - that is
    where the meaningful spaces between words are.
    """
    fragment = re.sub(r">[ \t]*\n[ \t]*", ">", fragment)
    return re.sub(r"[ \t]*\n[ \t]*<", "<", fragment)
