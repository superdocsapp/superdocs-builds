"""Unit tests for section detector."""

import pytest

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock
from superdocs_template_inference.profiling.section_detector import SectionDetector


class TestSectionDetector:
    """Tests for SectionDetector."""

    def test_detect_sections_empty_document(self):
        """Test section detection in empty document."""
        doc = Document(
            document_id="doc-1",
            filename="empty.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert sections == []

    def test_detect_sections_no_headings(self):
        """Test section detection with no headings - entire document is one section."""
        blocks = [
            ParagraphBlock(text="Paragraph 1"),
            ParagraphBlock(text="Paragraph 2"),
            ParagraphBlock(text="Paragraph 3"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert len(sections) == 1
        assert sections[0].start_block_idx == 0
        assert sections[0].end_block_idx == 2
        assert sections[0].title is None
        assert sections[0].boundary_marker == "document_start"

    def test_detect_sections_single_heading(self):
        """Test section detection with single heading."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content 1"),
            ParagraphBlock(text="Content 2"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert len(sections) == 1
        assert sections[0].title == "Title"
        assert sections[0].heading_level == 1
        assert sections[0].boundary_marker == "heading"

    def test_detect_sections_multiple_headings(self):
        """Test section detection with multiple headings."""
        blocks = [
            ParagraphBlock(text="Section 1", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content 1"),
            ParagraphBlock(text="Section 2", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content 2"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert len(sections) == 2
        assert sections[0].title == "Section 1"
        assert sections[1].title == "Section 2"

    def test_detect_sections_nested_headings(self):
        """Test section detection with nested headings."""
        blocks = [
            ParagraphBlock(text="Main", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content"),
            ParagraphBlock(text="Subsection", is_heading=True, heading_level=2),
            ParagraphBlock(text="Subcontent"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        # Each heading creates a new section
        assert len(sections) == 2
        assert sections[0].title == "Main"
        assert sections[0].heading_level == 1
        assert sections[1].title == "Subsection"
        assert sections[1].heading_level == 2

    def test_section_with_table(self):
        """Test section containing table."""
        blocks = [
            ParagraphBlock(text="Section with table", is_heading=True, heading_level=1),
            ParagraphBlock(text="Intro"),
            TableBlock(rows=[["A", "B"], ["C", "D"]]),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert len(sections) == 1
        assert sections[0].table_count == 1
        assert sections[0].paragraph_count == 2

    def test_section_content_length(self):
        """Test content length calculation in sections."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content with 20 chars"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        # Content length should include both heading and content
        expected_length = len("Title") + len("Content with 20 chars")
        assert sections[0].content_length == expected_length

    def test_consecutive_headings(self):
        """Test handling of consecutive headings without content."""
        blocks = [
            ParagraphBlock(text="Section 1", is_heading=True, heading_level=1),
            ParagraphBlock(text="Section 2", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        # Should still create separate sections for each heading
        assert len(sections) == 2

    def test_section_block_counts(self):
        """Test block count calculations in sections."""
        blocks = [
            ParagraphBlock(text="Section 1", is_heading=True, heading_level=1),
            ParagraphBlock(text="Para 1"),
            ParagraphBlock(text="Para 2"),
            TableBlock(rows=[["X"]]),
            ParagraphBlock(text="Section 2", is_heading=True, heading_level=1),
            ParagraphBlock(text="Para 3"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        detector = SectionDetector()
        sections = detector.detect_sections(doc)

        assert sections[0].block_count == 4  # heading + 2 paras + table
        assert sections[0].paragraph_count == 3
        assert sections[0].table_count == 1

        assert sections[1].block_count == 2  # heading + para
        assert sections[1].paragraph_count == 2
        assert sections[1].table_count == 0
