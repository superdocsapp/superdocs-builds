from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from core.models import EntryStatus, ParseResult
from core.validation import validate_coverage


MISSING_RESPONSE_DOCX_TEXT = (
    "Missing response in source notes - "
    "human input required."
)


def build_cheatsheet_docx_bytes(
    result: ParseResult,
    title: str = "Objection Handling Cheatsheet",
) -> bytes:
    """
    Render a clean, scannable DOCX.

    No objection or response content is invented.
    Rendering is blocked when coverage validation fails.
    """

    coverage = validate_coverage(result)

    if not coverage.is_complete:
        raise ValueError(
            "DOCX generation blocked because "
            "coverage validation failed."
        )

    document = Document()

    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    normal_style = document.styles["Normal"]
    normal_style.font.name = "Arial"
    normal_style.font.size = Pt(10.5)

    # --------------------------------------------------
    # Title
    # --------------------------------------------------

    title_paragraph = document.add_paragraph()
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    title_run = title_paragraph.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(20)

    # --------------------------------------------------
    # Coverage summary
    # --------------------------------------------------

    summary = document.add_paragraph()
    summary.alignment = WD_ALIGN_PARAGRAPH.CENTER

    summary_run = summary.add_run(
        f"{coverage.detected_objection_count} objections  |  "
        f"{coverage.complete_count} complete  |  "
        f"{coverage.missing_response_count} missing response"
    )

    summary_run.font.size = Pt(9)

    document.add_paragraph()

    # --------------------------------------------------
    # One objection per block
    # --------------------------------------------------

    for index, entry in enumerate(
        result.entries,
        start=1,
    ):
        table = document.add_table(
            rows=1,
            cols=1,
        )

        table.style = "Table Grid"

        cell = table.cell(
            0,
            0,
        )

        # Objection label
        label = cell.paragraphs[0]

        label_run = label.add_run(
            f"OBJECTION {index}"
        )

        label_run.bold = True
        label_run.font.size = Pt(9)

        # Objection content
        objection_paragraph = cell.add_paragraph()

        objection_run = objection_paragraph.add_run(
            entry.objection
        )

        objection_run.bold = True
        objection_run.font.size = Pt(12)

        # Response label
        response_label = cell.add_paragraph()

        response_label_run = response_label.add_run(
            "RESPONSE"
        )

        response_label_run.bold = True
        response_label_run.font.size = Pt(9)

        # Response body
        response_paragraph = cell.add_paragraph()

        if (
            entry.status == EntryStatus.COMPLETE
            and entry.response
        ):
            response_paragraph.add_run(
                entry.response
            )

        else:
            missing_run = response_paragraph.add_run(
                MISSING_RESPONSE_DOCX_TEXT
            )

            missing_run.bold = True
            missing_run.italic = True

        # Source trace
        source_paragraph = cell.add_paragraph()

        source_ids = (
            entry.objection_source_ids
            + entry.response_source_ids
        )

        source_run = source_paragraph.add_run(
            "Source: "
            + ", ".join(source_ids)
        )

        source_run.italic = True
        source_run.font.size = Pt(8)

        document.add_paragraph()

    # --------------------------------------------------
    # Footer note
    # --------------------------------------------------

    note = document.add_paragraph()

    note_run = note.add_run(
        "Source wording preserved. "
        "Missing responses are flagged rather than generated."
    )

    note_run.italic = True
    note_run.font.size = Pt(8)

    buffer = BytesIO()

    document.save(buffer)

    return buffer.getvalue()