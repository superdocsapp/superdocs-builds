import pytest
from unittest.mock import MagicMock, patch
import docx
import openpyxl

from backend.app.services.parsing import extract_document_text
from backend.app.exceptions import UnsupportedFileError

def test_parse_txt():
    content = "Hello, startup diligence data room!"
    segments = extract_document_text("diligence.txt", content.encode("utf-8"))
    assert len(segments) == 1
    assert segments[0].content == content
    assert segments[0].page_number is None
    assert segments[0].section is None

def test_parse_pdf_mocked():
    with patch("pypdf.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        mock_page_1 = MagicMock()
        mock_page_1.extract_text.return_value = "Page 1 content: Revenue ARR"
        mock_page_2 = MagicMock()
        mock_page_2.extract_text.return_value = "Page 2 content: Churn Rate 5%"
        mock_reader.pages = [mock_page_1, mock_page_2]
        mock_reader_cls.return_value = mock_reader

        segments = extract_document_text("diligence.pdf", b"%PDF-1.4 dummy header")
        assert len(segments) == 2
        assert segments[0].content == "Page 1 content: Revenue ARR"
        assert segments[0].page_number == 1
        assert segments[1].content == "Page 2 content: Churn Rate 5%"
        assert segments[1].page_number == 2

def test_parse_docx(tmp_path):
    doc_path = tmp_path / "test.docx"
    doc = docx.Document()
    doc.add_heading("Cap Table & IP Assignment", level=1)
    doc.add_paragraph("Founder owns 60% shares. All IP is assigned to the company.")
    
    # Add a table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Shareholder"
    table.cell(0, 1).text = "Percentage"
    table.cell(1, 0).text = "Alice"
    table.cell(1, 1).text = "40%"
    
    doc.save(str(doc_path))

    with open(doc_path, "rb") as f:
        file_bytes = f.read()

    segments = extract_document_text("diligence.docx", file_bytes)
    assert len(segments) >= 2
    
    # Verify paragraph parsing and section assignment
    p_segment = next(s for s in segments if "Founder owns" in s.content)
    assert p_segment.section == "Cap Table & IP Assignment"
    
    # Verify table parsing
    t_segment = next(s for s in segments if "Alice | 40%" in s.content)
    assert t_segment.section == "Cap Table & IP Assignment"

def test_parse_xlsx(tmp_path):
    xls_path = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ARR Churn Data"
    ws.append(["Year", "ARR", "Churn"])
    ws.append(["2025", "$2.5M", "4.5%"])
    wb.save(str(xls_path))

    with open(xls_path, "rb") as f:
        file_bytes = f.read()

    segments = extract_document_text("diligence.xlsx", file_bytes)
    assert len(segments) == 1
    assert "ARR Churn Data" in segments[0].section
    assert "Year | ARR | Churn" in segments[0].content
    assert "2025 | $2.5M | 4.5%" in segments[0].content

def test_unsupported_xls():
    with pytest.raises(UnsupportedFileError) as exc_info:
        extract_document_text("diligence.xls", b"legacy binary xls")
    assert "Legacy Excel format (.xls) is not supported" in str(exc_info.value)

def test_unsupported_extension():
    with pytest.raises(UnsupportedFileError) as exc_info:
        extract_document_text("cap_table.png", b"binary png bytes")
    assert "Unsupported file format" in str(exc_info.value)
