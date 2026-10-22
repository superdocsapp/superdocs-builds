from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_session
from app.domain.packet import Packet
from app.domain.document import Document
from app.domain.page import Page
from app.domain.bates import BatesAssignment

router = APIRouter()


@router.get("/{packet_id}")
async def search_packet(packet_id: UUID, q: str, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    query = q.strip()
    if not query:
        return {"packet_id": packet_id, "query": q, "total_results": 0, "results": []}

    pattern = f"%{query}%"

    doc_results = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            or_(
                Document.original_filename.ilike(pattern),
                Document.description.ilike(pattern),
            ),
        )
    )
    matched_docs = doc_results.scalars().all()

    page_results = await session.execute(
        select(Page, Document)
        .join(Document, Page.document_id == Document.id)
        .where(
            Document.packet_id == packet_id,
            Page.extracted_text.ilike(pattern),
        )
    )
    page_matches = page_results.fetchall()

    bates_results = await session.execute(
        select(BatesAssignment)
        .where(
            BatesAssignment.packet_id == packet_id,
            BatesAssignment.bates_label.ilike(pattern),
        )
    )
    bates_matches = bates_results.scalars().all()

    results = []
    seen_documents = set()

    for document in matched_docs:
        matched_fields = []
        if document.original_filename and query.lower() in document.original_filename.lower():
            matched_fields.append("filename")
        if document.description and query.lower() in document.description.lower():
            matched_fields.append("description")
        results.append({
            "document_id": str(document.id),
            "document_name": document.original_filename,
            "document_type": document.document_type.value,
            "page_count": document.page_count,
            "status": document.processing_status.value,
            "matched_fields": matched_fields,
            "snippets": [],
        })
        seen_documents.add(document.id)

    for page, document in page_matches:
        if document.id in seen_documents:
            continue
        seen_documents.add(document.id)
        text = page.extracted_text or ""
        lower = text.lower()
        idx = lower.find(query.lower())
        start = max(0, idx - 100)
        snippet = text[start:idx + len(query) + 100]
        results.append({
            "document_id": str(document.id),
            "document_name": document.original_filename,
            "document_type": document.document_type.value,
            "page_count": document.page_count,
            "status": document.processing_status.value,
            "matched_fields": ["content"],
            "snippets": [{"page_number": page.page_number, "snippet": snippet}],
        })

    for ba in bates_matches:
        if ba.document_id in seen_documents:
            continue
        seen_documents.add(ba.document_id)
        document = await session.get(Document, ba.document_id)
        if not document:
            continue
        results.append({
            "document_id": str(document.id),
            "document_name": document.original_filename,
            "document_type": document.document_type.value,
            "page_count": document.page_count,
            "status": document.processing_status.value,
            "matched_fields": ["bates_label"],
            "snippets": [{"page_number": ba.page_number, "snippet": f"Bates number {ba.bates_label}"}],
        })

    return {
        "packet_id": packet_id,
        "query": q,
        "total_results": len(results),
        "results": results,
    }


@router.get("/{packet_id}/bates/{bates_number}")
async def search_by_bates(packet_id: UUID, bates_number: str, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(BatesAssignment).where(
            BatesAssignment.packet_id == packet_id,
            BatesAssignment.bates_label == bates_number,
        )
    )
    assignment = result.scalars().first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Bates number not found in packet")

    document = await session.get(Document, assignment.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "bates_label": assignment.bates_label,
        "bates_number": assignment.bates_number,
        "page_number": assignment.page_number,
        "document_id": str(document.id),
        "document_name": document.original_filename,
        "packet_id": packet_id,
    }
