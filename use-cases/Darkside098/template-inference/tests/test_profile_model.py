"""Unit tests for profile data models."""

import pytest

from superdocs_template_inference.models import (
    ContentProfile,
    DetectedSection,
    DocumentProfile,
    FormattingProfile,
    StructuralProfile,
)


class TestStructuralProfile:
    """Tests for StructuralProfile."""

    def test_create_minimal_structural_profile(self):
        """Test creating a minimal structural profile."""
        profile = StructuralProfile(
            total_blocks=10,
            paragraph_count=8,
            heading_count=2,
            table_count=0,
            list_item_count=0,
            heading_levels={1: 1, 2: 1},
            max_heading_level=2,
            table_dimensions=[],
            avg_table_rows=None,
            avg_table_cols=None,
            block_type_sequence=["paragraph"] * 8 + ["heading"] * 2,
            paragraph_lengths=[100, 200, 150, 120, 180, 90, 110, 95],
            avg_paragraph_length=131.25,
            min_paragraph_length=90,
            max_paragraph_length=200,
            list_depth_max=None,
            ordered_list_count=0,
            unordered_list_count=0,
        )

        assert profile.total_blocks == 10
        assert profile.paragraph_count == 8
        assert profile.heading_count == 2


class TestContentProfile:
    """Tests for ContentProfile."""

    def test_create_content_profile(self):
        """Test creating a content profile."""
        profile = ContentProfile(
            total_text_length=500,
            word_count=100,
            unique_words_count=60,
            heading_texts=["Introduction", "Methods"],
            vocabulary={"test": 5, "document": 3},
            top_vocabulary=[("test", 5), ("document", 3)],
            text_statistics={"avg_word_length": 5.2, "unique_to_total_ratio": 0.6},
        )

        assert profile.total_text_length == 500
        assert profile.word_count == 100
        assert len(profile.heading_texts) == 2


class TestFormattingProfile:
    """Tests for FormattingProfile."""

    def test_create_formatting_profile(self):
        """Test creating a formatting profile."""
        profile = FormattingProfile(
            paragraph_styles={"Normal": 8, "List Paragraph": 2},
            heading_styles={"Heading 1": 1, "Heading 2": 1},
            has_tables=False,
            has_lists=True,
            has_headings=True,
        )

        assert profile.has_headings is True
        assert profile.has_lists is True
        assert profile.has_tables is False


class TestDetectedSection:
    """Tests for DetectedSection."""

    def test_create_detected_section(self):
        """Test creating a detected section."""
        section = DetectedSection(
            section_id="sec-1",
            start_block_idx=0,
            end_block_idx=5,
            title="Introduction",
            heading_level=1,
            block_count=6,
            paragraph_count=5,
            table_count=0,
            content_length=300,
            boundary_marker="heading",
        )

        assert section.title == "Introduction"
        assert section.block_count == 6
        assert section.boundary_marker == "heading"

    def test_section_with_no_heading(self):
        """Test creating a section without heading."""
        section = DetectedSection(
            section_id="sec-1",
            start_block_idx=0,
            end_block_idx=3,
            title=None,
            heading_level=None,
            block_count=4,
            paragraph_count=4,
            table_count=0,
            content_length=200,
            boundary_marker="document_start",
        )

        assert section.title is None
        assert section.heading_level is None


class TestDocumentProfile:
    """Tests for DocumentProfile."""

    def test_create_document_profile(self):
        """Test creating a document profile."""
        structural = StructuralProfile(
            total_blocks=10,
            paragraph_count=8,
            heading_count=2,
            table_count=0,
            list_item_count=0,
            heading_levels={1: 1},
            max_heading_level=1,
            table_dimensions=[],
            avg_table_rows=None,
            avg_table_cols=None,
            block_type_sequence=["paragraph"] * 8 + ["heading"] * 2,
            paragraph_lengths=[100] * 8,
            avg_paragraph_length=100.0,
            min_paragraph_length=100,
            max_paragraph_length=100,
            list_depth_max=None,
            ordered_list_count=0,
            unordered_list_count=0,
        )

        content = ContentProfile(
            total_text_length=800,
            word_count=80,
            unique_words_count=50,
            heading_texts=["Title"],
            vocabulary={"word": 1},
            top_vocabulary=[("word", 1)],
        )

        formatting = FormattingProfile(
            paragraph_styles={"Normal": 8},
            heading_styles={"Heading 1": 1},
            has_tables=False,
            has_lists=False,
            has_headings=True,
        )

        profile = DocumentProfile(
            profile_id="prof-1",
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            structural=structural,
            content=content,
            formatting=formatting,
            sections=[],
        )

        assert profile.filename == "test.docx"
        assert profile.file_type == "docx"
        assert profile.structural.total_blocks == 10

    def test_document_profile_with_sections(self):
        """Test creating a document profile with sections."""
        structural = StructuralProfile(
            total_blocks=5,
            paragraph_count=5,
            heading_count=1,
            table_count=0,
            list_item_count=0,
            heading_levels={1: 1},
            max_heading_level=1,
            table_dimensions=[],
            avg_table_rows=None,
            avg_table_cols=None,
            block_type_sequence=["heading", "paragraph"] * 2 + ["paragraph"],
            paragraph_lengths=[100, 100, 100, 100],
            avg_paragraph_length=100.0,
            min_paragraph_length=100,
            max_paragraph_length=100,
            list_depth_max=None,
            ordered_list_count=0,
            unordered_list_count=0,
        )

        content = ContentProfile(
            total_text_length=400,
            word_count=40,
            unique_words_count=30,
            heading_texts=["Title"],
            vocabulary={"word": 1},
            top_vocabulary=[("word", 1)],
        )

        formatting = FormattingProfile(
            paragraph_styles={"Normal": 4},
            heading_styles={"Heading 1": 1},
            has_tables=False,
            has_lists=False,
            has_headings=True,
        )

        section = DetectedSection(
            section_id="sec-1",
            start_block_idx=0,
            end_block_idx=4,
            title="Title",
            heading_level=1,
            block_count=5,
            paragraph_count=4,
            table_count=0,
            content_length=400,
            boundary_marker="heading",
        )

        profile = DocumentProfile(
            profile_id="prof-1",
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            structural=structural,
            content=content,
            formatting=formatting,
            sections=[section],
        )

        assert len(profile.sections) == 1
        assert profile.sections[0].title == "Title"
