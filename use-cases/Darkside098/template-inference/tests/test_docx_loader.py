"""Unit tests for the DOCX loader."""

import pytest
from unittest.mock import Mock, MagicMock, patch

from superdocs_template_inference.exceptions import DocumentLoadError
from superdocs_template_inference.ingestion import DOCXLoader
from superdocs_template_inference.models import (
    Document,
    ParagraphBlock,
    TableBlock,
)


class TestDOCXLoader:
    """Tests for DOCXLoader."""

    def test_loader_inheritance(self):
        """Test that DOCXLoader is a proper DocumentLoader."""
        from superdocs_template_inference.ingestion import DocumentLoader

        assert issubclass(DOCXLoader, DocumentLoader)

    def test_load_nonexistent_file(self):
        """Test that loading a nonexistent file raises DocumentLoadError."""
        loader = DOCXLoader()
        with pytest.raises(DocumentLoadError):
            loader.load("/nonexistent/file/path.docx")

    def test_extract_paragraph_block_with_text(self):
        """Test extracting a paragraph block with text."""
        loader = DOCXLoader()
        paragraph = Mock()
        paragraph.text = "Sample paragraph text"
        paragraph.style = Mock()
        paragraph.style.name = "Normal"
        paragraph._element = Mock()
        pPr_mock = Mock()
        pPr_mock.find = Mock(return_value=None)
        paragraph._element.get_or_add_pPr = Mock(return_value=pPr_mock)

        block = loader._extract_paragraph_block(paragraph)

        assert block is not None
        assert block.text == "Sample paragraph text"
        assert block.style_name == "Normal"
        assert block.is_heading is False
        assert block.is_list is False

    def test_extract_paragraph_block_empty(self):
        """Test that empty paragraphs are ignored."""
        loader = DOCXLoader()
        paragraph = Mock()
        paragraph.text = "   "  # Only whitespace
        paragraph.style = Mock()
        paragraph.style.name = "Normal"

        block = loader._extract_paragraph_block(paragraph)

        assert block is None  # Empty paragraphs are ignored

    def test_extract_paragraph_block_without_iterable_runs(self):
        """Test that paragraphs lacking iterable runs still extract cleanly."""
        loader = DOCXLoader()
        paragraph = Mock()
        paragraph.text = "Sample paragraph text"
        paragraph.style = Mock()
        paragraph.style.name = "Normal"
        paragraph.runs = Mock()
        paragraph.runs.__iter__ = Mock(side_effect=TypeError("Mock object is not iterable"))
        paragraph._element = Mock()
        pPr_mock = Mock()
        pPr_mock.find = Mock(return_value=None)
        paragraph._element.get_or_add_pPr = Mock(return_value=pPr_mock)

        block = loader._extract_paragraph_block(paragraph)

        assert block is not None
        assert block.text == "Sample paragraph text"
        assert block.style_name == "Normal"
        assert block.is_heading is False
        assert block.is_list is False

    def test_extract_heading_paragraph(self):
        """Test extracting a heading paragraph."""
        loader = DOCXLoader()
        paragraph = Mock()
        paragraph.text = "Section Title"
        paragraph.style = Mock()
        paragraph.style.name = "Heading 1"
        paragraph._element = Mock()
        paragraph._element.get_or_add_pPr = Mock(return_value=Mock())

        block = loader._extract_paragraph_block(paragraph)

        assert block is not None
        assert block.is_heading is True
        assert block.heading_level == 1

    def test_extract_heading_levels(self):
        """Test extraction of various heading levels."""
        loader = DOCXLoader()

        for level in range(1, 7):
            paragraph = Mock()
            paragraph.text = f"Heading {level}"
            paragraph.style = Mock()
            paragraph.style.name = f"Heading {level}"
            paragraph._element = Mock()
            paragraph._element.get_or_add_pPr = Mock(return_value=Mock())

            block = loader._extract_paragraph_block(paragraph)

            assert block.heading_level == level
            assert block.is_heading is True

    def test_extract_table_block(self):
        """Test extracting a table block."""
        loader = DOCXLoader()

        # Create mock table
        table = Mock()
        row1 = Mock()
        row1.cells = [Mock(text="Header 1"), Mock(text="Header 2")]
        row2 = Mock()
        row2.cells = [Mock(text="Cell 1"), Mock(text="Cell 2")]
        table.rows = [row1, row2]

        block = loader._extract_table_block(table)

        assert block.block_type == "table"
        assert block.num_rows == 2
        assert block.num_cols == 2
        assert block.rows[0] == ["Header 1", "Header 2"]
        assert block.rows[1] == ["Cell 1", "Cell 2"]

    def test_is_list_paragraph_false(self):
        """Test that non-list paragraphs are correctly identified."""
        loader = DOCXLoader()
        paragraph = Mock()
        pPr = Mock()
        pPr.find = Mock(return_value=None)
        paragraph._element = Mock()
        paragraph._element.get_or_add_pPr = Mock(return_value=pPr)

        is_list = loader._is_list_paragraph(paragraph)

        assert is_list is False

    def test_get_list_level_none_for_non_list(self):
        """Test that non-list paragraphs return None for list level."""
        loader = DOCXLoader()
        paragraph = Mock()
        pPr = Mock()
        pPr.find = Mock(return_value=None)
        paragraph._element = Mock()
        paragraph._element.get_or_add_pPr = Mock(return_value=pPr)

        level = loader._get_list_level(paragraph)

        assert level is None

    def test_is_ordered_list_none_for_non_list(self):
        """Test that non-list paragraphs return None for list_ordered."""
        loader = DOCXLoader()
        paragraph = Mock()
        pPr = Mock()
        pPr.find = Mock(return_value=None)
        paragraph._element = Mock()
        paragraph._element.get_or_add_pPr = Mock(return_value=pPr)

        is_ordered = loader._is_ordered_list(paragraph)

        assert is_ordered is None

    def test_load_returns_document(self):
        """Test that load returns a Document instance."""
        # This test uses a real DOCX file if available, or mocks the loading
        loader = DOCXLoader()

        # We'll mock the docx library to test the structure
        with patch("superdocs_template_inference.ingestion.docx_loader.DocxDocument") as mock_doc_class:
            mock_doc = MagicMock()
            mock_doc.element = Mock()
            mock_doc.element.body = []
            mock_doc.paragraphs = []
            mock_doc.tables = []
            mock_doc_class.return_value = mock_doc

            doc = loader.load("dummy.docx")

            assert isinstance(doc, Document)
            assert doc.filename == "dummy.docx"
            assert doc.file_type == "docx"
            assert "Z" in doc.loaded_at  # ISO 8601 with Z timezone
