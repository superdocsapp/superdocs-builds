"""Unit tests for formatting profiler."""

import pytest

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock
from superdocs_template_inference.profiling.formatting_profiler import FormattingProfiler


class TestFormattingProfiler:
    """Tests for FormattingProfiler."""

    def test_profile_empty_document(self):
        """Test profiling an empty document."""
        doc = Document(
            document_id="doc-1",
            filename="empty.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.has_tables is False
        assert profile.has_lists is False
        assert profile.has_headings is False

    def test_style_name_extraction(self):
        """Test extraction of paragraph style names."""
        blocks = [
            ParagraphBlock(text="Normal paragraph", style_name="Normal"),
            ParagraphBlock(text="Another normal", style_name="Normal"),
            ParagraphBlock(text="List item", style_name="List Paragraph"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.paragraph_styles["Normal"] == 2
        assert profile.paragraph_styles["List Paragraph"] == 1

    def test_heading_detection(self):
        """Test heading detection."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1, style_name="Heading 1"),
            ParagraphBlock(text="Content", style_name="Normal"),
            ParagraphBlock(
                text="Subtitle", is_heading=True, heading_level=2, style_name="Heading 2"
            ),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.has_headings is True
        assert "Heading 1" in profile.heading_styles
        assert "Heading 2" in profile.heading_styles

    def test_list_detection(self):
        """Test list detection."""
        blocks = [
            ParagraphBlock(text="Item 1", is_list=True, list_level=0),
            ParagraphBlock(text="Item 2", is_list=True, list_level=0),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.has_lists is True

    def test_table_detection(self):
        """Test table detection."""
        blocks = [
            ParagraphBlock(text="Before table"),
            TableBlock(rows=[["A", "B"], ["C", "D"]]),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.has_tables is True

    def test_mixed_formatting(self):
        """Test document with mixed formatting elements."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1, style_name="Heading 1"),
            ParagraphBlock(text="Item 1", is_list=True),
            ParagraphBlock(text="Item 2", is_list=True),
            TableBlock(rows=[["A", "B"]]),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert profile.has_headings is True
        assert profile.has_lists is True
        assert profile.has_tables is True

    def test_no_style_names(self):
        """Test paragraphs with no style names."""
        blocks = [
            ParagraphBlock(text="Para 1", style_name=None),
            ParagraphBlock(text="Para 2", style_name=None),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = FormattingProfiler()
        profile = profiler.profile(doc)

        assert len(profile.paragraph_styles) == 0
        assert len(profile.heading_styles) == 0
