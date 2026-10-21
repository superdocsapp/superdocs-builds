"""
Integration test for complete Tariff export flow.

Tests the actual DOCX file generation end-to-end:
- MemoSection records
- Product image storage/retrieval
- DOCX structure validation
- Image embedding in word/media
"""

import pytest
import pytest_asyncio
from uuid import uuid4
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document

from backend.services.export import ExportService
from backend.repositories.export import ExportRepository
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.document import DocumentRepository
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.repositories.memo_section import MemoSectionRepository
from backend.storage.local import LocalStorageBackend
from backend.models.workspace import Workspace
from backend.models.workflow import WorkflowRun
from backend.models.memo_section import MemoSection
from backend.models.document import Document as DocumentModel
from backend.config import settings


@pytest_asyncio.fixture
async def integration_workspace(db_session, test_user):
    """Create a real workspace for integration testing."""
    from backend.repositories.workspace import WorkspaceRepository

    workspace_repo = WorkspaceRepository(db_session)
    workspace = await workspace_repo.create(
        name="Integration Test Workspace",
        owner_id=test_user.id,
    )
    yield workspace

    # Cleanup
    await db_session.delete(workspace)
    await db_session.commit()


@pytest_asyncio.fixture
async def integration_run(db_session, integration_workspace):
    """Create a completed workflow run."""
    from backend.repositories.workflow import WorkflowRepository, WorkflowRunRepository

    workflow_repo = WorkflowRepository(db_session)
    workflow = await workflow_repo.get_by_slug("tariff_classification")
    if not workflow:
        workflow = await workflow_repo.create(
            name="Tariff Classification",
            slug="tariff_classification",
            current_version="1.0.0",
        )

    run_repo = WorkflowRunRepository(db_session)
    run = await run_repo.create(
        workspace_id=integration_workspace.id,
        workflow_id=workflow.id,
        workflow_version="1.0.0",
        created_by="test-user",
        status="completed",
    )
    yield run

    # Cleanup
    from sqlalchemy import delete
    from backend.models.export import Export
    await db_session.execute(delete(Export).where(Export.workflow_run_id == run.id))
    await db_session.commit()
    await db_session.delete(run)
    await db_session.commit()


@pytest_asyncio.fixture
async def integration_memo_sections(db_session, integration_run):
    """Create real MemoSection records."""
    from backend.repositories.memo_section import MemoSectionRepository

    section_repo = MemoSectionRepository(db_session)

    sections = []

    # Product Description section
    section1 = await section_repo.create(
        workflow_run_id=integration_run.id,
        section_type="product_description",
        title="Product Description",
        section_order=1,
        content="This is an aluminum storage container measuring 10x10x10 cm.\nIt is designed for industrial use.",
        analyst_reasoning="Based on product specification document.",
        source_attribution=[
            {
                "document_id": str(uuid4()),
                "document_name": "product_spec.pdf",
                "page": 5,
                "excerpt": "Material: aluminum alloy"
            }
        ],
        status="completed",
    )
    sections.append(section1)

    # Recommended Classification section
    section2 = await section_repo.create(
        workflow_run_id=integration_run.id,
        section_type="recommended_classification",
        title="Recommended Classification",
        section_order=2,
        content="The recommended classification is based on material composition and intended use.",
        analyst_reasoning="Analysis of product characteristics and relevant rulings.",
        source_attribution=[],
        structured_data={
            "recommendation": {
                "hs_code": "7326.90.8588",
                "description": "Other articles of iron or steel",
                "reasoning": "Aluminum construction for storage purposes matches this category based on GRI 1 and Note 3.",
                "duty_rate": "2.9%",
            }
        },
        status="completed",
    )
    sections.append(section2)

    # Product Images section (conditional)
    section3 = await section_repo.create(
        workflow_run_id=integration_run.id,
        section_type="product_images",
        title="Product Images",
        section_order=3,
        content="Product images are provided below.",
        status="completed",
    )
    sections.append(section3)

    yield sections

    # Cleanup
    for section in sections:
        await db_session.delete(section)
    await db_session.commit()


@pytest_asyncio.fixture
async def integration_product_image(db_session, integration_workspace):
    """Create a product image document with actual image bytes in storage."""
    from backend.repositories.document import DocumentRepository

    # Create a minimal valid PNG (1x1 pixel red)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
        b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x8e\x1c\xe6\x82"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    # Save to storage
    storage = LocalStorageBackend(settings.storage_path)
    storage_path = storage.save(png_bytes, "test_product.png", str(integration_workspace.id))

    # Create document record
    doc_repo = DocumentRepository(db_session)
    doc = await doc_repo.create(
        workspace_id=integration_workspace.id,
        filename="test_product.png",
        mime_type="image/png",
        checksum="png_checksum_123",
        storage_path=storage_path,
        document_role="product_image",
    )

    yield doc

    # Cleanup
    try:
        # Delete from storage
        Path(storage_path).unlink(missing_ok=True)
    except Exception:
        pass

    await db_session.delete(doc)
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_complete_tariff_export_flow(
    db_session,
    integration_workspace,
    integration_run,
    integration_memo_sections,
    integration_product_image,
):
    """
    Integration test: Complete export flow from MemoSections to DOCX with images.

    Tests:
    - MemoSection retrieval
    - Image loading from storage
    - DOCX generation
    - Image embedding in word/media
    - No legacy content
    """
    # Setup export service with all dependencies
    storage = LocalStorageBackend(settings.storage_path)
    export_service = ExportService(
        export_repository=ExportRepository(db_session),
        review_repository=ReviewRepository(db_session),
        claim_repository=ClaimRepository(db_session),
        workspace_repository=WorkspaceRepository(db_session),
        document_repository=DocumentRepository(db_session),
        run_repository=WorkflowRunRepository(db_session),
        stage_repository=WorkflowStageRepository(db_session),
        storage=storage,
        memo_section_repository=MemoSectionRepository(db_session),
    )

    # Export the run with image
    export = await export_service.export_run_as_docx(
        run_id=integration_run.id,
        workspace_id=integration_workspace.id,
        document_ids=[str(integration_product_image.id)],
    )

    # Verify export record created
    assert export is not None
    assert export.workflow_run_id == integration_run.id
    assert export.format == "docx"
    assert export.file_size > 0

    # Read the exported DOCX
    docx_bytes = storage.read(export.storage_path)
    assert len(docx_bytes) > 0

    # Load as python-docx Document
    buffer = BytesIO(docx_bytes)
    doc = Document(buffer)

    # Verify document structure
    all_text = "\n".join([p.text for p in doc.paragraphs])

    # 1. Check for memo title
    assert "Tariff Classification Memo" in all_text

    # 2. Check for section titles
    assert "Product Description" in all_text
    assert "Recommended Classification" in all_text
    assert "Product Images" in all_text

    # 3. Check for section content
    assert "aluminum storage container" in all_text
    assert "10x10x10 cm" in all_text

    # 4. Check for analyst reasoning
    assert "Analyst Reasoning" in all_text
    assert "product specification document" in all_text

    # 5. Check for source attribution with metadata
    assert "Sources" in all_text
    assert "product_spec.pdf" in all_text
    assert "Page: 5" in all_text
    assert "Material: aluminum alloy" in all_text

    # 6. Check for recommendation
    assert "HS Code: 7326.90.8588" in all_text
    assert "Other articles of iron or steel" in all_text
    assert "Duty Rate: 2.9%" in all_text
    assert "Reasoning:" in all_text

    # 7. Check for image caption
    assert "test_product.png" in all_text

    # 8. Verify NO legacy content
    assert "No classifications found" not in all_text
    assert "0 product" not in all_text

    # 9. Check for embedded images in DOCX structure
    # Open DOCX as ZIP to inspect word/media
    buffer.seek(0)
    with ZipFile(buffer, 'r') as docx_zip:
        # List all files
        file_list = docx_zip.namelist()

        # Check for media folder and images
        media_files = [f for f in file_list if f.startswith("word/media/")]
        assert len(media_files) > 0, "No images found in word/media/"

        # Check for image file (usually image1.png or similar)
        image_files = [f for f in media_files if "image" in f and (".png" in f or ".jpg" in f or ".jpeg" in f)]
        assert len(image_files) > 0, "No PNG/JPEG images found in word/media/"

        # Verify image relationship exists
        rels_files = [f for f in file_list if "rels" in f]
        assert len(rels_files) > 0, "No relationship files found"

    # Cleanup export file
    try:
        Path(export.storage_path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.mark.asyncio
@pytest.mark.integration
async def test_export_with_missing_image_graceful_failure(
    db_session,
    integration_workspace,
    integration_run,
    integration_memo_sections,
):
    """Test export continues when image file is missing from storage."""
    from backend.repositories.document import DocumentRepository

    # Create document record WITHOUT actual file in storage
    doc_repo = DocumentRepository(db_session)
    doc = await doc_repo.create(
        workspace_id=integration_workspace.id,
        filename="missing_image.png",
        mime_type="image/png",
        checksum="missing_png_checksum",
        storage_path="nonexistent/path/missing_image.png",
        document_role="product_image",
    )

    storage = LocalStorageBackend(settings.storage_path)
    export_service = ExportService(
        export_repository=ExportRepository(db_session),
        review_repository=ReviewRepository(db_session),
        claim_repository=ClaimRepository(db_session),
        workspace_repository=WorkspaceRepository(db_session),
        document_repository=DocumentRepository(db_session),
        run_repository=WorkflowRunRepository(db_session),
        stage_repository=WorkflowStageRepository(db_session),
        storage=storage,
        memo_section_repository=MemoSectionRepository(db_session),
    )

    # Export should succeed despite missing image
    export = await export_service.export_run_as_docx(
        run_id=integration_run.id,
        workspace_id=integration_workspace.id,
        document_ids=[str(doc.id)],
    )

    # Verify export created
    assert export is not None

    # Read DOCX
    docx_bytes = storage.read(export.storage_path)
    buffer = BytesIO(docx_bytes)
    doc_obj = Document(buffer)
    all_text = "\n".join([p.text for p in doc_obj.paragraphs])

    # Check for fallback message
    assert "[Image unavailable: missing_image.png]" in all_text

    # Verify other content still present
    assert "Product Description" in all_text
    assert "aluminum storage container" in all_text

    # Cleanup
    try:
        Path(export.storage_path).unlink(missing_ok=True)
    except Exception:
        pass

    await db_session.delete(doc)
    await db_session.commit()
