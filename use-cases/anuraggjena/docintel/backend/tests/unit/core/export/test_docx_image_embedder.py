"""
Tests for docx_image_embedder — product image post-processing.

Covers:
  a. valid product image is embedded in the generated DOCX
  b. export still succeeds when no product image exists / bytes missing
  c. existing DOCX content remains intact after embedding
"""

import pytest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from docx import Document
from docx.shared import Inches

from backend.core.export.docx_image_embedder import embed_images_in_docx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_docx_with_product_images_section(tmp_path: Path) -> Path:
    """Create a minimal DOCX that has a 'Product Images' Heading 2."""
    doc = Document()
    doc.add_heading("Tariff Memo", level=0)
    doc.add_heading("Product Overview", level=2)
    doc.add_paragraph("Overview content.")
    doc.add_heading("Product Images", level=2)
    doc.add_paragraph("")  # blank placeholder as SuperDocs leaves
    doc.add_heading("Classification Analysis", level=2)
    doc.add_paragraph("Analysis content.")
    p = tmp_path / "memo.docx"
    doc.save(str(p))
    return p


def _make_docx_without_product_images_section(tmp_path: Path) -> Path:
    """Create a DOCX with no 'Product Images' heading."""
    doc = Document()
    doc.add_heading("Tariff Memo", level=0)
    doc.add_heading("Product Overview", level=2)
    doc.add_paragraph("Overview content.")
    p = tmp_path / "memo_no_images.docx"
    doc.save(str(p))
    return p


def _tiny_png_bytes() -> bytes:
    """Return a minimal valid 1x1 pixel white PNG."""
    import struct, zlib
    def chunk(c_type, data):
        c = c_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b'\x00\xFF\xFF\xFF'
    idat = chunk(b'IDAT', zlib.compress(raw))
    iend = chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


# ---------------------------------------------------------------------------
# Test a: valid image is embedded
# ---------------------------------------------------------------------------

def test_image_embedded_under_product_images_heading(tmp_path):
    """
    Given a DOCX with a 'Product Images' heading and a valid PNG,
    embed_images_in_docx must embed the image and return True.
    The resulting DOCX must contain exactly one inline shape (the image).
    """
    docx_path = _make_docx_with_product_images_section(tmp_path)
    png = _tiny_png_bytes()

    result = embed_images_in_docx(
        str(docx_path),
        images=[{"bytes": png, "filename": "product_image.png"}],
    )

    assert result is True

    doc = Document(str(docx_path))
    assert len(doc.inline_shapes) == 1, "Expected exactly 1 embedded image"


def test_image_appears_after_product_images_heading(tmp_path):
    """
    The image paragraph must appear immediately after the 'Product Images'
    heading, not at the end of the document.
    """
    docx_path = _make_docx_with_product_images_section(tmp_path)
    png = _tiny_png_bytes()

    embed_images_in_docx(str(docx_path), [{"bytes": png, "filename": "img.png"}])

    doc = Document(str(docx_path))
    heading_idx = next(
        i for i, p in enumerate(doc.paragraphs)
        if p.style.name.startswith("Heading") and p.text.strip() == "Product Images"
    )
    # Within the next few paragraphs there must be an inline shape
    nearby_xml = "".join(
        p._element.xml for p in doc.paragraphs[heading_idx : heading_idx + 5]
    )
    assert "pic:pic" in nearby_xml, "Image XML not found near Product Images heading"


# ---------------------------------------------------------------------------
# Test b: graceful no-op when images are absent or bytes missing
# ---------------------------------------------------------------------------

def test_no_images_returns_false(tmp_path):
    """embed_images_in_docx with empty images list returns False and leaves DOCX unchanged."""
    docx_path = _make_docx_with_product_images_section(tmp_path)
    before = docx_path.read_bytes()

    result = embed_images_in_docx(str(docx_path), images=[])

    assert result is False
    assert docx_path.read_bytes() == before, "DOCX must not be modified when no images given"


def test_missing_bytes_skipped_gracefully(tmp_path):
    """If bytes key is None/missing, image is skipped; embed_images_in_docx returns False."""
    docx_path = _make_docx_with_product_images_section(tmp_path)

    result = embed_images_in_docx(
        str(docx_path),
        images=[{"bytes": None, "filename": "product.png"}],
    )

    assert result is False
    doc = Document(str(docx_path))
    assert len(doc.inline_shapes) == 0


def test_no_product_images_heading_returns_false(tmp_path):
    """If DOCX has no 'Product Images' heading, returns False without crashing."""
    docx_path = _make_docx_without_product_images_section(tmp_path)
    png = _tiny_png_bytes()

    result = embed_images_in_docx(str(docx_path), [{"bytes": png, "filename": "img.png"}])

    assert result is False


def test_nonexistent_docx_returns_false(tmp_path):
    """If the DOCX path does not exist, returns False without raising."""
    result = embed_images_in_docx(
        str(tmp_path / "does_not_exist.docx"),
        [{"bytes": b"x", "filename": "img.png"}],
    )
    assert result is False


# ---------------------------------------------------------------------------
# Test c: existing content intact after embedding
# ---------------------------------------------------------------------------

def test_existing_content_preserved(tmp_path):
    """
    After embedding, all headings and paragraphs that were in the original
    DOCX must still be present.
    """
    docx_path = _make_docx_with_product_images_section(tmp_path)
    png = _tiny_png_bytes()

    embed_images_in_docx(str(docx_path), [{"bytes": png, "filename": "img.png"}])

    doc = Document(str(docx_path))
    texts = [p.text.strip() for p in doc.paragraphs]

    assert "Product Overview" in texts
    assert "Overview content." in texts
    assert "Product Images" in texts
    assert "Classification Analysis" in texts
    assert "Analysis content." in texts


# ---------------------------------------------------------------------------
# Test: SuperDocsExportStage.execute embeds images after download
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_stage_embeds_images(tmp_path):
    """
    SuperDocsExportStage.execute must call embed_images_in_docx when
    image_document_ids are present and a DOCX export is stored locally.
    """
    from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
    from backend.modules.tariff.schemas import TariffWorkflowState

    # Create a real DOCX with "Product Images" heading for the mock to reference
    docx_path = _make_docx_with_product_images_section(tmp_path)
    png = _tiny_png_bytes()

    # Mock export record
    mock_export = MagicMock()
    mock_export.id = uuid4()
    mock_export.format = "docx"
    mock_export.storage_path = str(docx_path)

    class LegacyExportService:
        def __init__(self):
            self.export_run = AsyncMock(return_value=mock_export)

    mock_export_service = LegacyExportService()

    # Mock document repo
    mock_doc = MagicMock()
    mock_doc.filename = "product_image.png"
    mock_doc.storage_path = "ws/product_image.png"
    mock_doc_repo = AsyncMock()
    mock_doc_repo.get_by_id = AsyncMock(return_value=mock_doc)

    # Mock storage
    mock_storage = MagicMock()
    mock_storage.read = MagicMock(return_value=png)

    stage = SuperDocsExportStage(
        export_service=mock_export_service,
        document_repository=mock_doc_repo,
        storage_backend=mock_storage,
    )

    doc_id = str(uuid4())
    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_id=str(uuid4()),
        superdocs_session_id="sess-123",
        image_document_ids=[doc_id],
    )

    result = await stage.execute(state)

    assert result["export_completed"] is True
    mock_doc_repo.get_by_id.assert_called_once()
    mock_storage.read.assert_called_once_with("ws/product_image.png")

    # Verify the DOCX now contains the image
    doc = Document(str(docx_path))
    assert len(doc.inline_shapes) == 1, "Image must be embedded in DOCX after stage.execute"


@pytest.mark.asyncio
async def test_export_stage_succeeds_without_images():
    """
    SuperDocsExportStage.execute must succeed when image_document_ids is empty,
    with no call to document_repository.
    """
    from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
    from backend.modules.tariff.schemas import TariffWorkflowState

    mock_export = MagicMock()
    mock_export.id = uuid4()
    mock_export.format = "docx"
    mock_export.storage_path = "/tmp/nonexistent.docx"

    mock_export_service = AsyncMock()
    mock_export_service.export_run = AsyncMock(return_value=mock_export)
    mock_doc_repo = AsyncMock()
    mock_storage = MagicMock()

    stage = SuperDocsExportStage(
        export_service=mock_export_service,
        document_repository=mock_doc_repo,
        storage_backend=mock_storage,
    )

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_id=str(uuid4()),
        superdocs_session_id="sess-456",
        image_document_ids=[],  # no images
    )

    result = await stage.execute(state)

    assert result["export_completed"] is True
    mock_doc_repo.get_by_id.assert_not_called()
    mock_storage.read.assert_not_called()


@pytest.mark.asyncio
async def test_export_stage_image_load_failure_does_not_fail_export(tmp_path):
    """
    If loading image bytes raises an exception, the export must still succeed.
    """
    from backend.modules.tariff.stages.superdocs_export import SuperDocsExportStage
    from backend.modules.tariff.schemas import TariffWorkflowState

    docx_path = _make_docx_with_product_images_section(tmp_path)

    mock_export = MagicMock()
    mock_export.id = uuid4()
    mock_export.format = "docx"
    mock_export.storage_path = str(docx_path)

    mock_export_service = AsyncMock()
    mock_export_service.export_run = AsyncMock(return_value=mock_export)

    mock_doc_repo = AsyncMock()
    mock_doc_repo.get_by_id = AsyncMock(side_effect=Exception("DB connection lost"))
    mock_storage = MagicMock()

    stage = SuperDocsExportStage(
        export_service=mock_export_service,
        document_repository=mock_doc_repo,
        storage_backend=mock_storage,
    )

    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_id=str(uuid4()),
        superdocs_session_id="sess-789",
        image_document_ids=[str(uuid4())],
    )

    result = await stage.execute(state)

    assert result["export_completed"] is True, "Export must succeed even if image loading fails"
