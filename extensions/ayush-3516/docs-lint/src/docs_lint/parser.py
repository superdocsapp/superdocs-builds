"""Parsing Markdown into addressable segments.

The card asks that findings map to precise locations. That means a finding has to know four things
about where it lives: which heading section, which lines, which characters, and later which
SuperDocs chunk. This module produces the first three.

Segments are produced from the CommonMark token stream rather than by scanning lines, so a `#`
inside a fenced code block is code and not a heading, and prose rules never fire on examples. That
distinction is the whole reason not to do this with regular expressions over raw text.
"""

from __future__ import annotations

import bisect
from enum import StrEnum

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict

from .model import Anchor


class SegmentKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE = "code"
    HTML = "html"
    TABLE_ROW = "table_row"

    @property
    def is_prose(self) -> bool:
        """Whether prose rules should look at this segment.

        Code is excluded deliberately: a style guide that bans "utilise" is talking about the
        documentation's voice, not about a variable named `utilise_this`. Rewriting an identifier
        inside an example because it matched a prose rule would break the example.
        """
        return self in {SegmentKind.HEADING, SegmentKind.PARAGRAPH, SegmentKind.TABLE_ROW}


class Segment(BaseModel):
    """One addressable block of a document."""

    model_config = ConfigDict(frozen=True)

    kind: SegmentKind
    #: The exact source slice, byte-for-byte as it appears in the file.
    raw: str
    #: Inline content with block markers removed - the heading text without its `#`, for instance.
    content: str
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    heading_path: tuple[str, ...] = ()
    #: Fence language for code segments, heading level for headings.
    info: str = ""
    level: int = 0

    @property
    def content_offset(self) -> int:
        """Offset of `content` within `raw`, so a match in content maps back to the file.

        For a heading, this steps over the `## ` marker. Falls back to zero when the content has
        been transformed enough that it cannot be located, which keeps the anchor at the block
        start rather than pointing somewhere wrong.
        """
        found = self.raw.find(self.content)
        return found if found >= 0 else 0


class Document(BaseModel):
    """A parsed Markdown file, plus the machinery to turn an offset into an `Anchor`."""

    model_config = ConfigDict(frozen=True)

    path: str
    text: str
    segments: tuple[Segment, ...] = ()
    line_starts: tuple[int, ...] = ()

    def line_of(self, offset: int) -> int:
        """1-based line number containing `offset`."""
        return bisect.bisect_right(self.line_starts, offset)

    def anchor(
        self, segment: Segment, *, start: int | None = None, end: int | None = None
    ) -> Anchor:
        """An anchor for a span given as absolute character offsets into the document.

        With no span, anchors the whole segment.
        """
        start_offset = segment.start_offset if start is None else start
        end_offset = segment.end_offset if end is None else end
        return Anchor(
            path=self.path,
            start_line=self.line_of(start_offset),
            end_line=self.line_of(max(start_offset, end_offset - 1)),
            start_char=start_offset,
            end_char=end_offset,
            heading_path=segment.heading_path,
        )

    def slice(self, anchor: Anchor) -> str:
        return self.text[anchor.start_char : anchor.end_char]

    @property
    def prose_segments(self) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.kind.is_prose)


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    return tuple(starts)


def _markdown_parser() -> MarkdownIt:
    # CommonMark plus tables, which is what documentation actually uses. Nothing else is enabled:
    # unknown syntax degrades to paragraphs and HTML blocks, which is a safe way to be wrong.
    return MarkdownIt("commonmark").enable("table")


def parse_document(path: str, text: str) -> Document:
    """Parse Markdown (or MDX, best-effort) into addressable segments."""
    md = _markdown_parser()
    tokens = md.parse(text)
    starts = _line_starts(text)

    def offsets(token) -> tuple[int, int]:
        """Absolute character span of a block token, from its line map."""
        start_line, end_line = token.map
        start = starts[start_line]
        end = starts[end_line] if end_line < len(starts) else len(text)
        return start, end

    segments: list[Segment] = []
    heading_stack: list[tuple[int, str]] = []
    pending_kind: SegmentKind | None = None
    pending_token = None
    heading_level = 0

    def current_path() -> tuple[str, ...]:
        return tuple(title for _, title in heading_stack)

    for token in tokens:
        if token.type == "heading_open":
            pending_kind = SegmentKind.HEADING
            pending_token = token
            heading_level = int(token.tag[1:]) if token.tag[1:].isdigit() else 1

        elif token.type == "paragraph_open":
            pending_kind = SegmentKind.PARAGRAPH
            pending_token = token

        elif token.type == "tr_open":
            pending_kind = SegmentKind.TABLE_ROW
            pending_token = token

        elif token.type == "inline" and pending_kind is not None and pending_token is not None:
            start, end = offsets(pending_token)
            raw = text[start:end]
            segment = Segment(
                kind=pending_kind,
                raw=raw,
                content=token.content,
                start_line=pending_token.map[0] + 1,
                end_line=pending_token.map[1],
                start_offset=start,
                end_offset=end,
                heading_path=current_path(),
                level=heading_level if pending_kind is SegmentKind.HEADING else 0,
            )
            segments.append(segment)

            if pending_kind is SegmentKind.HEADING:
                # A heading closes every section at or below its level, then opens its own. This
                # is what keeps `heading_path` correct when a document goes h1, h2, h3, h2.
                while heading_stack and heading_stack[-1][0] >= heading_level:
                    heading_stack.pop()
                heading_stack.append((heading_level, token.content.strip()))

            pending_kind = None
            pending_token = None

        elif token.type in {"fence", "code_block"}:
            start, end = offsets(token)
            segments.append(
                Segment(
                    kind=SegmentKind.CODE,
                    raw=text[start:end],
                    content=token.content,
                    start_line=token.map[0] + 1,
                    end_line=token.map[1],
                    start_offset=start,
                    end_offset=end,
                    heading_path=current_path(),
                    info=(token.info or "").strip(),
                )
            )

        elif token.type == "html_block":
            start, end = offsets(token)
            segments.append(
                Segment(
                    kind=SegmentKind.HTML,
                    raw=text[start:end],
                    content=token.content,
                    start_line=token.map[0] + 1,
                    end_line=token.map[1],
                    start_offset=start,
                    end_offset=end,
                    heading_path=current_path(),
                )
            )

    return Document(path=path, text=text, segments=tuple(segments), line_starts=starts)
