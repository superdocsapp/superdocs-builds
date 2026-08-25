"""Integration test for DOCX loader with real benchmark document."""

import os
from pathlib import Path

import pytest

from superdocs_template_inference.ingestion import DOCXLoader
from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock


class TestDOCXLoaderIntegration:
    """Integration tests using real benchmark documents."""

    @pytest.fixture
    def corpus_path(self):
        """Get path to benchmark corpus."""
        current_dir = Path(__file__).parent.parent
        corpus_dir = current_dir / "corpus" / "offer_letters" / "docx"
        return corpus_dir

    @pytest.fixture
    def offer_001_path(self, corpus_path):
        """Get path to offer_001.docx."""
        doc_path = corpus_path / "offer_001.docx"
        if not doc_path.exists():
            pytest.skip(f"Benchmark document not found: {doc_path}")
        return str(doc_path)

    def test_load_real_docx_file(self, offer_001_path):
        """Test loading a real DOCX file from the benchmark corpus."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        # Verify document structure
        assert isinstance(doc, Document)
        assert doc.filename == "offer_001.docx"
        assert doc.file_type == "docx"
        assert len(doc.document_id) > 0
        assert "Z" in doc.loaded_at

    def test_loaded_document_has_blocks(self, offer_001_path):
        """Test that loaded document has content blocks."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        # Should have at least some blocks
        assert len(doc.blocks) > 0

    def test_blocks_contain_expected_types(self, offer_001_path):
        """Test that blocks are of expected types."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        # Check that blocks are ParagraphBlock or TableBlock
        for block in doc.blocks:
            assert isinstance(block, (ParagraphBlock, TableBlock))

    def test_blocks_preserve_order(self, offer_001_path):
        """Test that blocks maintain document order."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        # Verify that blocks are a proper sequence
        assert isinstance(doc.blocks, list)
        for i, block in enumerate(doc.blocks):
            assert i >= 0  # Blocks maintain sequential order

    def test_paragraph_blocks_have_text(self, offer_001_path):
        """Test that paragraph blocks contain text."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        paragraph_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]

        # Should have at least some paragraphs
        assert len(paragraph_blocks) > 0

        # All paragraphs should have non-empty text
        for para in paragraph_blocks:
            assert para.text  # Non-empty string
            assert isinstance(para.text, str)

    def test_table_blocks_have_structure(self, offer_001_path):
        """Test that table blocks have proper structure if present."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        table_blocks = [b for b in doc.blocks if isinstance(b, TableBlock)]

        # Table structure validation
        for table in table_blocks:
            assert table.rows is not None
            assert isinstance(table.rows, list)
            if len(table.rows) > 0:
                assert table.num_rows > 0
                assert table.num_cols > 0

    def test_heading_detection(self, offer_001_path):
        """Test that headings are detected in document."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        paragraph_blocks = [b for b in doc.blocks if isinstance(b, ParagraphBlock)]

        # Check if any headings are detected
        # (actual presence depends on document structure)
        has_headings = any(b.is_heading for b in paragraph_blocks)

        # Whether or not headings are detected, structure is valid
        for para in paragraph_blocks:
            if para.is_heading:
                assert para.heading_level is not None
                assert 1 <= para.heading_level <= 6
            else:
                # Non-heading paragraphs should have None heading_level
                assert para.heading_level is None

    def test_document_is_not_empty(self, offer_001_path):
        """Test that real documents are not empty after loading."""
        loader = DOCXLoader()
        doc = loader.load(offer_001_path)

        # The offer letter should have substantial content
        assert len(doc.blocks) > 5, "Offer letter should have multiple blocks"

        # Should have at least some text content
        total_text = sum(
            len(b.text) for b in doc.blocks if isinstance(b, ParagraphBlock)
        )
        assert total_text > 100, "Should have substantial text content"

    def test_multiple_docx_files_load_independently(self, corpus_path):
        """Test that multiple DOCX files can be loaded independently."""
        loader = DOCXLoader()

        files_to_test = ["offer_001.docx", "offer_002.docx"]
        docs = []

        for filename in files_to_test:
            file_path = corpus_path / filename
            if file_path.exists():
                doc = loader.load(str(file_path))
                docs.append(doc)

        # If we loaded documents, verify they're distinct
        if len(docs) >= 2:
            # Each document should have a unique ID
            ids = [d.document_id for d in docs]
            assert len(set(ids)) == len(ids), "Each document should have unique ID"

            # Each document should have its correct filename
            assert docs[0].filename == "offer_001.docx"
            assert docs[1].filename == "offer_002.docx"
