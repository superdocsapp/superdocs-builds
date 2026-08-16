"""
Splits a SuperDocs document's HTML into its top-level chunks (each carrying
a `data-chunk-id` attribute), so the agent can hash every chunk EXCEPT the
one it owns and prove, byte-for-byte, that nothing else changed after an
edit -- not assert it, check it.

Uses the standard-library html.parser rather than a regex, because the
boundary check is the one thing in this build that has to be actually
correct, not approximately correct. Handles nested elements properly via a
depth counter: only elements at depth 0 (not nested inside another chunk)
are treated as top-level chunks, since that's what SuperDocs' own documents
consistently produced in every real document this build created (see
README.md's "Known limitations" section for the one case this doesn't
cover, and why it doesn't matter for the boundary guarantee).
"""

from dataclasses import dataclass
from html.parser import HTMLParser

_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "col", "area", "base", "embed", "source", "track", "wbr"}


@dataclass
class Chunk:
    chunk_id: str | None
    tag: str
    html: str
    start: int
    end: int


class _TopLevelChunkParser(HTMLParser):
    def __init__(self, raw_html: str):
        super().__init__(convert_charrefs=False)
        self.raw_html = raw_html
        self._line_starts = self._compute_line_starts(raw_html)
        self.depth = 0
        self.chunks: list[Chunk] = []
        self._stack: list[tuple[str, int, str | None]] = []  # (tag, start_offset, chunk_id)

    @staticmethod
    def _compute_line_starts(text: str) -> list[int]:
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        return starts

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self._offset()
        if tag in _VOID_TAGS:
            if self.depth == 0:
                chunk_id = dict(attrs).get("data-chunk-id")
                end = start + len(self.get_starttag_text())
                self.chunks.append(Chunk(chunk_id, tag, self.raw_html[start:end], start, end))
            return
        if self.depth == 0:
            chunk_id = dict(attrs).get("data-chunk-id")
            self._stack.append((tag, start, chunk_id))
        else:
            self._stack.append((tag, start, None))
        self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.depth == 0:
            start = self._offset()
            end = start + len(self.get_starttag_text())
            chunk_id = dict(attrs).get("data-chunk-id")
            self.chunks.append(Chunk(chunk_id, tag, self.raw_html[start:end], start, end))

    def handle_endtag(self, tag):
        if not self._stack:
            return
        self.depth -= 1
        opened_tag, start, chunk_id = self._stack.pop()
        if self.depth == 0:
            end = self._offset() + len(f"</{tag}>")
            self.chunks.append(Chunk(chunk_id, opened_tag, self.raw_html[start:end], start, end))


def split_into_chunks(html: str) -> list[Chunk]:
    parser = _TopLevelChunkParser(html)
    parser.feed(html)
    return sorted(parser.chunks, key=lambda c: c.start)


def chunk_map_excluding(html: str, exclude_chunk_ids) -> dict[str, str]:
    """chunk_id -> raw html, for every top-level chunk except the given
    ones. `exclude_chunk_ids` may be a single id or a collection -- the
    owned SECTION is a heading plus every chunk under it, not one chunk
    (see find_section_chunk_ids), so this always needs to exclude a set,
    not a single id. Chunks with no chunk_id (rare) are keyed by their
    start offset instead, so they still participate in the comparison."""
    if isinstance(exclude_chunk_ids, str):
        exclude_chunk_ids = {exclude_chunk_ids}
    else:
        exclude_chunk_ids = set(exclude_chunk_ids)
    result: dict[str, str] = {}
    for c in split_into_chunks(html):
        if c.chunk_id in exclude_chunk_ids:
            continue
        key = c.chunk_id or f"__unkeyed_offset_{c.start}"
        result[key] = c.html
    return result


_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def find_section_chunk_ids(html: str, heading_text: str) -> list[str] | None:
    """A 'section' is the heading chunk whose text contains `heading_text`,
    plus every following top-level chunk up to (not including) the next
    heading. Returns None if no matching heading is found."""
    chunks = split_into_chunks(html)
    ids: list[str] = []
    in_section = False
    for c in chunks:
        if not in_section:
            if c.tag in _HEADING_TAGS and heading_text in c.html:
                in_section = True
                ids.append(c.chunk_id)
            continue
        if c.tag in _HEADING_TAGS:
            break
        ids.append(c.chunk_id)
    return ids or None
