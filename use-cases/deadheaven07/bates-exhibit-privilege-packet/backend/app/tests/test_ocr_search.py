"""Tests proving scanned/image documents with text become searchable
via the search endpoint after processing (and non-searchable when no text exists).
"""

from io import BytesIO
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw
import pytest

from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_assignment import BatesAssignmentService
from app.workers.processor import process_document


def _create_image_with_text(text: str) -> bytes:
    """Create a PNG image with rendered text."""
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 50), text, fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_image_pdf_with_text(text: str) -> bytes:
    """Create a single-page PDF containing a rendered image with text (simulating a scanned PDF)."""
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 50), text, fill="black")
    img_buf = BytesIO()
    img.save(img_buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_image(page.rect, stream=img_buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_scanned_pdf_becomes_searchable_after_processing(api_client, test_session):
    client = api_client
    session = test_session

    # 1. Create a packet
    packet = Packet(
        name="Scanned Search QA Packet",
        bates_prefix="SCAN-",
        bates_start_number=1,
        bates_padding=4,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)

    seeded_term = "CONFIDENTIAL_PATIENT_RECORD_XYZ99"
    scanned_pdf_bytes = _create_image_pdf_with_text(seeded_term)

    # 2. Upload the scanned PDF
    files = {"files": ("medical_scan_01.pdf", scanned_pdf_bytes, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet.id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    doc_data = resp.json()["documents"][0]
    doc_id = doc_data["id"]

    # 3. Simulate/Run processor with OCR extracting the seeded text
    with patch("pytesseract.image_to_string", return_value=f"Page 1: {seeded_term}"):
        await process_document(doc_id)

    # 4. Verify document state in database
    doc = await session.get(Document, doc_id)
    assert doc is not None
    assert doc.is_searchable is True
    assert doc.processing_status == ProcessingStatus.COMPLETED

    # 5. Search via the search endpoint
    search_resp = await client.get(f"/api/search/{packet.id}?q=XYZ99")
    assert search_resp.status_code == 200, search_resp.text
    search_results = search_resp.json()["results"]

    assert len(search_results) >= 1
    matched_doc = next(r for r in search_results if r["document_id"] == str(doc_id))
    assert "content" in matched_doc["matched_fields"]
    assert len(matched_doc["snippets"]) >= 1
    snippet_info = matched_doc["snippets"][0]
    assert "XYZ99" in snippet_info["snippet"]
    assert snippet_info["bates_label"] == "SCAN-0001"


@pytest.mark.asyncio
async def test_scanned_pdf_without_ocr_marked_non_searchable(api_client, test_session):
    client = api_client
    session = test_session

    packet = Packet(
        name="Empty Scan QA Packet",
        bates_prefix="BLANK-",
        bates_start_number=1,
        bates_padding=4,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)

    blank_pdf = _create_image_pdf_with_text("")

    files = {"files": ("blank_scan.pdf", blank_pdf, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet.id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["documents"][0]["id"]

    # Simulate OCR returning empty text (e.g. blank page or OCR missing)
    with patch("pytesseract.image_to_string", return_value=""):
        await process_document(doc_id)

    doc = await session.get(Document, doc_id)
    assert doc is not None
    assert doc.is_searchable is False

    # Search should not find any content matches
    search_resp = await client.get(f"/api/search/{packet.id}?q=UNMATCHABLE_KEYWORD_123")
    assert search_resp.status_code == 200
    assert len(search_resp.json()["results"]) == 0
