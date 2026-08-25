"""Unit tests for document profiler."""

import json

import pytest

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock
from superdocs_template_inference.profiling.profiler import DocumentProfiler


class TestDocumentProfiler:
    """Tests for DocumentProfiler orchestration."""

    def test_profile_empty_document(self):
        """Test profiling an empty document."""
        doc = Document(
            document_id="doc-1",
            filename="empty.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        assert profile.profile_id != ""
        assert profile.document_id == "doc-1"
        assert profile.filename == "empty.docx"
        assert profile.structural.total_blocks == 0
        assert profile.sections == []

    def test_profile_simple_document(self):
        """Test profiling a simple document."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1, style_name="Heading 1"),
            ParagraphBlock(text="Some content here", style_name="Normal"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        assert profile.document_id == "doc-1"
        assert profile.structural.total_blocks == 2
        assert profile.structural.heading_count == 1
        assert len(profile.content.heading_texts) == 1
        assert profile.formatting.has_headings is True

    def test_profile_id_uniqueness(self):
        """Test that each profile gets a unique ID."""
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[ParagraphBlock(text="Content")],
        )

        profiler = DocumentProfiler()
        profile1 = profiler.profile(doc)
        profile2 = profiler.profile(doc)

        # Profile IDs should be unique
        assert profile1.profile_id != profile2.profile_id
        # But document IDs should be the same
        assert profile1.document_id == profile2.document_id

    def test_profile_version(self):
        """Test profile version is set."""
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        assert profile.profile_version == "1.0"

    def test_profile_timestamp(self):
        """Test profile timestamp is set."""
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=[],
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        assert "Z" in profile.profiled_at  # ISO 8601 with Z
        assert len(profile.profiled_at) > 0

    def test_to_dict_serialization(self):
        """Test profile serialization to dict."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Content"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)
        profile_dict = profiler.to_dict(profile)

        assert isinstance(profile_dict, dict)
        assert "profile_id" in profile_dict
        assert "document_id" in profile_dict
        assert "structural" in profile_dict
        assert "content" in profile_dict
        assert "formatting" in profile_dict
        assert "sections" in profile_dict

    def test_to_json_serialization(self):
        """Test profile serialization to JSON."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)
        json_str = profiler.to_json(profile)

        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["document_id"] == "doc-1"

    def test_profile_all_components_populated(self):
        """Test that all profile components are populated."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1, style_name="Heading 1"),
            ParagraphBlock(text="Item 1", is_list=True, list_level=0),
            ParagraphBlock(text="Item 2", is_list=True, list_level=0),
            TableBlock(rows=[["A", "B"]]),
            ParagraphBlock(text="Regular content", style_name="Normal"),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Verify all components have data
        assert profile.structural is not None
        assert profile.structural.total_blocks == 5

        assert profile.content is not None
        assert len(profile.content.heading_texts) > 0

        assert profile.formatting is not None
        assert profile.formatting.has_headings is True
        assert profile.formatting.has_lists is True
        assert profile.formatting.has_tables is True

        assert len(profile.sections) > 0

    def test_profiler_does_not_modify_document(self):
        """Test that profiler does not modify the original document."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )

        original_block_count = len(doc.blocks)
        profiler = DocumentProfiler()
        profile = profiler.profile(doc)

        # Document should be unchanged
        assert len(doc.blocks) == original_block_count
        assert doc.blocks[0].text == "Title"
