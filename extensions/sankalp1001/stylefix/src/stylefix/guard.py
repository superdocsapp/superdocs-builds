"""Deterministic protected-region guard.

The card's bar is that "applied fixes never alter code samples or meaning". That is
not something a model can be asked to promise, so nothing reaches the document until
it has passed this module, which uses no model at all.

Two things were learned by getting them wrong:

1. **A model returns text; a document is markup.** Matching a target against raw HTML
   fails when prose contains `<em>` or `&amp;`, and worse, it matches inside `<script>`
   and inside tag attributes — text no reader sees. So the scanner extracts text nodes
   and records, for every character, its exact offset in the source.

2. **Protection is a property of the document, not of the fragment.** An earlier
   version narrowed the search by re-parsing just one chunk, which silently discarded
   every ancestor — a `<td>` chunk parsed alone looks like ordinary prose, so table
   cells became editable. Protection is now computed once over the whole document as
   element spans, and a scope only *filters* which hits are eligible.

The guard fails closed. A change it cannot place unambiguously is dropped, with the
reason. A missed fix is cosmetic; a wrong edit inside a code sample is the card's
explicit failure condition.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from html.parser import HTMLParser

PROTECTED_TAGS = frozenset({"pre", "code", "table", "kbd", "samp", "tt", "var"})
NON_PROSE_TAGS = frozenset({"script", "style", "template", "noscript"})

# SuperDocs returns out-of-flow document parts as <aside>/<header> elements carrying
# data-part-type, each with its own chunk id (verified against a real upload,
# 2026-08-19). A reviewer's comment is someone else's words — quoted material, which
# the house guide itself says never to touch — so comments are protected. Footnotes
# and headers are the document's own prose and stay fixable.
PROTECTED_PART_TYPES = frozenset({"comment"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input",
     "link", "meta", "param", "source", "track", "wbr"}
)

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Span:
    """A half-open character range [start, end) over the document source."""

    start: int
    end: int
    reason: str

    def intersects(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True)
class Verdict:
    """Why one proposed change was kept or dropped. Always reported, never silent."""

    kept: bool
    reason: str
    span: Span | None = None


def normalize(text: str) -> str:
    """Entities resolved, whitespace collapsed — the text as a reader sees it."""
    return _WHITESPACE.sub(" ", html_module.unescape(text)).strip()


class _Scanner(HTMLParser):
    """Walks the source once, collecting two things: the visible text with an exact
    offset for every character, and the source span of every protected element."""

    def __init__(self, compliant_headings: frozenset[str]) -> None:
        # charrefs are handled explicitly so that one entity maps to one character
        # with its true source width. convert_charrefs=True silently collapses them
        # and every offset after one in the same text node is wrong.
        super().__init__(convert_charrefs=False)
        self._compliant = compliant_headings
        self._open: list[tuple[str, int]] = []
        self._parts: list[tuple[str, int, str]] = []
        self.chars: list[str] = []
        self.offsets: list[int] = []
        self.widths: list[int] = []
        self.protected: list[Span] = []

    def _pos(self) -> int:
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def _add(self, char: str, width: int) -> None:
        self.chars.append(char)
        self.offsets.append(self._pos())
        self.widths.append(width)

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self._open.append((tag, self._pos()))
        part = dict(attrs).get("data-part-type")
        if part in PROTECTED_PART_TYPES:
            self._parts.append((tag, self._pos(), part))

    def handle_endtag(self, tag):
        close = self.rawdata.find(">", self._pos())
        end = (close + 1) if close != -1 else self._pos() + len(tag) + 3
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                start = self._open[i][1]
                del self._open[i:]
                self._close(tag, start, end)
                break

    def _close(self, tag: str, start: int, end: int) -> None:
        for i in range(len(self._parts) - 1, -1, -1):
            if self._parts[i][0] == tag and self._parts[i][1] == start:
                self.protected.append(
                    Span(start, end, f"a {self._parts.pop(i)[2]} is not your prose to edit"))
                return
        if tag in NON_PROSE_TAGS:
            self.protected.append(Span(start, end, f"inside <{tag}>, not document prose"))
        elif tag in PROTECTED_TAGS:
            self.protected.append(Span(start, end, f"inside <{tag}>"))
        elif tag in HEADING_TAGS:
            text = normalize("".join(
                c for c, o in zip(self.chars, self.offsets) if start <= o < end))
            if text in self._compliant:
                self.protected.append(Span(start, end, "heading already compliant"))

    def handle_data(self, data: str) -> None:
        base = self._pos()
        for i, ch in enumerate(data):
            self.chars.append(ch)
            self.offsets.append(base + i)
            self.widths.append(1)

    def handle_entityref(self, name: str) -> None:
        self._add(html_module.unescape(f"&{name};"), len(name) + 2)

    def handle_charref(self, name: str) -> None:
        self._add(html_module.unescape(f"&#{name};"), len(name) + 3)

    def scan(self, source: str) -> "_Scanner":
        starts, pos = [0], 0
        for piece in source.split("\n")[:-1]:
            pos += len(piece) + 1
            starts.append(pos)
        self._starts = starts
        self.feed(source)
        self.close()
        # An unclosed protected tag protects everything from where it opened.
        for tag, start in self._open:
            if tag in PROTECTED_TAGS or tag in NON_PROSE_TAGS:
                self.protected.append(Span(start, len(source), f"unclosed <{tag}>"))
        return self


class Document:
    """Visible text, an exact source span for every character, and the source spans
    of every region the linter must not touch."""

    def __init__(self, source: str, compliant_headings: frozenset[str] = frozenset()):
        scanned = _Scanner(compliant_headings).scan(source)
        self.source = source
        self.protected = scanned.protected
        chars, spans, pending = [], [], None
        for ch, off, width in zip(scanned.chars, scanned.offsets, scanned.widths):
            if ch.isspace():
                if chars:
                    pending = (off, width)
                continue
            if pending is not None:
                chars.append(" ")
                spans.append((pending[0], pending[0] + pending[1]))
                pending = None
            chars.append(ch)
            spans.append((off, off + width))
        self.text = "".join(chars)
        self._spans = spans

    def _span_of(self, start: int, end: int) -> Span:
        return Span(self._spans[start][0], self._spans[end - 1][1], "proposed change")

    def occurrences(self, target: str, within: Span | None = None):
        """Every place `target` appears, with the protected region it touches, if any.

        Overlapping matches count separately: stepping past a match would under-count
        ambiguity, and under-counting errs toward applying, which is the wrong
        direction for a module whose job is to refuse when unsure.
        """
        needle = normalize(target)
        if not needle:
            return []
        found, pos = [], self.text.find(needle)
        while pos != -1:
            span = self._span_of(pos, pos + len(needle))
            if within is None or within.contains(span):
                # A hit is refused if it sits inside a protected element *or* encloses
                # one — the second case catches an empty or whitespace-only <code>,
                # which contributes no characters of its own.
                hit = next((p for p in self.protected if p.intersects(span)), None)
                found.append((span, hit.reason if hit else None))
            pos = self.text.find(needle, pos + 1)
        return found

    def locate_fragment(self, fragment: str) -> Span | None:
        """Where a chunk's HTML sits in this document, if it can be found exactly."""
        at = self.source.find(fragment)
        if at == -1 or self.source.find(fragment, at + 1) != -1:
            return None
        return Span(at, at + len(fragment), "chunk scope")


def protected_regions(source: str, compliant_headings: frozenset[str] = frozenset()):
    """The source spans a fix must not touch. Element spans, tags included."""
    return list(Document(source, compliant_headings).protected)


def screen(source: str, target: str,
           compliant_headings: frozenset[str] = frozenset(),
           scope: str | None = None) -> Verdict:
    """Decide whether one proposed change may be applied.

    `scope` is the HTML of the chunk the change claims. It narrows *which* hits are
    eligible; it never narrows what counts as protected, because a `<td>` read on its
    own looks exactly like ordinary prose.
    """
    doc = Document(source, compliant_headings)
    within = doc.locate_fragment(scope) if scope else None
    if scope and within is None:
        return Verdict(False, "chunk scope not found uniquely in the document")

    hits = doc.occurrences(target, within)
    if not hits:
        return Verdict(False, "target text not found"
                              + (" in this chunk" if within else " in document"))

    clear = [s for s, why in hits if why is None]
    blocked = [(s, why) for s, why in hits if why is not None]

    if not clear:
        return Verdict(False, f"protected: {blocked[0][1]}", blocked[0][0])
    if blocked:
        return Verdict(False,
                       f"ambiguous: {len(hits)} occurrences, {len(blocked)} protected "
                       f"({blocked[0][1]}) — refusing rather than guessing")
    if len(clear) > 1:
        return Verdict(False,
                       f"ambiguous: {len(clear)} identical occurrences and no chunk "
                       f"scope — refusing rather than guessing which")
    return Verdict(True, "clear of every protected region", clear[0])
