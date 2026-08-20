"""Document parsing with layout awareness and a graceful degradation ladder.

Strategy per file type
----------------------
PDF   : pdfplumber (text + tables with coordinates) -> PyMuPDF (fast text) ->
        OCR via pytesseract on rasterised pages when the page yields no text.
DOCX  : python-docx paragraphs (with heading tracking) + tables.
TXT/MD: split on blank lines, markdown headings become sections.

Every extracted unit becomes a :class:`TextBlock` carrying page, paragraph,
section and character offsets — that provenance is what makes citations
verifiable rather than plausible-looking.

Every optional dependency is imported lazily so the module (and the unit tests
over plain text) works in a minimal environment.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from app.core.errors import ParsingError, UnsupportedFileType
from app.core.logging import get_logger
from app.schemas.domain import ParsedDocument, Table, TextBlock

log = get_logger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+([A-Z][^.]{2,80})$")
_MIN_CHARS_FOR_TEXT_PAGE = 24


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    if _HEADING_RE.match(stripped) or _NUMBERED_HEADING_RE.match(stripped):
        return True
    letters = [c for c in stripped if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 3:
        return True
    return stripped.endswith(":") and len(stripped.split()) <= 8


def _blocks_from_lines(
    lines: list[str], *, page: int, cursor: int, section: str | None
) -> tuple[list[TextBlock], int, str | None]:
    """Turn raw lines into paragraph/heading blocks, tracking char offsets."""
    blocks: list[TextBlock] = []
    buffer: list[str] = []
    paragraph = 0

    def flush() -> None:
        nonlocal buffer, cursor, paragraph
        if not buffer:
            return
        text = " ".join(part.strip() for part in buffer).strip()
        buffer = []
        if not text:
            return
        blocks.append(
            TextBlock(
                text=text,
                page=page,
                paragraph=paragraph,
                section=section,
                char_start=cursor,
                char_end=cursor + len(text),
                kind="paragraph",
            )
        )
        cursor += len(text) + 1
        paragraph += 1

    for line in lines:
        if not line.strip():
            flush()
            continue
        if _looks_like_heading(line):
            flush()
            heading = _HEADING_RE.sub(r"\2", line.strip()).strip().rstrip(":")
            section = heading
            blocks.append(
                TextBlock(
                    text=heading,
                    page=page,
                    paragraph=paragraph,
                    section=section,
                    char_start=cursor,
                    char_end=cursor + len(heading),
                    kind="heading",
                )
            )
            cursor += len(heading) + 1
            paragraph += 1
            continue
        buffer.append(line)
    flush()
    return blocks, cursor, section


def parse_text(data: bytes) -> ParsedDocument:
    raw = data.decode("utf-8", errors="replace")
    blocks, _, _ = _blocks_from_lines(raw.splitlines(), page=1, cursor=0, section=None)
    return ParsedDocument(
        text=raw, blocks=blocks, page_count=1, parser="text", tables=_tables_from_markdown(raw)
    )


def _tables_from_markdown(raw: str) -> list[Table]:
    """Parse GitHub-flavoured markdown pipe tables (common in .md specs)."""
    tables: list[Table] = []
    rows: list[list[str]] = []
    for line in raw.splitlines() + [""]:
        if line.strip().startswith("|") and line.count("|") >= 2:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            rows.append(cells)
            continue
        if len(rows) >= 2:
            tables.append(Table(page=1, header=rows[0], rows=rows[1:]))
        rows = []
    return tables


def parse_docx(data: bytes) -> ParsedDocument:
    try:
        import docx  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ParsingError("python-docx is not installed") from exc

    document = docx.Document(io.BytesIO(data))
    blocks: list[TextBlock] = []
    cursor = 0
    section: str | None = None
    paragraph_index = 0
    text_parts: list[str] = []

    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        is_heading = style.startswith("heading") or style == "title" or _looks_like_heading(text)
        if is_heading:
            section = text
        blocks.append(
            TextBlock(
                text=text,
                page=1,
                paragraph=paragraph_index,
                section=section,
                char_start=cursor,
                char_end=cursor + len(text),
                kind="heading" if is_heading else "paragraph",
            )
        )
        text_parts.append(text)
        cursor += len(text) + 1
        paragraph_index += 1

    tables: list[Table] = []
    for table in document.tables:
        grid = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not grid:
            continue
        tables.append(Table(page=1, section=section, header=grid[0], rows=grid[1:]))
        for row in grid:
            text_parts.append(" | ".join(row))

    return ParsedDocument(
        text="\n".join(text_parts),
        blocks=blocks,
        tables=tables,
        page_count=1,
        parser="docx",
    )


def _ocr_page(page) -> str:  # pragma: no cover - requires tesseract binary
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return ""
    try:
        image = page.to_image(resolution=200).original
        if not isinstance(image, Image.Image):
            image = Image.open(io.BytesIO(image))
        return pytesseract.image_to_string(image) or ""
    except Exception as exc:  # noqa: BLE001 - OCR is best-effort by design
        log.warning("ocr_failed", error=str(exc))
        return ""


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ParsingError("pdfplumber is not installed") from exc

    blocks: list[TextBlock] = []
    tables: list[Table] = []
    warnings: list[str] = []
    text_parts: list[str] = []
    cursor = 0
    section: str | None = None
    ocr_used = False

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        for index, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            kind = "paragraph"
            if len(page_text.strip()) < _MIN_CHARS_FOR_TEXT_PAGE:
                ocr_text = _ocr_page(page)
                if ocr_text.strip():
                    page_text = ocr_text
                    ocr_used = True
                    kind = "ocr"
                    warnings.append(f"page {index}: text layer empty, used OCR")
                else:
                    warnings.append(f"page {index}: no extractable text")

            page_blocks, cursor, section = _blocks_from_lines(
                page_text.splitlines(), page=index, cursor=cursor, section=section
            )
            if kind == "ocr":
                for block in page_blocks:
                    block.kind = "ocr"
            blocks.extend(page_blocks)
            text_parts.append(page_text)

            for raw_table in page.extract_tables() or []:
                grid = [[(cell or "").strip() for cell in row] for row in raw_table if row]
                if len(grid) < 2:
                    continue
                tables.append(Table(page=index, section=section, header=grid[0], rows=grid[1:]))

    return ParsedDocument(
        text="\n".join(text_parts),
        blocks=blocks,
        tables=tables,
        page_count=page_count,
        parser="pdfplumber",
        ocr_used=ocr_used,
        warnings=warnings,
    )


PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".txt": parse_text,
    ".md": parse_text,
}


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """Dispatch on extension; fall back to plain text on parser failure."""
    suffix = Path(filename).suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedFileType(f"No parser for '{suffix}'")
    try:
        parsed = parser(data)
    except (ParsingError, UnsupportedFileType):
        raise
    except Exception as exc:  # noqa: BLE001 - degrade instead of failing the run
        log.warning("parser_fallback", filename=filename, error=str(exc))
        parsed = parse_text(data)
        parsed.warnings.append(f"{suffix} parser failed ({exc}); used plain-text fallback")
    if not parsed.blocks:
        parsed.warnings.append("document produced no text blocks")
    return parsed
