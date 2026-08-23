import io

from docx import Document

from app.models import DocClass, ExtractedFields
from app.workflow.companion_doc import render_companion_docx


def _open(docx_bytes: bytes) -> Document:
    return Document(io.BytesIO(docx_bytes))


def test_renders_a_valid_docx_with_populated_fields():
    extracted = ExtractedFields(
        doc_class=DocClass.CONTRACT,
        doc_class_confidence=0.97,
        counterparty_name="Acme Logistics Inc",
        effective_date="2026-01-15",
        contract_value="$84,000",
        field_confidence={"counterparty_name": 0.92, "contract_value": 0.55},
    )
    docx_bytes = render_companion_docx(
        extracted, "Body content here.", source_filename="acme-msa.pdf", generated_at_iso="2026-08-21T00:00:00Z"
    )
    assert docx_bytes.startswith(b"PK")  # a docx is a zip archive
    doc = _open(docx_bytes)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Companion Document" in full_text
    assert "acme-msa.pdf" in full_text
    assert "Body content here." in full_text

    # table has the extracted values, not raw None/blank
    table_text = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    assert "Acme Logistics Inc" in table_text
    assert "0.92" in table_text


def test_unstated_fields_are_labeled_not_stated_never_blank():
    extracted = ExtractedFields(doc_class=DocClass.CONTRACT)  # everything else None
    docx_bytes = render_companion_docx(extracted, "", source_filename="doc.pdf")
    doc = _open(docx_bytes)
    table_text = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
    assert "Not stated in source" in table_text


def test_empty_companion_text_does_not_crash_and_says_so():
    extracted = ExtractedFields(doc_class=DocClass.CONTRACT)
    docx_bytes = render_companion_docx(extracted, "   ", source_filename="doc.pdf")
    doc = _open(docx_bytes)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "no companion content" in full_text.lower()


def test_extraction_notes_included_when_present():
    extracted = ExtractedFields(doc_class=DocClass.CONTRACT, extraction_notes="source did not support: expiration_date. ")
    docx_bytes = render_companion_docx(extracted, "body", source_filename="doc.pdf")
    doc = _open(docx_bytes)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "source did not support: expiration_date" in full_text


def test_governance_footer_always_present():
    extracted = ExtractedFields(doc_class=DocClass.CONTRACT)
    docx_bytes = render_companion_docx(extracted, "body", source_filename="doc.pdf")
    doc = _open(docx_bytes)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "not overridden" in full_text.lower()
