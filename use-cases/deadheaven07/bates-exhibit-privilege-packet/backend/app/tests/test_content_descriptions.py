"""Tests for content-derived exhibit descriptions.

Invariant: Exhibit descriptions must come from document CONTENT, not filenames.
These tests ensure the description_generator never uses filename as primary source.
"""
import pytest

from app.services.description_generator import (
    DescriptionResult,
    generate_description,
    generate_description_from_filename,
    generate_description_from_text,
)


class TestContentDerivedDescriptions:
    """Prove that descriptions come from content, not filenames."""

    def test_content_used_not_filename(self):
        content = "IN THE SUPERIOR COURT OF CALIFORNIA\nCounty of Los Angeles\nCase No. 24-CV-12345"
        filename = "random_scanned_doc_001.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert "superior court" in result.description.lower() or "los angeles" in result.description.lower() or "case" in result.description.lower()
        assert filename not in result.description

    def test_fallback_only_when_no_content(self):
        filename = "exhibit_a_medical_records.pdf"
        result = generate_description("", filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "filename_fallback"
        assert "exhibit" in result.description.lower() or "medical" in result.description.lower()

    def test_fallback_only_when_whitespace_content(self):
        filename = "contract_deed_2024.pdf"
        result = generate_description("   \n  \n  ", filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "filename_fallback"

    def test_short_content_still_used(self):
        content = "This is a contract between Party A and Party B."
        filename = "random_name.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert "contract" in result.description.lower()

    def test_content_extraction_skips_headers(self):
        content = "PAGE 1 OF 5\nCONFIDENTIAL\nIN THE MATTER OF SMITH v. JONES\nContract Agreement\nThis agreement is made on..."
        filename = "doc.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert "page 1" not in result.description.lower()
        assert "confidential" not in result.description.lower()
        assert len(result.description) > 10

    def test_content_with_newlines_extracts_meaningful_lines(self):
        content = "HEADER TEXT\n\n\nThis is the actual content of the document.\nAnother meaningful line.\n\nPage 2 of 10"
        filename = "test.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert len(result.description) > 5

    def test_generate_from_text_direct(self):
        text = "LOAN AGREEMENT\nThis loan agreement is entered into on January 1, 2024."
        result = generate_description_from_text(text)
        assert isinstance(result, DescriptionResult)
        assert len(result.description) > 10
        assert "loan" in result.description.lower() or "agreement" in result.description.lower()

    def test_generate_from_text_empty(self):
        result = generate_description_from_text("")
        assert isinstance(result, DescriptionResult)
        assert result.description == ""
        assert result.source == "fallback_empty"

    def test_generate_from_text_only_headers(self):
        text = "PAGE 1\nCONFIDENTIAL\nPRIVILEGED\nPAGE 2"
        result = generate_description_from_text(text)
        assert isinstance(result, DescriptionResult)
        assert result.description == ""
        assert result.source == "fallback_empty"

    def test_generate_from_filename_direct(self):
        filename = "exhibit_b_financial_statement.pdf"
        result = generate_description_from_filename(filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "filename_fallback"
        assert "exhibit" in result.description.lower() or "financial" in result.description.lower()

    def test_content_description_not_just_filename(self):
        content = "SETTLEMENT AGREEMENT\nThis Settlement Agreement is made effective as of..."
        filename = "random_name_with_no_info.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert "settlement" in result.description.lower()
        assert filename not in result.description

    def test_long_content_truncated(self):
        content = "A" * 500
        filename = "doc.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert len(result.description) <= 500

    def test_multiline_content_best_lines_selected(self):
        content = "PAGE 1\n\nTHE REGENTS OF THE UNIVERSITY OF CALIFORNIA\n\nThis is a research collaboration agreement between UC and Industry Corp.\n\nPage 2 of 10"
        filename = "random.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert len(result.description) > 10

    def test_boilerplate_skipped(self):
        content = "This page intentionally left blank.\n\nReal content starts here.\nTestimony of John Doe."
        filename = "doc.pdf"
        result = generate_description(content, filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "content_summary"
        assert "intentionally" not in result.description.lower()
        assert len(result.description) > 5

    def test_filename_fallback_still_useful(self):
        filename = "Exhibit_12_Bates_001-050.pdf"
        result = generate_description("", filename)
        assert isinstance(result, DescriptionResult)
        assert result.source == "filename_fallback"
        assert len(result.description) > 0

    def test_confidence_score_populated(self):
        content = "Meaningful content here."
        result = generate_description(content, "test.pdf")
        assert isinstance(result, DescriptionResult)
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence > 0.0

    def test_no_text_no_filename_returns_empty(self):
        result = generate_description(None, None)
        assert isinstance(result, DescriptionResult)
        assert result.description == ""
        assert result.source == "fallback_empty"
