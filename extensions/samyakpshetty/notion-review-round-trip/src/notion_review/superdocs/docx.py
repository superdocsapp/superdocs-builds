"""Render document HTML to a real .docx — the fake's stand-in for SuperDocs' export.

The live SuperDocs returns a styled .docx from its export endpoint; the fake produces a genuine
Word file here so the reviewer copy is real and the round-trip is testable end to end. Headings
map to Word heading styles, tables to Word tables, everything else to paragraphs.
"""

from __future__ import annotations

from io import BytesIO
from typing import cast

from docx import Document
from docx.document import Document as DocxDocument
from lxml import html as lxml_html
from lxml.html import HtmlElement

_HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3}
_PARAGRAPH_TAGS = frozenset({"p", "blockquote", "summary", "li", "pre"})


def html_to_docx(html: str) -> bytes:
    """Convert document HTML into Word .docx bytes."""
    root = lxml_html.fromstring(f"<div>{html}</div>")
    doc = Document()

    for el in root.iter():
        tag = el.tag  # a callable for comments/PIs; the comparisons below simply miss those
        if tag == "table":
            _add_table(doc, el)
        elif tag in _HEADING_LEVEL:
            doc.add_heading(_text(el), level=_HEADING_LEVEL[tag])
        elif tag in _PARAGRAPH_TAGS:
            text = _text(el)
            if text:
                doc.add_paragraph(text)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _text(el: HtmlElement) -> str:
    return str(cast(HtmlElement, el).text_content()).strip()


def _add_table(doc: DocxDocument, table_el: HtmlElement) -> None:
    rows = list(table_el.iter("tr"))
    if not rows:
        return
    first_cells = list(rows[0].iter("td"))
    table = doc.add_table(rows=0, cols=max(1, len(first_cells)))
    for row_el in rows:
        cells = list(row_el.iter("td"))
        target = table.add_row().cells
        for i, cell in enumerate(cells):
            if i < len(target):
                target[i].text = _text(cell)
