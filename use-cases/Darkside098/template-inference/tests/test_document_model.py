"""Unit tests for the document model."""

import pytest

from superdocs_template_inference.models import (
    Document,
    ParagraphBlock,
    TableBlock,
)


class TestParagraphBlock:
    """Tests for ParagraphBlock."""

    def test_create_simple_paragraph(self):
        """Test creating a simple paragraph block."""
        block = ParagraphBlock(text="Hello, world!")
        assert block.text == "Hello, world!"
        assert block.block_type == "paragraph"
        assert block.is_heading is False
        assert block.heading_level is None
        assert block.is_list is False
        assert block.list_level is None
        assert block.list_ordered is None

    def test_create_heading_block(self):
        """Test creating a heading block."""
        block = ParagraphBlock(
            text="Introduction",
            is_heading=True,
            heading_level=1,
            style_name="Heading 1",
        )
        assert block.text == "Introduction"
        assert block.is_heading is True
        assert block.heading_level == 1

    def test_create_list_block(self):
        """Test creating a list item block."""
        block = ParagraphBlock(
            text="First item",
            is_list=True,
            list_level=0,
            list_ordered=True,
        )
        assert block.text == "First item"
        assert block.is_list is True
        assert block.list_level == 0
        assert block.list_ordered is True

    def test_create_unordered_list_block(self):
        """Test creating an unordered list item block."""
        block = ParagraphBlock(
            text="Bullet point",
            is_list=True,
            list_level=0,
            list_ordered=False,
        )
        assert block.is_list is True
        assert block.list_ordered is False


class TestTableBlock:
    """Tests for TableBlock."""

    def test_create_empty_table(self):
        """Test creating an empty table block."""
        block = TableBlock()
        assert block.block_type == "table"
        assert block.rows == []
        assert block.num_rows == 0
        assert block.num_cols == 0

    def test_create_table_with_data(self):
        """Test creating a table with data."""
        rows = [
            ["Name", "Age"],
            ["Alice", "30"],
            ["Bob", "25"],
        ]
        block = TableBlock(rows=rows)
        assert block.num_rows == 3
        assert block.num_cols == 2
        assert block.rows[0] == ["Name", "Age"]
        assert block.rows[1] == ["Alice", "30"]

    def test_table_num_rows_num_cols_consistency(self):
        """Test that num_rows and num_cols are consistent."""
        rows = [["A", "B", "C"], ["D", "E", "F"]]
        block = TableBlock(rows=rows)
        assert block.num_rows == len(block.rows)
        assert block.num_cols == len(block.rows[0])

    def test_table_with_uneven_columns(self):
        """Test table with inconsistent column counts (uses first row)."""
        rows = [
            ["A", "B"],
            ["C", "D", "E"],  # More columns
        ]
        block = TableBlock(rows=rows)
        assert block.num_rows == 2
        assert block.num_cols == 2  # Based on first row


class TestDocument:
    """Tests for Document."""

    def test_create_empty_document(self):
        """Test creating an empty document."""
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
        )
        assert doc.document_id == "doc-1"
        assert doc.filename == "test.docx"
        assert doc.file_type == "docx"
        assert doc.blocks == []

    def test_create_document_with_blocks(self):
        """Test creating a document with blocks."""
        blocks = [
            ParagraphBlock(text="Title", is_heading=True, heading_level=1),
            ParagraphBlock(text="Some content."),
        ]
        doc = Document(
            document_id="doc-1",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-08-12T00:00:00Z",
            blocks=blocks,
        )
        assert len(doc.blocks) == 2
        assert doc.blocks[0].text == "Title"
        assert doc.blocks[1].text == "Some content."

    def test_invalid_file_type(self):
        """Test that invalid file types are rejected."""
        with pytest.raises(ValueError, match="Invalid file_type"):
            Document(
                document_id="doc-1",
                filename="test.txt",
                file_type="txt",  # Invalid
                loaded_at="2026-08-12T00:00:00Z",
            )

    def test_valid_file_types(self):
        """Test that valid file types are accepted."""
        for file_type in ["docx", "pdf"]:
            doc = Document(
                document_id="doc-1",
                filename=f"test.{file_type}",
                file_type=file_type,
                loaded_at="2026-08-12T00:00:00Z",
            )
            assert doc.file_type == file_type
