from io import BytesIO

import pytest
from docx import Document

from core.docx_render import (
    MISSING_RESPONSE_DOCX_TEXT,
    build_cheatsheet_docx_bytes,
)
from core.models import (
    EntryStatus,
    ObjectionEntry,
    ParseResult,
    SourceUnit,
)
from core.parser import parse_objection_notes


def _document_from_bytes(
    content: bytes,
) -> Document:
    return Document(
        BytesIO(content)
    )


def test_docx_contains_one_block_per_objection():
    result = parse_objection_notes(
        [
            "- Too expensive",
            "resp: Start small.",
            "- Security?",
            "resp: Data is encrypted.",
        ]
    )

    content = build_cheatsheet_docx_bytes(
        result
    )

    document = _document_from_bytes(
        content
    )

    assert len(document.tables) == 2


def test_docx_preserves_source_wording():
    result = parse_objection_notes(
        [
            "- SECURITY???",
            (
                "resp: We encrypt data "
                "in transit and at rest."
            ),
        ]
    )

    document = _document_from_bytes(
        build_cheatsheet_docx_bytes(
            result
        )
    )

    text = "\n".join(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )

    assert "SECURITY???" in text

    assert (
        "We encrypt data in transit "
        "and at rest."
        in text
    )


def test_missing_response_is_flagged_in_docx():
    result = parse_objection_notes(
        [
            "- Implementation looks complicated",
        ]
    )

    document = _document_from_bytes(
        build_cheatsheet_docx_bytes(
            result
        )
    )

    text = document.tables[0].cell(
        0,
        0,
    ).text

    assert (
        MISSING_RESPONSE_DOCX_TEXT
        in text
    )


def test_docx_does_not_print_markdown_markers():
    result = parse_objection_notes(
        [
            "- Price?",
            "resp: Start small.",
        ]
    )

    document = _document_from_bytes(
        build_cheatsheet_docx_bytes(
            result
        )
    )

    all_text = "\n".join(
        paragraph.text
        for paragraph in document.paragraphs
    )

    all_text += "\n".join(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )

    assert "**Response**" not in all_text
    assert "## " not in all_text


def test_docx_generation_blocks_failed_coverage():
    result = ParseResult(
        source_units=[
            SourceUnit(
                source_id="SRC-001",
                position=1,
                text="- Security?",
            ),
            SourceUnit(
                source_id="SRC-002",
                position=2,
                text="- Price?",
            ),
        ],
        detected_objection_source_ids=[
            "SRC-001",
            "SRC-002",
        ],
        entries=[
            ObjectionEntry(
                entry_id="OBJ-001",
                objection="Security?",
                response=None,
                status=EntryStatus.MISSING_RESPONSE,
                objection_source_ids=[
                    "SRC-001"
                ],
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="coverage validation failed",
    ):
        build_cheatsheet_docx_bytes(
            result
        )