"""Unit tests for structural profiler."""

import pytest

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock
from superdocs_template_inference.profiling.structural_profiler import StructuralProfiler


class TestStructuralProfiler:
    """Tests for StructuralProfiler."""

    def test_profile_empty_document(self):
        """Test profiling an empty document."""
        doc = Document(
            document_id="doc-1",
            filename="empty.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.total_blocks == 0
        assert profile.paragraph_count == 0
        assert profile.heading_count == 0
        assert profile.table_count == 0

    def test_profile_simple_paragraphs(self):
        """Test profiling a document with simple paragraphs."""
        blocks = [
            ParagraphBlock(text="First paragraph"),
            ParagraphBlock(text="Second paragraph"),
            ParagraphBlock(text="Third"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.total_blocks == 3
        assert profile.paragraph_count == 3
        assert profile.heading_count == 0
        assert profile.min_paragraph_length == 5  # "Third"
        assert profile.max_paragraph_length == 16  # "Second paragraph"

    def test_profile_with_headings(self):
        """Test profiling a document with headings."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content under title"),
            ParagraphBlock(text="Subtitle", is_heading=True, heading_level=2),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.heading_count == 2
        assert profile.heading_levels == {1: 1, 2: 1}
        assert profile.max_heading_level == 2

    def test_profile_with_tables(self):
        """Test profiling a document with tables."""
        blocks = [
            ParagraphBlock(text="Intro"),
            TableBlock(rows=[["A", "B"], ["C", "D"]]),
            TableBlock(rows=[["X", "Y", "Z"]]),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.table_count == 2
        assert profile.table_dimensions == [(2, 2), (1, 3)]
        assert profile.avg_table_rows == 1.5
        assert profile.avg_table_cols == 2.5

    def test_profile_with_lists(self):
        """Test profiling a document with lists."""
        blocks = [
            ParagraphBlock(text="List item 1", is_list=True, list_level=0, list_ordered=True),
            ParagraphBlock(text="List item 2", is_list=True, list_level=0, list_ordered=True),
            ParagraphBlock(
                text="Nested item", is_list=True, list_level=1, list_ordered=False
            ),
            ParagraphBlock(text="Bullet point", is_list=True, list_level=0, list_ordered=False),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.list_item_count == 4
        assert profile.list_depth_max == 1
        assert profile.ordered_list_count == 2
        assert profile.unordered_list_count == 2

    def test_block_type_sequence(self):
        """Test block type sequence is preserved."""
        blocks = [
            ParagraphBlock(text="Para 1"),
            TableBlock(rows=[["A"]]),
            ParagraphBlock(text="Para 2"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.block_type_sequence == ["paragraph", "table", "paragraph"]

    def test_paragraph_statistics(self):
        """Test paragraph length statistics."""
        blocks = [
            ParagraphBlock(text="Short"),
            ParagraphBlock(text="This is a medium paragraph"),
            ParagraphBlock(text="This is a much longer paragraph with more content"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = StructuralProfiler()
        profile = profiler.profile(doc)

        assert profile.paragraph_lengths == [5, 26, 49]
        assert profile.min_paragraph_length == 5
        assert profile.max_paragraph_length == 49
        expected_avg = (5 + 26 + 49) / 3
        assert abs(profile.avg_paragraph_length - expected_avg) < 0.1
