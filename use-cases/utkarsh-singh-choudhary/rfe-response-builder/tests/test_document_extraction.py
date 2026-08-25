"""
Tests for rfe_response_builder/document_extraction.py.

These tests generate REAL .pdf/.docx files (via reportlab/python-docx)
and extract text from them -- not mocked library calls -- since the
whole point of this module is correctly handling the quirks of real
file formats (encryption, missing text layers, corruption). A test that
mocks pypdf/python-docx's internals would not have caught the real
issues found while building this (e.g. exactly what exception type a
corrupted PDF raises).
"""
import pytest

from rfe_response_builder.document_extraction import DocumentExtractionError, extract_text

pytest.importorskip("pypdf")
pytest.importorskip("docx")
pytest.importorskip("reportlab")


# --- .txt --------------------------------------------------------------------

def test_extracts_txt_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("The beneficiary has ten years of experience.")
    assert extract_text(path) == "The beneficiary has ten years of experience."


def test_txt_file_with_invalid_utf8_raises_readable_error(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xfe\x00invalid utf-8 bytes")
    with pytest.raises(DocumentExtractionError, match="not valid UTF-8"):
        extract_text(path)


# --- unsupported extensions ---------------------------------------------------

def test_unsupported_extension_raises_readable_error(tmp_path):
    path = tmp_path / "notes.xyz"
    path.write_text("some content")
    with pytest.raises(DocumentExtractionError, match="Unsupported file type"):
        extract_text(path)


# --- .docx ---------------------------------------------------------------------

def _make_docx(path, paragraphs, table_rows=None):
    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table_rows:
        table = d.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for i, row in enumerate(table_rows):
            for j, cell_text in enumerate(row):
                table.cell(i, j).text = cell_text
    d.save(str(path))


def test_extracts_docx_paragraphs(tmp_path):
    path = tmp_path / "letter.docx"
    _make_docx(path, [
        "The beneficiary has published three peer-reviewed papers in robotics journals.",
        "The beneficiary also holds two patents in autonomous navigation systems.",
    ])
    text = extract_text(path)
    assert "peer-reviewed papers" in text
    assert "patents" in text


def test_extracts_docx_table_content(tmp_path):
    path = tmp_path / "letter_with_table.docx"
    _make_docx(path, ["Summary of employment history:"],
               table_rows=[["Year", "Employer"], ["2018", "Acme Robotics Corp"]])
    text = extract_text(path)
    assert "Acme Robotics Corp" in text


def test_empty_docx_raises_readable_error(tmp_path):
    path = tmp_path / "empty.docx"
    _make_docx(path, [])
    with pytest.raises(DocumentExtractionError, match="No extractable text"):
        extract_text(path)


def test_corrupted_docx_raises_readable_error(tmp_path):
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"this is not a real docx file at all")
    with pytest.raises(DocumentExtractionError, match="Could not open"):
        extract_text(path)


# --- .pdf ------------------------------------------------------------------

def _make_pdf(path, lines):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    y = 750
    for line in lines:
        c.drawString(100, y, line)
        y -= 30
    c.save()


def test_extracts_pdf_text(tmp_path):
    path = tmp_path / "letter.pdf"
    _make_pdf(path, [
        "The beneficiary has published three peer-reviewed papers in robotics.",
        "The beneficiary also holds two patents in autonomous navigation.",
    ])
    text = extract_text(path)
    assert "peer-reviewed papers" in text
    assert "patents" in text


def test_blank_pdf_raises_readable_error(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(path))
    c.showPage()
    c.save()
    with pytest.raises(DocumentExtractionError, match="No extractable text"):
        extract_text(path)


def test_corrupted_pdf_raises_readable_error(tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a real pdf at all")
    with pytest.raises(DocumentExtractionError, match="Could not open"):
        extract_text(path)


def test_password_protected_pdf_raises_readable_error(tmp_path):
    import pypdf
    source_pdf = tmp_path / "source.pdf"
    _make_pdf(source_pdf, ["Some content that would otherwise be extractable."])

    reader = pypdf.PdfReader(str(source_pdf))
    writer = pypdf.PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt(user_password="secret123")
    protected_path = tmp_path / "protected.pdf"
    with open(protected_path, "wb") as f:
        writer.write(f)

    with pytest.raises(DocumentExtractionError, match="password-protected"):
        extract_text(protected_path)


def test_multi_page_pdf_extracts_all_pages(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "multipage.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "This text is on page one.")
    c.showPage()
    c.drawString(100, 750, "This text is on page two.")
    c.save()

    text = extract_text(path)
    assert "page one" in text
    assert "page two" in text


# --- resource limits (item #8) -------------------------------------------------
# These monkeypatch the module-level limits down to small numbers rather than
# generating multi-MB fixtures -- proves the same enforcement path without
# slow tests.

def test_oversized_file_raises_readable_error(tmp_path, monkeypatch):
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_FILE_SIZE_BYTES", 10)
    path = tmp_path / "notes.txt"
    path.write_text("This is more than ten bytes of content.")
    with pytest.raises(DocumentExtractionError, match="over the .* MB limit"):
        extract_text(path)


def test_file_under_size_limit_still_extracts(tmp_path, monkeypatch):
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_FILE_SIZE_BYTES", 10_000)
    path = tmp_path / "notes.txt"
    path.write_text("Short enough.")
    assert extract_text(path) == "Short enough."


def test_pdf_over_page_limit_raises_readable_error(tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_PDF_PAGES", 1)
    path = tmp_path / "multipage.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "Page one content.")
    c.showPage()
    c.drawString(100, 750, "Page two content.")
    c.save()
    with pytest.raises(DocumentExtractionError, match="pages, over the"):
        extract_text(path)


def test_pdf_within_page_limit_still_extracts(tmp_path, monkeypatch):
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_PDF_PAGES", 5)
    path = tmp_path / "letter.pdf"
    _make_pdf(path, ["The beneficiary has published three papers."])
    assert "three papers" in extract_text(path)


def test_docx_over_paragraph_limit_raises_readable_error(tmp_path, monkeypatch):
    import docx
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_DOCX_PARAGRAPHS", 2)
    path = tmp_path / "long.docx"
    document = docx.Document()
    for i in range(5):
        document.add_paragraph(f"Paragraph number {i}.")
    document.save(str(path))
    with pytest.raises(DocumentExtractionError, match="paragraphs, over the"):
        extract_text(path)


def test_docx_over_table_cell_limit_raises_readable_error(tmp_path, monkeypatch):
    import docx
    import rfe_response_builder.document_extraction as de
    monkeypatch.setattr(de, "MAX_DOCX_TABLE_CELLS", 4)
    path = tmp_path / "tables.docx"
    document = docx.Document()
    document.add_paragraph("Intro paragraph.")
    table = document.add_table(rows=3, cols=3)  # 9 cells > limit of 4
    for row in table.rows:
        for cell in row.cells:
            cell.text = "data"
    document.save(str(path))
    with pytest.raises(DocumentExtractionError, match="table cells, over"):
        extract_text(path)
