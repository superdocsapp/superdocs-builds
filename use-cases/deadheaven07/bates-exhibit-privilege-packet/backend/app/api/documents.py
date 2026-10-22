import hashlib
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, DocumentType
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_assignment import BatesAssignmentService
from app.services.ingestion import FileValidationError, IngestionService
from app.services.storage import (
    cleanup_document_files,
    cleanup_unreferenced_original,
    original_path_for,
)

router = APIRouter()


class ReorderDocumentRequest(BaseModel):
    new_order: int


@router.post("/{packet_id}/upload")
async def upload_documents(
    packet_id: UUID,
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    ingestion_service = IngestionService()
    uploaded_documents = []
    created_documents = []

    try:
        for upload_file in files:
            filename = upload_file.filename or "unnamed"
            display_order = await packet.next_display_order(session)

            file_content = await upload_file.read()
            file_stream = BytesIO(file_content)

            try:
                session.add(
                    AuditEvent(
                        packet_id=packet_id,
                        event_type=AuditEventType.PROCESSING_STARTED,
                        user_id="system",
                        event_metadata={"filename": filename},
                    )
                )
                result = await ingestion_service.ingest_file(
                    file=file_stream,
                    original_filename=filename,
                    packet_id=str(packet_id),
                    display_order=display_order,
                )
            except FileValidationError as e:
                sha = hashlib.sha256(file_content).hexdigest()
                await cleanup_unreferenced_original(session, sha, filename)
                raise HTTPException(status_code=400, detail=str(e)) from e

            existing = await session.execute(
                select(Document.id).where(
                    Document.packet_id == packet_id,
                    Document.sha256 == result.document.sha256,
                )
            )
            if existing.first() is not None:
                await cleanup_document_files(session, result.document)
                raise HTTPException(
                    status_code=409,
                    detail=f"Duplicate document: {filename} already exists in this packet",
                )

            session.add(result.document)
            await session.flush()
            created_documents.append(result.document)

            per_page_texts: list[str] = []
            if result.is_searchable and result.document.document_type in (
                DocumentType.PDF,
                DocumentType.SCANNED_PDF,
            ):
                try:
                    import fitz

                    orig_path = original_path_for(result.document)
                    if orig_path.exists():
                        doc = fitz.open(orig_path)
                        for p in doc:
                            per_page_texts.append(p.get_text())
                        doc.close()
                except Exception:
                    pass

            for page_num in range(1, result.page_count + 1):
                page_idx = page_num - 1
                page_text = (
                    per_page_texts[page_idx]
                    if page_idx < len(per_page_texts) and per_page_texts[page_idx].strip()
                    else (result.extracted_text if result.page_count == 1 else None)
                )
                page = Page(
                    document_id=result.document.id,
                    page_number=page_num,
                    has_text=result.is_searchable and bool(page_text and page_text.strip()),
                    extracted_text=page_text[:1000000] if page_text else None,
                )
                session.add(page)

            session.add(
                AuditEvent(
                    packet_id=packet_id,
                    document_id=result.document.id,
                    event_type=AuditEventType.UPLOAD,
                    user_id="system",
                    event_metadata={
                        "filename": filename,
                        "document_type": result.document.document_type.value,
                        "page_count": result.document.page_count,
                    },
                )
            )

            session.add(
                AuditEvent(
                    packet_id=packet_id,
                    document_id=result.document.id,
                    event_type=AuditEventType.PROCESSING_COMPLETED,
                    user_id="system",
                    event_metadata={
                        "filename": filename,
                        "page_count": result.document.page_count,
                        "is_searchable": result.is_searchable,
                    },
                )
            )

            uploaded_documents.append(
                {
                    "id": str(result.document.id),
                    "filename": result.document.original_filename,
                    "document_type": result.document.document_type.value,
                    "page_count": result.document.page_count,
                    "status": result.document.processing_status.value,
                    "is_searchable": result.is_searchable,
                }
            )

    except FileValidationError as e:
        await _rollback_upload(session, created_documents)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        await _rollback_upload(session, created_documents)
        raise
    except Exception as e:
        await _rollback_upload(session, created_documents)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}") from e

    await session.commit()

    if uploaded_documents:
        assignments = await BatesAssignmentService().assign_bates(session, packet_id)
        await _record_bates_audit(session, packet_id, assignments)

    return {"documents": uploaded_documents}


async def _rollback_upload(session: AsyncSession, created_documents: list) -> None:
    for document in created_documents:
        if document not in session:
            continue
        await cleanup_document_files(session, document)
        await session.delete(document)
    if created_documents:
        await session.commit()


async def _record_bates_audit(session: AsyncSession, packet_id: UUID, assignments: list) -> None:
    if not assignments:
        return
    session.add(
        AuditEvent(
            packet_id=packet_id,
            event_type=AuditEventType.BATES_ASSIGNED,
            user_id="system",
            event_metadata={
                "count": len(assignments),
                "bates_start": assignments[0].bates_label,
                "bates_end": assignments[-1].bates_label,
            },
        )
    )
    await session.commit()


@router.get("/{packet_id}")
async def list_documents(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document)
        .where(Document.packet_id == packet_id)
        .order_by(Document.display_order)
        .options(
            selectinload(Document.bates_assignments),
            selectinload(Document.privilege_decisions),
        )
    )
    documents = result.scalars().all()

    return [
        {
            "id": str(doc.id),
            "filename": doc.original_filename,
            "document_type": doc.document_type.value,
            "page_count": doc.page_count,
            "status": doc.processing_status.value,
            "display_order": doc.display_order,
            "bates_range": (
                f"{doc.bates_assignments[0].bates_label} - {doc.bates_assignments[-1].bates_label}"
            )
            if doc.bates_assignments
            else None,
            "privilege_status": doc.privilege_decisions[0].status.value
            if doc.privilege_decisions
            else "pending",
            "is_searchable": doc.is_searchable,
            "description": doc.description,
            "description_source": doc.description_source,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        }
        for doc in documents
    ]


@router.get("/{packet_id}/{document_id}")
async def get_document(
    packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)
):
    document = await session.get(
        Document,
        document_id,
        options=(
            selectinload(Document.bates_assignments),
            selectinload(Document.privilege_decisions),
        ),
    )
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    pages_result = await session.execute(
        select(Page).where(Page.document_id == document_id).order_by(Page.page_number)
    )
    pages = pages_result.scalars().all()

    return {
        "id": str(document.id),
        "filename": document.original_filename,
        "document_type": document.document_type.value,
        "page_count": document.page_count,
        "status": document.processing_status.value,
        "display_order": document.display_order,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "sha256": document.sha256,
        "is_searchable": document.is_searchable,
        "description": document.description,
        "pages": [
            {
                "page_number": p.page_number,
                "has_text": p.has_text,
                "width": p.width,
                "height": p.height,
            }
            for p in pages
        ],
        "bates_assignments": [
            {
                "page_number": ba.page_number,
                "bates_number": ba.bates_number,
                "bates_label": ba.bates_label,
            }
            for ba in document.bates_assignments
        ],
        "privilege_decision": {
            "status": document.privilege_decisions[0].status.value,
            "category": document.privilege_decisions[0].category.value
            if document.privilege_decisions[0].category
            else None,
            "reason": document.privilege_decisions[0].reason,
        }
        if document.privilege_decisions
        else None,
    }


@router.delete("/{packet_id}/{document_id}")
async def delete_document(
    packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    session.add(
        AuditEvent(
            packet_id=packet_id,
            event_type=AuditEventType.DOCUMENT_DELETED,
            user_id="system",
            event_metadata={
                "document_id": str(document.id),
                "filename": document.original_filename,
            },
        )
    )
    removed_files = await cleanup_document_files(session, document)
    await session.delete(document)
    await session.commit()

    assignments = await BatesAssignmentService().assign_bates(session, packet_id)
    await _record_bates_audit(session, packet_id, assignments)

    return {"message": "Document deleted", "files_removed": removed_files}


@router.get("/{packet_id}/{document_id}/download")
async def download_document(
    packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)
):
    from fastapi.responses import FileResponse

    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = original_path_for(document)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=document.original_filename,
        media_type=document.mime_type,
    )


@router.patch("/{packet_id}/{document_id}/reorder")
async def reorder_document(
    packet_id: UUID,
    document_id: UUID,
    request: ReorderDocumentRequest,
    session: AsyncSession = Depends(get_session),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    new_order = request.new_order

    result = await session.execute(
        select(Document).where(Document.packet_id == packet_id).order_by(Document.display_order)
    )
    documents = list(result.scalars().all())

    if new_order < 1 or new_order > len(documents):
        raise HTTPException(status_code=400, detail="Invalid order")

    documents.remove(document)
    documents.insert(new_order - 1, document)

    for i, doc in enumerate(documents):
        doc.display_order = i + 1

    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.DOCUMENT_REORDERED,
            user_id="system",
            event_metadata={"document_id": str(document.id), "new_order": new_order},
        )
    )
    await session.commit()

    assignments = await BatesAssignmentService().assign_bates(session, packet_id)
    await _record_bates_audit(session, packet_id, assignments)

    return {"message": "Document reordered"}
