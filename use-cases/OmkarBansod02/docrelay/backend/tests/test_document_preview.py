from docrelay.services.document_preview import preview_from_canonical


def _paragraph(text: str, *, style: str = "NORMAL_TEXT") -> dict[str, object]:
    return {
        "type": "paragraph",
        "paragraphStyle": {"namedStyleType": style},
        "runs": [{"kind": "text", "text": f"{text}\n"}],
    }


def _canonical(*body: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "docrelay.google-native-canonical.v1",
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0", "title": "Tab 1"},
                "body": list(body),
            }
        ],
    }


def test_preview_extracts_frozen_paragraphs_and_headings() -> None:
    preview = preview_from_canonical(
        _canonical(
            _paragraph("Payment Terms", style="HEADING_1"),
            _paragraph("Payment terms are 30 days after receipt of a valid invoice."),
            _paragraph("Warranty", style="HEADING_1"),
            _paragraph("Warranty lasts 12 months."),
        ),
        revision_id="A1roV34H9ERMvb0Y",
    )

    assert preview.available is True
    assert preview.revision_id == "A1roV34H9ERMvb0Y"
    assert [(block.kind, block.named_style, block.text) for block in preview.blocks] == [
        ("heading", "HEADING_1", "Payment Terms"),
        ("paragraph", "NORMAL_TEXT", "Payment terms are 30 days after receipt of a valid invoice."),
        ("heading", "HEADING_1", "Warranty"),
        ("paragraph", "NORMAL_TEXT", "Warranty lasts 12 months."),
    ]


def test_preview_skips_tables_section_breaks_and_empty_paragraphs() -> None:
    preview = preview_from_canonical(
        _canonical(
            {"type": "sectionBreak", "sectionStyle": {}},
            _paragraph("   "),
            {
                "type": "table",
                "tableRows": [
                    {
                        "cells": [
                            {
                                "content": [_paragraph("Hidden table cell")],
                            }
                        ]
                    }
                ],
            },
            _paragraph("Visible body paragraph."),
        ),
        revision_id="rev-1",
    )

    assert preview.available is True
    assert [block.text for block in preview.blocks] == ["Visible body paragraph."]


def test_preview_is_unavailable_when_canonical_has_no_readable_text() -> None:
    empty = preview_from_canonical({"tabs": []}, revision_id="rev-empty")
    malformed = preview_from_canonical({"not": "canonical"}, revision_id="rev-bad")
    missing = preview_from_canonical(None, revision_id="rev-none")

    assert empty.available is False and empty.blocks == ()
    assert malformed.available is False and malformed.blocks == ()
    assert missing.available is False and missing.blocks == ()


def test_preview_does_not_invent_content() -> None:
    preview = preview_from_canonical(
        _canonical(_paragraph("Only this sentence exists.")),
        revision_id="rev-2",
    )
    encoded = " ".join(block.text for block in preview.blocks)
    assert "Only this sentence exists." in encoded
    assert "14 days" not in encoded
    assert "Confidentiality" not in encoded
