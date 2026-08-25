"""Tests for DOCX generator"""
import pytest
from io import BytesIO
from docx import Document

from backend.core.export.docx_generator import DOCXGenerator


class TestDOCXGenerator:
    """Test DOCX generator functionality"""

    def test_init_creates_document(self):
        """Test that initialization creates a document"""
        generator = DOCXGenerator()
        assert generator.document is not None
        # Check that document has the expected attributes
        assert hasattr(generator.document, 'paragraphs')
        assert hasattr(generator.document, 'tables')

    def test_add_title(self):
        """Test adding title to document"""
        generator = DOCXGenerator()
        generator.add_title("Test Title")

        # Title should be a heading level 0
        assert len(generator.document.paragraphs) > 0
        # Check that title was added
        paragraphs = generator.document.paragraphs
        assert any("Test Title" in p.text for p in paragraphs)

    def test_add_heading(self):
        """Test adding heading to document"""
        generator = DOCXGenerator()
        generator.add_heading("Section 1", level=1)
        generator.add_heading("Subsection 1.1", level=2)

        paragraphs = generator.document.paragraphs
        assert any("Section 1" in p.text for p in paragraphs)
        assert any("Subsection 1.1" in p.text for p in paragraphs)

    def test_add_paragraph(self):
        """Test adding paragraph to document"""
        generator = DOCXGenerator()
        generator.add_paragraph("This is a test paragraph.")

        paragraphs = generator.document.paragraphs
        assert any("This is a test paragraph." in p.text for p in paragraphs)

    def test_add_paragraph_with_formatting(self):
        """Test adding formatted paragraph"""
        generator = DOCXGenerator()
        generator.add_paragraph("Bold text", bold=True)
        generator.add_paragraph("Italic text", italic=True)

        # Verify paragraphs were added
        paragraphs = generator.document.paragraphs
        assert any("Bold text" in p.text for p in paragraphs)
        assert any("Italic text" in p.text for p in paragraphs)

    def test_add_table(self):
        """Test adding table to document"""
        generator = DOCXGenerator()
        headers = ["Column 1", "Column 2", "Column 3"]
        rows = [
            ["Row 1 Col 1", "Row 1 Col 2", "Row 1 Col 3"],
            ["Row 2 Col 1", "Row 2 Col 2", "Row 2 Col 3"],
        ]

        generator.add_table(headers, rows)

        # Check table was added
        tables = generator.document.tables
        assert len(tables) == 1
        table = tables[0]

        # Check dimensions
        assert len(table.rows) == 3  # 1 header + 2 data rows
        assert len(table.columns) == 3

        # Check header content
        header_row = table.rows[0]
        assert header_row.cells[0].text == "Column 1"
        assert header_row.cells[1].text == "Column 2"
        assert header_row.cells[2].text == "Column 3"

        # Check data content
        data_row_1 = table.rows[1]
        assert data_row_1.cells[0].text == "Row 1 Col 1"

    def test_add_key_value_pair(self):
        """Test adding key-value pair"""
        generator = DOCXGenerator()
        generator.add_key_value_pair("Name", "John Doe")
        generator.add_key_value_pair("Email", "john@example.com")

        paragraphs = generator.document.paragraphs
        paragraph_texts = [p.text for p in paragraphs]

        assert any("Name: John Doe" in text for text in paragraph_texts)
        assert any("Email: john@example.com" in text for text in paragraph_texts)

    def test_add_page_break(self):
        """Test adding page break"""
        generator = DOCXGenerator()
        generator.add_paragraph("Page 1")
        generator.add_page_break()
        generator.add_paragraph("Page 2")

        # Page breaks are added as runs within paragraphs
        # Just verify no errors occurred
        assert len(generator.document.paragraphs) >= 2

    def test_generate_tariff_report(self):
        """Test generating complete tariff report"""
        generator = DOCXGenerator()

        workspace_name = "Test Workspace"
        document_name = "Import Document.pdf"
        claims = [
            {
                "content": '{"hs_code": "8471.30", "description": "Portable computers", "duty_rate": "0%"}',
                "status": "approved"
            },
            {
                "content": '{"hs_code": "8471.41", "description": "Data processing machines", "duty_rate": "0%"}',
                "status": "pending"
            }
        ]
        generated_report = "This is a detailed analysis of the tariff classifications.\n\nEach product has been carefully reviewed."

        docx_bytes = generator.generate_tariff_report(
            workspace_name,
            document_name,
            claims,
            generated_report
        )

        # Verify bytes were generated
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0

        # Verify it's a valid DOCX file by loading it
        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)

        # Check document has content
        assert len(doc.paragraphs) > 0

        # Check for expected content
        all_text = "\n".join([p.text for p in doc.paragraphs])
        assert "Tariff Classification Report" in all_text
        assert workspace_name in all_text
        assert document_name in all_text
        assert "Executive Summary" in all_text
        assert "Tariff Classifications" in all_text
        assert "Detailed Analysis" in all_text

        # Check table exists
        assert len(doc.tables) > 0
        table = doc.tables[0]
        # Should have header + 2 data rows
        assert len(table.rows) == 3

    def test_generate_tariff_memo(self):
        """Test generating structured tariff memo DOCX"""
        generator = DOCXGenerator()
        sections = [
            {
                "title": "Product Overview",
                "section_order": 2,
                "content": "Widget overview content",
                "analyst_reasoning": "Based on spec sheet",
                "source_attribution": [],
                "structured_data": None,
                "status": "pending",
            },
            {
                "title": "Recommended Classification",
                "section_order": 12,
                "content": "HS 7326.90 recommended",
                "analyst_reasoning": "Essential character analysis",
                "structured_data": {"recommendation": {"hs_code": "7326.90", "description": "Steel articles"}},
                "status": "pending",
            },
        ]
        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test WS",
            document_name="spec.pdf",
            sections=sections,
        )
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0
        doc = Document(BytesIO(docx_bytes))
        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])
        assert "Tariff Classification Memo" in all_text
        assert "Product Overview" in all_text
        assert "7326.90" in all_text

    def test_generate_tariff_report_empty_claims(self):
        """Test generating report with no claims"""
        generator = DOCXGenerator()

        docx_bytes = generator.generate_tariff_report(
            workspace_name="Test Workspace",
            document_name="Document.pdf",
            claims=[],
            generated_report="No classifications found."
        )

        # Verify bytes were generated
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0

        # Verify it's valid
        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs])

        assert "No classifications found" in all_text

    def test_generate_tariff_report_with_invalid_claim_content(self):
        """Test generating report with invalid JSON in claims"""
        generator = DOCXGenerator()

        claims = [
            {
                "content": "invalid json",
                "status": "pending"
            }
        ]

        # Should not raise an error, should handle gracefully
        docx_bytes = generator.generate_tariff_report(
            workspace_name="Test Workspace",
            document_name="Document.pdf",
            claims=claims,
            generated_report=""
        )

        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0

        # Check that N/A values are used
        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        table = doc.tables[0]
        # Should have N/A for invalid content
        cell_text = table.rows[1].cells[0].text
        assert cell_text == "N/A"
