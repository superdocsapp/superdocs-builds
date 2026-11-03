"""Renders a companion document as real .docx instead of plain text.

Previously the "generate companion document" stage wrote SuperDocs'
`companion_text` straight to a .txt file. That's honest about content
but is the one artifact in this whole pipeline a human reviewer
actually opens and looks at -- and a plain-text file doesn't read as
"the retention-approved companion document" the way a properly
formatted Word doc does.

This module owns exactly one responsibility: given the extracted
fields and the raw text SuperDocs generated, produce .docx bytes. It
does not call SuperDocs and does not touch Box -- pipeline.py still
owns orchestration, retry, and upload; this is a pure rendering step,
which keeps it trivially unit-testable without any fake/live client.
"""
from __future__ import annotations

import io
from typing import Optional

from docx import Document
from docx.shared import Pt, RGBColor

from app.models import ExtractedFields

_HEADER_COLOR = RGBColor(0x1F, 0x2D, 0x3D)


def render_companion_docx(
    extracted: ExtractedFields,
    companion_text: str,
    source_filename: str,
    generated_at_iso: Optional[str] = None,
) -> bytes:
    """Builds a formatted .docx: a title, a metadata summary table of
    everything the extract stage populated (with an explicit "Not
    stated in source" for anything left None, honoring the same
    never-guess rule as the metadata write-back itself), and the
    generated companion text as body content.

    Returns raw .docx bytes ready to hand to Box's upload API --
    callers should never need to touch the Document object directly."""
    doc = Document()

    title = doc.add_heading("Companion Document", level=0)
    for run in title.runs:
        run.font.color.rgb = _HEADER_COLOR

    meta_para = doc.add_paragraph()
    meta_para.add_run(f"Source document: {source_filename}").italic = True
    if generated_at_iso:
        p2 = doc.add_paragraph()
        p2.add_run(f"Generated: {generated_at_iso}").italic = True

    doc.add_heading("Extracted Terms", level=1)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Field"
    hdr[1].text = "Value"
    hdr[2].text = "Confidence"

    rows = [
        ("Document Class", extracted.doc_class.value, extracted.doc_class_confidence),
        (
            "Counterparty",
            extracted.counterparty_name,
            extracted.field_confidence.get("counterparty_name"),
        ),
        (
            "Effective Date",
            extracted.effective_date,
            extracted.field_confidence.get("effective_date"),
        ),
        (
            "Expiration Date",
            extracted.expiration_date,
            extracted.field_confidence.get("expiration_date"),
        ),
        (
            "Contract Value",
            extracted.contract_value,
            extracted.field_confidence.get("contract_value"),
        ),
    ]
    for label, value, confidence in rows:
        row = table.add_row().cells
        row[0].text = label
        # Honest-over-fabricated, same rule as the Box metadata write:
        # a field the source didn't support is labeled as such, never
        # left blank in a way that could be misread as "value is empty
        # string" versus "we don't know."
        row[1].text = str(value) if value not in (None, "") else "Not stated in source"
        row[2].text = f"{confidence:.2f}" if confidence is not None else "\u2014"

    if extracted.extraction_notes.strip():
        doc.add_heading("Extraction Notes", level=1)
        doc.add_paragraph(extracted.extraction_notes.strip())

    doc.add_heading("Generated Content", level=1)
    if companion_text.strip():
        for line in companion_text.splitlines():
            if line.strip():
                doc.add_paragraph(line)
            else:
                doc.add_paragraph("")
    else:
        p = doc.add_paragraph("(SuperDocs returned no companion content for this document.)")
        p.runs[0].italic = True

    footer_p = doc.add_paragraph()
    footer_run = footer_p.add_run(
        "This document was generated automatically and normalized to the "
        "retention-approved template. Governance labels and legal holds on "
        "the source document were not overridden by this process."
    )
    footer_run.font.size = Pt(8)
    footer_run.italic = True

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
