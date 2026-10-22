from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.domain.bates import BatesAssignment
from app.domain.document import Document
from app.domain.packet import Packet
from app.domain.page import Page

router = APIRouter()


def _bates_for_page(bates_map: dict, doc_id, page_num: int) -> str | None:
    key = (str(doc_id), page_num)
    assignment = bates_map.get(key)
    return assignment.bates_label if assignment else None


@router.get("/{packet_id}")
async def search_packet(packet_id: UUID, q: str, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    query = q.strip()
    if not query:
        return {"packet_id": packet_id, "query": q, "total_results": 0, "results": []}

    pattern = f"%{query}%"

    bates_result = await session.execute(
        select(BatesAssignment).where(BatesAssignment.packet_id == packet_id)
    )
    bates_assignments = bates_result.scalars().all()
    bates_map = {
        (str(ba.document_id), ba.page_number): ba for ba in bates_assignments
    }
    doc_bates_map: dict[str, list] = {}
    for ba in bates_assignments:
        doc_bates_map.setdefault(str(ba.document_id), []).append(ba)
    for k in doc_bates_map:
        doc_bates_map[k].sort(key=lambda b: b.bates_number)

    doc_results = await session.execute(
        select(Document)
        .where(
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
        select(BatesAssignment).where(
            BatesAssignment.packet_id == packet_id,
            BatesAssignment.bates_label.ilike(pattern),
        )
    )
    bates_matches = bates_results.scalars().all()

    results = []
    seen_documents: set = set()
    seen_page_keys: set = set()

    for document in matched_docs:
        doc_id_str = str(document.id)
        matched_fields = []
        if document.original_filename and query.lower() in document.original_filename.lower():
            matched_fields.append("filename")
        if document.description and query.lower() in document.description.lower():
            matched_fields.append("description")
        doc_bates = doc_bates_map.get(doc_id_str, [])
        bates_range = (
            f"{doc_bates[0].bates_label} - {doc_bates[-1].bates_label}"
            if doc_bates
            else None
        )
        results.append(
            {
                "document_id": doc_id_str,
                "document_name": document.original_filename,
                "document_type": document.document_type.value,
                "page_count": document.page_count,
                "status": document.processing_status.value,
                "bates_range": bates_range,
                "description": document.description,
                "matched_fields": matched_fields,
                "snippets": [],
            }
        )
        seen_documents.add(doc_id_str)

    for page, document in page_matches:
        doc_id_str = str(document.id)
        page_key = (doc_id_str, page.page_number)
        text = page.extracted_text or ""
        lower = text.lower()
        idx = lower.find(query.lower())
        if idx < 0:
            continue
        start = max(0, idx - 100)
        snippet = text[start : idx + len(query) + 100]
        bates_label = _bates_for_page(bates_map, document.id, page.page_number)

        if doc_id_str in seen_documents:
            for r in results:
                if r["document_id"] == doc_id_str:
                    r["snippets"].append(
                        {
                            "page_number": page.page_number,
                            "bates_label": bates_label,
                            "snippet": snippet,
                        }
                    )
                    break
        elif page_key not in seen_page_keys:
            seen_page_keys.add(page_key)
            doc_bates = doc_bates_map.get(doc_id_str, [])
            bates_range = (
                f"{doc_bates[0].bates_label} - {doc_bates[-1].bates_label}"
                if doc_bates
                else None
            )
            results.append(
                {
                    "document_id": doc_id_str,
                    "document_name": document.original_filename,
                    "document_type": document.document_type.value,
                    "page_count": document.page_count,
                    "status": document.processing_status.value,
                    "bates_range": bates_range,
                    "description": document.description,
                    "matched_fields": ["content"],
                    "snippets": [
                        {
                            "page_number": page.page_number,
                            "bates_label": bates_label,
                            "snippet": snippet,
                        }
                    ],
                }
            )
            seen_documents.add(doc_id_str)

    for ba in bates_matches:
        doc_id_str = str(ba.document_id)
        if doc_id_str in seen_documents:
            continue
        seen_documents.add(doc_id_str)
        document = await session.get(Document, ba.document_id)
        if not document:
            continue
        doc_bates = doc_bates_map.get(doc_id_str, [])
        bates_range = (
            f"{doc_bates[0].bates_label} - {doc_bates[-1].bates_label}"
            if doc_bates
            else None
        )
        results.append(
            {
                "document_id": doc_id_str,
                "document_name": document.original_filename,
                "document_type": document.document_type.value,
                "page_count": document.page_count,
                "status": document.processing_status.value,
                "bates_range": bates_range,
                "description": document.description,
                "matched_fields": ["bates_label"],
                "snippets": [
                    {
                        "page_number": ba.page_number,
                        "bates_label": ba.bates_label,
                        "snippet": f"Bates number {ba.bates_label}",
                    }
                ],
            }
        )

    return {
        "packet_id": packet_id,
        "query": q,
        "total_results": len(results),
        "results": results,
    }


@router.get("/{packet_id}/bates/{bates_number}")
async def search_by_bates(
    packet_id: UUID, bates_number: str, session: AsyncSession = Depends(get_session)
):
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
