"""
chunking.py -- pure functions for chunk extraction, heading extraction, and
content hashing. Deliberately dependency-free (stdlib only: re, hashlib,
html.parser) and side-effect-free so they can be unit tested without a live
SuperDocs key or a database -- this whole module is what Phase 11's pytest
suite targets.

This is the deterministic core of the "the links stay valid" claim: instead
of asking an LLM whether a procedure's citation still matches its policy
section, we hash the policy chunk's normalized text and compare hashes.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser


class _TopLevelChunkSplitter(HTMLParser):
    """
    Splits a flat sequence of sibling `<TAG data-chunk-id="...">...</TAG>`
    blocks into {chunk_id: inner_html}.

    Originally written assuming the chunk-bearing element was always a
    `<div>` -- true for HTML this project hand-authors itself with baked-in
    ids. Empirically, against a real SuperDocs parse of an uploaded .docx,
    the chunk id lands on whatever element it actually is: `<p
    data-chunk-id="...">` for a paragraph, `<h1>`-`<h6>` for a heading,
    `<table>` for a table (with row/cell elements carrying their OWN nested
    data-chunk-id inside it -- see below). So this now opens a chunk on the
    first element carrying data-chunk-id encountered while no chunk is
    currently open, regardless of tag name, and closes it on the matching
    end tag for THAT SAME tag name (not hardcoded to "div").

    Nested data-chunk-id attributes (e.g. a table's own rows/cells) are
    handled correctly by construction: once a chunk is open, every
    descendant element -- whether it carries its own data-chunk-id or not
    -- is just appended into that chunk's buffered HTML verbatim, never
    treated as the start of a new top-level chunk. Depth-tracking only
    increments for a same-tag re-open (e.g. a table nested inside a table),
    so a table's internal <tr>/<td> chunk ids ride along inside the table's
    chunk content without confusing the table's own open/close bookkeeping.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.chunks: dict[str, str] = {}
        self.chunk_tags: dict[str, str] = {}
        self._current_id: str | None = None
        self._current_tag: str | None = None
        self._depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if self._current_id is None and "data-chunk-id" in attrs_dict:
            self._current_id = attrs_dict["data-chunk-id"]
            self._current_tag = tag
            self._depth = 1
            self._buffer = []
            return
        if self._current_id is not None:
            if tag == self._current_tag:
                self._depth += 1
            self._buffer.append(self._reconstruct_tag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if self._current_id is None and "data-chunk-id" in attrs_dict:
            # A self-closing element (e.g. <hr/>) that is itself the whole
            # chunk -- no separate end tag will ever arrive to close it.
            cid = attrs_dict["data-chunk-id"]
            self.chunks[cid] = self._reconstruct_tag(tag, attrs, self_closing=True)
            self.chunk_tags[cid] = tag
            return
        if self._current_id is not None:
            self._buffer.append(self._reconstruct_tag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag):
        if self._current_id is None:
            return
        if tag == self._current_tag:
            self._depth -= 1
            if self._depth == 0:
                self.chunks[self._current_id] = "".join(self._buffer).strip()
                self.chunk_tags[self._current_id] = self._current_tag
                self._current_id = None
                self._current_tag = None
                self._buffer = []
                return
        self._buffer.append(f"</{tag}>")

    def handle_data(self, data):
        if self._current_id is not None:
            self._buffer.append(data)

    def handle_entityref(self, name):
        if self._current_id is not None:
            self._buffer.append(f"&{name};")

    def handle_charref(self, name):
        if self._current_id is not None:
            self._buffer.append(f"&#{name};")

    @staticmethod
    def _reconstruct_tag(tag: str, attrs: list[tuple[str, str | None]], self_closing: bool = False) -> str:
        parts = [f"<{tag}"]
        for k, v in attrs:
            if v is None:
                parts.append(f" {k}")
            else:
                parts.append(f' {k}="{v}"')
        parts.append(" />" if self_closing else ">")
        return "".join(parts)


def _parse_chunks(document_html: str) -> _TopLevelChunkSplitter:
    parser = _TopLevelChunkSplitter()
    parser.feed(document_html)
    parser.close()
    return parser


def extract_chunks(document_html: str) -> dict[str, str]:
    """
    Parse a SuperDocs document's HTML into {chunk_id: inner_html}.

    >>> extract_chunks('<div data-chunk-id="a"><p>hi</p></div><div data-chunk-id="b"><p>bye</p></div>')
    {'a': '<p>hi</p>', 'b': '<p>bye</p>'}
    """
    return _parse_chunks(document_html).chunks


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_text(html_fragment: str) -> str:
    """
    Strip tags and collapse whitespace, so the hash is stable across
    harmless formatting round-trips (attribute reordering, whitespace
    changes) and only changes when the actual visible text changes.

    >>> normalize_text('<p>  Hello   <b>world</b>. </p>')
    'Hello world .'
    """
    text = _TAG_RE.sub(" ", html_fragment)
    text = text.replace("&mdash;", "—").replace("&ndash;", "–").replace("&amp;", "&")
    text = _WS_RE.sub(" ", text).strip()
    return text


def content_hash(html_fragment: str) -> str:
    """sha256 hex digest of the normalized text of an HTML fragment."""
    normalized = normalize_text(html_fragment)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_HEADING_TAG_RE = re.compile(r"^h[1-6]$", re.IGNORECASE)


def extract_first_heading(html_fragment: str) -> str | None:
    """
    Pull the text of the first h1-h6 in a chunk's HTML, stripped of any
    inner tags. Returns None if the chunk has no heading (e.g. the citation
    chunk, which is a <p>, not a heading).

    Only looks for a heading tag NESTED inside the fragment -- this is the
    convention this project's own hand-authored HTML uses (a <div> chunk
    wrapping a heading plus its following content). It deliberately does
    NOT cover the case where the fragment itself is the inner content of a
    heading element with no wrapper tags left in the string at all -- see
    chunks_with_headings(), which handles that case using the chunk's own
    tag name from the parser instead of a regex search.

    >>> extract_first_heading('<h2>Section 1: Access Control</h2><p>...</p>')
    'Section 1: Access Control'
    """
    match = _HEADING_RE.search(html_fragment)
    if not match:
        return None
    return normalize_text(match.group(1))


_IMPLEMENTS_RE = re.compile(
    r"Implements:\s*Policy\s*§\s*(\d+)\s*[—–-]\s*(.+)", re.IGNORECASE
)


def parse_implements_citation(citation_text: str) -> tuple[int, str] | None:
    """
    Parse the fixed-format citation line "Implements: Policy §N — <heading>"
    into (section_number, heading_text). Returns None if the text doesn't
    match the expected format.

    >>> parse_implements_citation("Implements: Policy §4 — Breach Notification")
    (4, 'Breach Notification')
    """
    normalized = normalize_text(citation_text)
    match = _IMPLEMENTS_RE.search(normalized)
    if not match:
        return None
    section_number = int(match.group(1))
    heading = match.group(2).strip()
    return section_number, heading


def chunks_with_headings(document_html: str) -> list[tuple[str, str | None, str]]:
    """
    Convenience wrapper for the Workspace-schema section-sync logic:
    extract_chunks() + heading detection in one pass, in document order
    (dict insertion order, which matches the HTML's top-level sibling
    order for every document this project produces).

    Heading detection covers both conventions this project has to
    support: (1) a chunk whose own tag IS a heading element -- the real
    shape SuperDocs returns for an uploaded .docx, e.g. `<h2
    data-chunk-id="...">Scope</h2>`, where the h2 wrapper is consumed as
    the chunk boundary itself and never appears "inside" the chunk's
    buffered content, so a plain nested-tag search would always miss it;
    and (2) a heading NESTED inside a non-heading chunk -- the convention
    this project's own hand-authored HTML uses, e.g. `<div
    data-chunk-id="..."><h2>Scope</h2><p>...</p></div>`.

    Returns [(chunk_id, heading_text_or_None, chunk_html), ...].

    >>> chunks_with_headings('<div data-chunk-id="a"><h2>Scope</h2><p>x</p></div>')
    [('a', 'Scope', '<h2>Scope</h2><p>x</p>')]
    >>> chunks_with_headings('<h2 data-chunk-id="b">Scope</h2>')
    [('b', 'Scope', 'Scope')]
    """
    parser = _parse_chunks(document_html)
    result = []
    for cid, html in parser.chunks.items():
        tag = parser.chunk_tags.get(cid, "")
        if _HEADING_TAG_RE.match(tag):
            heading = normalize_text(html) or None
        else:
            heading = extract_first_heading(html)
        result.append((cid, heading, html))
    return result


def group_sections(document_html: str) -> list[dict]:
    """
    Group a document's chunks into logical, addressable sections: every
    heading-bearing chunk starts a new section; every following
    non-heading chunk belongs to that section's body, up to the next
    heading chunk. This is the piece the section-sync logic in main.py
    was missing: a real SuperDocs parse chunks per ELEMENT (one chunk id
    per paragraph, heading, table -- see _TopLevelChunkSplitter), so a
    section's actual content spans MANY chunk ids, not the single chunk
    this project's own hand-authored HTML used to pack a whole section
    into. Without this grouping, every body paragraph between two
    headings was silently discarded (never attached to any Section), and
    a section's stored content was just its bare heading text.

    Content before the first heading has no owning section (same as
    before: unaddressable preamble).

    Each returned dict:
      - heading_chunk_id: chunk id of the heading anchoring this section
      - heading_text: the heading's text
      - member_chunk_ids: [heading_chunk_id, *body_chunk_ids], document order
      - display_html: HTML for rendering the section body WITHOUT
        repeating the heading a second time. Body chunks are individually
        re-wrapped in their own original tag (so consecutive paragraphs
        stay visually separated instead of running together as bare
        text). For the older hand-authored convention -- a heading nested
        INSIDE a wrapping chunk together with its body, e.g. `<div
        data-chunk-id><h2>Scope</h2><p>x</p></div>` -- the heading chunk's
        own html already legitimately contains both and is kept whole,
        unchanged from this project's original single-chunk-per-section
        behavior. Only a chunk whose OWN tag is itself an h1-h6 (the real
        per-element SuperDocs shape, where the heading carries no body in
        the same chunk) is excluded from display_html.
      - full_text: normalized heading + body text, for hashing / LLM
        payloads / the contradiction-detection heuristic -- deliberately
        richer than display_html's heading exclusion, since the heading's
        own wording is real content that should count toward staleness
        and toward what an LLM reads when discovering references.

    >>> [(g["heading_text"], g["display_html"]) for g in
    ...  group_sections('<div data-chunk-id="a"><h2>Scope</h2><p>x</p></div>')]
    [('Scope', '<h2>Scope</h2><p>x</p>')]
    >>> [(g["heading_text"], g["display_html"]) for g in
    ...  group_sections('<h2 data-chunk-id="a">Scope</h2><p data-chunk-id="b">x</p>')]
    [('Scope', '<p>x</p>')]
    """
    parser = _parse_chunks(document_html)
    groups: list[dict] = []
    current: dict | None = None

    for chunk_id, html in parser.chunks.items():
        tag = parser.chunk_tags.get(chunk_id, "")
        is_heading_tag = bool(_HEADING_TAG_RE.match(tag))
        heading_text = normalize_text(html) if is_heading_tag else extract_first_heading(html)

        if heading_text:
            if current is not None:
                groups.append(current)
            current = {
                "heading_chunk_id": chunk_id,
                "heading_text": heading_text,
                "member_chunk_ids": [chunk_id],
                "_display_parts": [] if is_heading_tag else [html],
                "_text_parts": [normalize_text(html)],
            }
        else:
            if current is not None:
                current["member_chunk_ids"].append(chunk_id)
                already_wrapped = tag and html.lstrip().startswith(f"<{tag}")
                wrapped = html if (already_wrapped or not tag) else f"<{tag}>{html}</{tag}>"
                current["_display_parts"].append(wrapped)
                current["_text_parts"].append(normalize_text(html))

    if current is not None:
        groups.append(current)

    return [
        {
            "heading_chunk_id": g["heading_chunk_id"],
            "heading_text": g["heading_text"],
            "member_chunk_ids": g["member_chunk_ids"],
            "display_html": "".join(g["_display_parts"]),
            "full_text": " ".join(t for t in g["_text_parts"] if t),
        }
        for g in groups
    ]


def is_stale(synced_content_hash: str, current_content_hash: str) -> bool:
    """
    The entire dependency model in one function: an edge is stale exactly
    when the hash it was last synced against no longer matches the policy
    section's current hash. Deliberately just an equality check -- no
    prose-diffing, no LLM judgment call, no partial-match fuzziness. This
    is what main.py's change endpoint and validator.py both call (directly
    or by the same comparison) to decide staleness.

    >>> is_stale("abc", "abc")
    False
    >>> is_stale("abc", "def")
    True
    """
    return synced_content_hash != current_content_hash
