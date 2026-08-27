from __future__ import annotations

import pytest

from _docx_fixtures import (
    CHANGE_AUTHOR,
    COMMENT_AUTHOR,
    COMMENTED_PARA,
    HEADING,
    HYPERLINK_ORIGINAL,
    HYPERLINK_PROPOSED,
    MOVE_ORIGINAL,
    MOVE_PROPOSED,
    PARA_ORIGINAL,
    PARA_PROPOSED,
    build_docx,
    hyperlink_tracked_change_docx,
    moved_text_docx,
    reviewed_docx,
    zip_with_too_many_members,
)
from notion_review.docx_markup import DocxError, DocxSecurityError, parse_docx
from notion_review.docx_markup.security import read_docx_parts, secure_fromstring


def test_tracked_change_reconstructs_original_and_proposed() -> None:
    markup = parse_docx(reviewed_docx())
    change = next(p for p in markup.changes() if p.is_text_change)
    assert change.original_text == PARA_ORIGINAL
    assert change.proposed_text == PARA_PROPOSED
    assert "Q3" in change.original_text and "Q3" not in change.proposed_text
    assert "Q4" in change.proposed_text
    assert change.authors == [CHANGE_AUTHOR]  # attribution preserved


def test_tracked_change_inside_a_hyperlink_is_not_dropped() -> None:
    markup = parse_docx(hyperlink_tracked_change_docx())
    change = next(p for p in markup.changes() if p.is_text_change)
    assert change.original_text == HYPERLINK_ORIGINAL
    assert change.proposed_text == HYPERLINK_PROPOSED
    assert change.authors == [CHANGE_AUTHOR]


def test_moved_text_reads_as_original_then_proposed() -> None:
    markup = parse_docx(moved_text_docx())
    change = next(p for p in markup.changes() if p.is_text_change)
    assert change.original_text == MOVE_ORIGINAL
    assert change.proposed_text == MOVE_PROPOSED
    assert change.authors == [CHANGE_AUTHOR]


def test_comment_is_extracted_with_author() -> None:
    markup = parse_docx(reviewed_docx())
    commented = next(p for p in markup.changes() if p.comments)
    assert commented.original_text == COMMENTED_PARA
    assert not commented.is_text_change  # a comment is not a text edit
    assert commented.comments[0].author == COMMENT_AUTHOR
    assert "Postgres version" in commented.comments[0].text


def test_unchanged_paragraph_is_not_a_change() -> None:
    markup = parse_docx(reviewed_docx())
    headings = [p for p in markup.paragraphs if p.original_text == HEADING]
    assert headings and not headings[0].changed
    assert HEADING not in [p.original_text for p in markup.changes()]


def test_reviewers_are_listed_in_order() -> None:
    markup = parse_docx(reviewed_docx())
    assert markup.reviewers() == [CHANGE_AUTHOR, COMMENT_AUTHOR]


def test_xxe_payload_is_refused() -> None:
    malicious = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "boom">]><r>&x;</r>'
    with pytest.raises(DocxSecurityError):
        secure_fromstring(malicious)


def test_document_with_a_doctype_is_refused() -> None:
    doc = (
        '<?xml version="1.0"?><!DOCTYPE w:document>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body></w:body></w:document>"
    )
    with pytest.raises(DocxSecurityError):
        parse_docx(build_docx(doc))


def test_zip_with_too_many_members_is_refused() -> None:
    with pytest.raises(DocxSecurityError):
        read_docx_parts(zip_with_too_many_members(), {"word/document.xml"})


def test_not_a_zip_raises_docx_error() -> None:
    with pytest.raises(DocxError):
        parse_docx(b"this is not a docx")


def test_missing_document_part_raises() -> None:
    # A valid zip, but without word/document.xml.
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", b"nope")
    with pytest.raises(DocxError):
        parse_docx(buffer.getvalue())
