"""Parses a text document (markdown/html/txt) into comparable structural units.

Byte-identical comparison of a full document is rarely meaningful for this
app: even an export that changed nothing can differ byte-for-byte from the
original in trailing whitespace, line endings, or (for real DOCX round-trips)
package metadata such as timestamps and revision ids. So every document is
also parsed into a `DocumentModel` — a structural view (sections, paragraphs,
tables, styles, section order) that two documents can be compared on even
when their raw bytes differ.

This app's SuperDocs export path (`export_document`) only ever returns
markdown, html, or txt — never a real DOCX package (see
`src/integrations/superdocs_client.py`). Headers, footers, and footnotes are
DOCX/OOXML package concepts (`word/header1.xml`, `word/footnotes.xml`, ...)
that simply don't exist in those formats. Rather than silently skip them,
`DocumentModel.headers`/`footers`/`footnotes` are always present but marked
`SectionCheck(status="not_applicable", reason=...)` for markdown/html/txt —
so a fidelity report can say "not verified" instead of implying a check that
never ran. A future DOCX-native comparer can populate them for real by
constructing a `DocumentModel` with those fields filled in from
`python-docx` (or equivalent) output; nothing else in this package assumes
the markdown/html parser is the only source of a `DocumentModel`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CheckStatus(str, Enum):
    CHECKED = "checked"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SectionCheck:
    """Whether a structural facet was actually compared, or could not be.

    `NOT_APPLICABLE` must always carry a `reason` — the report layer refuses
    to render it otherwise, since a silent N/A is indistinguishable from a
    forgotten check.
    """

    status: CheckStatus
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status == CheckStatus.NOT_APPLICABLE and not self.reason:
            raise ValueError("a not_applicable SectionCheck must carry a reason")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    index: int  # position among headings, for section-order comparison


@dataclass(frozen=True)
class Paragraph:
    index: int
    text: str
    heading_context: Optional[str]  # nearest preceding heading, or None


@dataclass(frozen=True)
class TableCell:
    row: int
    col: int
    text: str


@dataclass(frozen=True)
class Table:
    index: int
    heading_context: Optional[str]
    header_row: tuple[str, ...]
    cells: tuple[TableCell, ...]

    def cell_map(self) -> dict[tuple[int, int], str]:
        return {(c.row, c.col): c.text for c in self.cells}


@dataclass(frozen=True)
class DocumentModel:
    """Structural view of one document, comparable across an edit."""

    raw_text: str
    sha256: str
    headings: tuple[Heading, ...]
    paragraphs: tuple[Paragraph, ...]
    tables: tuple[Table, ...]
    styles: tuple[str, ...]  # inline style/formatting markers found (html only)
    headers: SectionCheck
    footers: SectionCheck
    footnotes: SectionCheck

    def section_order(self) -> tuple[str, ...]:
        return tuple(h.text for h in self.headings)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_STYLE_RE = re.compile(r'style="([^"]*)"')
_HTML_HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_MD_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_MD_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _detect_format(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("<") and ("<html" in stripped.lower() or "<table" in stripped.lower() or "<h1" in stripped.lower() or "<p" in stripped.lower()):
        return "html"
    if "|" in text and _MD_TABLE_SEP_RE_ANY(text):
        return "markdown"
    if _HEADING_RE_ANY(text):
        return "markdown"
    return "text"


def _MD_TABLE_SEP_RE_ANY(text: str) -> bool:
    return any(_MD_TABLE_SEP_RE.match(line.strip()) for line in text.splitlines())


def _HEADING_RE_ANY(text: str) -> bool:
    return any(_HEADING_RE.match(line) for line in text.splitlines())


def _parse_markdown_tables(lines: list[str], heading_for_line: list[Optional[str]]) -> tuple[list[Table], set[int]]:
    tables: list[Table] = []
    consumed: set[int] = set()
    i = 0
    table_index = 0
    while i < len(lines):
        row_match = _MD_TABLE_ROW_RE.match(lines[i].strip())
        if row_match and i + 1 < len(lines) and _MD_TABLE_SEP_RE.match(lines[i + 1].strip()):
            header_cells = tuple(c.strip() for c in row_match.group(1).split("|"))
            consumed.add(i)
            consumed.add(i + 1)
            row_idx = 0
            cells: list[TableCell] = []
            j = i + 2
            while j < len(lines):
                data_match = _MD_TABLE_ROW_RE.match(lines[j].strip())
                if not data_match:
                    break
                row_cells = [c.strip() for c in data_match.group(1).split("|")]
                for col_idx, val in enumerate(row_cells):
                    cells.append(TableCell(row=row_idx, col=col_idx, text=val))
                consumed.add(j)
                row_idx += 1
                j += 1
            tables.append(
                Table(
                    index=table_index,
                    heading_context=heading_for_line[i] if i < len(heading_for_line) else None,
                    header_row=header_cells,
                    cells=tuple(cells),
                )
            )
            table_index += 1
            i = j
            continue
        i += 1
    return tables, consumed


def _parse_markdown(text: str) -> DocumentModel:
    lines = text.splitlines()
    headings: list[Heading] = []
    heading_for_line: list[Optional[str]] = [None] * len(lines)
    current_heading: Optional[str] = None
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            current_heading = m.group(2).strip()
            headings.append(Heading(level=len(m.group(1)), text=current_heading, index=len(headings)))
        heading_for_line[idx] = current_heading

    tables, consumed_table_lines = _parse_markdown_tables(lines, heading_for_line)

    paragraphs: list[Paragraph] = []
    buffer: list[str] = []
    buffer_heading: Optional[str] = None
    para_index = 0

    def flush() -> None:
        nonlocal para_index, buffer, buffer_heading
        joined = " ".join(s.strip() for s in buffer if s.strip())
        if joined:
            paragraphs.append(Paragraph(index=para_index, text=joined, heading_context=buffer_heading))
            para_index += 1
        buffer = []

    for idx, line in enumerate(lines):
        if idx in consumed_table_lines:
            flush()
            continue
        if _HEADING_RE.match(line):
            flush()
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if not buffer:
            buffer_heading = heading_for_line[idx]
        buffer.append(stripped)
    flush()

    return DocumentModel(
        raw_text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        headings=tuple(headings),
        paragraphs=tuple(paragraphs),
        tables=tuple(tables),
        styles=tuple(),
        headers=SectionCheck(CheckStatus.NOT_APPLICABLE, "markdown export has no page-header package part"),
        footers=SectionCheck(CheckStatus.NOT_APPLICABLE, "markdown export has no page-footer package part"),
        footnotes=SectionCheck(CheckStatus.NOT_APPLICABLE, "markdown export has no footnote package part"),
    )


def _parse_html(text: str) -> DocumentModel:
    headings: list[Heading] = []
    for m in _HTML_HEADING_RE.finditer(text):
        level = int(m.group(1))
        heading_text = _strip_html(m.group(2))
        if heading_text:
            headings.append(Heading(level=level, text=heading_text, index=len(headings)))

    styles = tuple(sorted(set(_HTML_STYLE_RE.findall(text))))

    tables: list[Table] = []
    table_index = 0
    for table_match in re.finditer(r"<table[^>]*>(.*?)</table>", text, re.IGNORECASE | re.DOTALL):
        table_html = table_match.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.IGNORECASE | re.DOTALL)
        header_row: tuple[str, ...] = tuple()
        cells: list[TableCell] = []
        data_row_idx = 0
        for row_idx, row_html in enumerate(rows):
            th_cells = re.findall(r"<th[^>]*>(.*?)</th>", row_html, re.IGNORECASE | re.DOTALL)
            if th_cells and row_idx == 0:
                header_row = tuple(_strip_html(c) for c in th_cells)
                continue
            td_cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
            for col_idx, val in enumerate(td_cells):
                cells.append(TableCell(row=data_row_idx, col=col_idx, text=_strip_html(val)))
            if td_cells:
                data_row_idx += 1
        tables.append(Table(index=table_index, heading_context=None, header_row=header_row, cells=tuple(cells)))
        table_index += 1

    without_tables = re.sub(r"<table[^>]*>.*?</table>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    without_headings = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", " ", without_tables, flags=re.IGNORECASE | re.DOTALL)
    raw_paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", without_headings, re.IGNORECASE | re.DOTALL)
    paragraphs = tuple(
        Paragraph(index=i, text=_strip_html(p), heading_context=None)
        for i, p in enumerate(raw_paragraphs)
        if _strip_html(p)
    )

    return DocumentModel(
        raw_text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        headings=tuple(headings),
        paragraphs=paragraphs,
        tables=tuple(tables),
        styles=styles,
        headers=SectionCheck(CheckStatus.NOT_APPLICABLE, "html export has no page-header package part"),
        footers=SectionCheck(CheckStatus.NOT_APPLICABLE, "html export has no page-footer package part"),
        footnotes=SectionCheck(CheckStatus.NOT_APPLICABLE, "html export has no footnote package part"),
    )


def _parse_plain_text(text: str) -> DocumentModel:
    paragraphs = tuple(
        Paragraph(index=i, text=block.strip(), heading_context=None)
        for i, block in enumerate(re.split(r"\n\s*\n", text))
        if block.strip()
    )
    return DocumentModel(
        raw_text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        headings=tuple(),
        paragraphs=paragraphs,
        tables=tuple(),
        styles=tuple(),
        headers=SectionCheck(CheckStatus.NOT_APPLICABLE, "plain-text export has no page-header package part"),
        footers=SectionCheck(CheckStatus.NOT_APPLICABLE, "plain-text export has no page-footer package part"),
        footnotes=SectionCheck(CheckStatus.NOT_APPLICABLE, "plain-text export has no footnote package part"),
    )


def parse_document(text: str, format_hint: Optional[str] = None) -> DocumentModel:
    """Parse markdown, html, or plain text into a `DocumentModel`.

    `format_hint` should be one of {"markdown", "html", "txt"} — the same
    values `export_document`'s `export_format` accepts — to avoid guessing.
    Falls back to sniffing when omitted (e.g. when comparing an original
    on-disk fixture, which has no associated export format).
    """

    fmt = format_hint or _detect_format(text)
    if fmt == "html":
        return _parse_html(text)
    if fmt in ("markdown", "md"):
        return _parse_markdown(text)
    return _parse_plain_text(text)
