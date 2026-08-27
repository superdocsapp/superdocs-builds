"""The returned .docx identifies its own review round, whatever route it took back."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from _docx_fixtures import reviewed_docx
from notion_review.docx_markup import parse_docx
from notion_review.docx_markup.security import DocxError
from notion_review.docx_markup.stamp import (
    identify_round,
    read_round_id,
    round_id_from_filename,
    stamp_round_id,
)

ROUND = "round_41f8a23f6130"


def test_a_stamped_file_reports_its_round() -> None:
    stamped = stamp_round_id(reviewed_docx(), ROUND)
    assert read_round_id(stamped) == ROUND


def test_stamping_leaves_the_markup_intact() -> None:
    # The stamp must not disturb what the reviewer wrote.
    before = parse_docx(reviewed_docx())
    after = parse_docx(stamp_round_id(reviewed_docx(), ROUND))
    assert [p.original_text for p in after.paragraphs] == [
        p.original_text for p in before.paragraphs
    ]
    assert [p.proposed_text for p in after.changes()] == [p.proposed_text for p in before.changes()]
    assert after.reviewers() == before.reviewers()


def test_the_stamped_file_is_still_a_valid_docx_package() -> None:
    stamped = stamp_round_id(reviewed_docx(), ROUND)
    with zipfile.ZipFile(BytesIO(stamped)) as archive:
        names = set(archive.namelist())
        content_types = archive.read("[Content_Types].xml").decode()
        rels = archive.read("_rels/.rels").decode()
    assert "docProps/custom.xml" in names
    assert "custom-properties+xml" in content_types  # the part is declared
    assert "docProps/custom.xml" in rels  # and related from the package root


def test_stamping_twice_does_not_duplicate_the_part() -> None:
    once = stamp_round_id(reviewed_docx(), ROUND)
    twice = stamp_round_id(once, ROUND)
    with zipfile.ZipFile(BytesIO(twice)) as archive:
        content_types = archive.read("[Content_Types].xml").decode()
        rels = archive.read("_rels/.rels").decode()
    assert content_types.count("docProps/custom.xml") == 1
    assert rels.count("docProps/custom.xml") == 1
    assert read_round_id(twice) == ROUND


def test_an_unstamped_file_reports_nothing() -> None:
    assert read_round_id(reviewed_docx()) is None


def test_the_filename_is_the_fallback_when_properties_are_dropped() -> None:
    # Some editors drop custom properties on save; the name still carries the id.
    assert round_id_from_filename(f"review-{ROUND}.docx") == ROUND
    assert round_id_from_filename(f"Copy of review-{ROUND} (1).docx") == ROUND
    assert round_id_from_filename("some-document.docx") is None


def test_identify_round_prefers_the_stamp_then_the_name() -> None:
    stamped = stamp_round_id(reviewed_docx(), ROUND)
    assert identify_round(stamped, "renamed-by-the-reviewer.docx") == ROUND
    assert identify_round(reviewed_docx(), f"review-{ROUND}.docx") == ROUND
    assert identify_round(reviewed_docx(), "no-clues.docx") is None


def test_stamping_a_non_docx_is_refused() -> None:
    with pytest.raises(DocxError):
        stamp_round_id(b"this is not a docx", ROUND)
