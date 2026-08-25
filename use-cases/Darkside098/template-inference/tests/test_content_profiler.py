"""Unit tests for content profiler."""

import pytest

from superdocs_template_inference.models import Document, ParagraphBlock
from superdocs_template_inference.profiling.content_profiler import ContentProfiler


class TestContentProfiler:
    """Tests for ContentProfiler."""

    def test_profile_empty_document(self):
        """Test profiling an empty document."""
        doc = Document(
            document_id="doc-1",
            filename="empty.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        assert profile.total_text_length == 0
        assert profile.word_count == 0
        assert profile.unique_words_count == 0
        assert profile.heading_texts == []

    def test_profile_simple_content(self):
        """Test profiling simple content."""
        blocks = [
            ParagraphBlock(text="Hello world"),
            ParagraphBlock(text="This is a test"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        assert profile.total_text_length == len("Hello world This is a test")
        assert profile.word_count > 0
        assert profile.unique_words_count > 0

    def test_heading_extraction(self):
        """Test heading text extraction."""
        blocks = [
            ParagraphBlock(text="Main Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Regular content"),
            ParagraphBlock(text="Subsection", is_heading=True, heading_level=2),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        assert "Main Title" in profile.heading_texts
        assert "Subsection" in profile.heading_texts
        assert "Regular content" not in profile.heading_texts

    def test_vocabulary_extraction(self):
        """Test vocabulary extraction with frequencies."""
        blocks = [
            ParagraphBlock(
                text="The test document contains test content with the test data"
            ),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        # "test" should be the most frequent after stopword filtering
        assert "test" in profile.vocabulary
        assert profile.vocabulary["test"] > 0

    def test_text_statistics(self):
        """Test text statistics calculation."""
        blocks = [
            ParagraphBlock(text="Testing word count"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        assert "avg_word_length" in profile.text_statistics
        assert "unique_to_total_ratio" in profile.text_statistics
        assert profile.text_statistics["unique_to_total_ratio"] > 0
        assert profile.text_statistics["unique_to_total_ratio"] <= 1.0

    def test_top_vocabulary(self):
        """Test top vocabulary extraction."""
        blocks = [
            ParagraphBlock(
                text="apple apple apple banana banana cherry date date date date"
            ),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        # Top vocabulary should exist and be sorted by frequency
        assert len(profile.top_vocabulary) > 0
        if len(profile.top_vocabulary) > 1:
            assert profile.top_vocabulary[0][1] >= profile.top_vocabulary[1][1]

    def test_multiple_paragraphs_content(self):
        """Test profiling multiple paragraphs."""
        blocks = [
            ParagraphBlock(text="First paragraph content"),
            ParagraphBlock(text="Second paragraph with more content"),
            ParagraphBlock(text="Third paragraph"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = ContentProfiler()
        profile = profiler.profile(doc)

        assert profile.word_count > 0
        assert profile.total_text_length > 0
        assert profile.unique_words_count > 0
