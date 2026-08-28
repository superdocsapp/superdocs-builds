"""Piles API — CRUD for document piles and uploading documents into them.

Provides:
- GET /piles — list all piles
- POST /piles — create a new pile
- GET /piles/{pile_id} — get pile with its documents
- POST /piles/{pile_id}/documents — upload file(s) directly into a pile
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.database import SessionLocal
from src.models.documents import Document, DocumentVersion
from src.models.piles import Pile, PileDocument

# Upload directory (relative to project root)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

EXTENSION_MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".text": "text/plain",
}


# ─── Response models ──────────────────────────────────────────────────────────


class PileListItem(BaseModel):
    id: str
    name: str
    status: str
    created_at: str
    document_count: int


class PileDocumentItem(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    added_at: str


class PileDetail(BaseModel):
    id: str
    name: str
    status: str
    created_at: str
    documents: list[PileDocumentItem]


class CreatePileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class CreatePileResponse(BaseModel):
    id: str
    name: str


class UploadToPileResponse(BaseModel):
    pile_id: str
    uploaded: list[dict]  # [{document_id, filename, mime_type, size_bytes}]
    errors: list[str]


# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/piles", tags=["piles"])


@router.get("", response_model=list[PileListItem])
async def list_piles() -> list[PileListItem]:
    """List all piles with document counts."""
    session = SessionLocal()
    try:
        piles = session.execute(
            select(Pile).where(Pile.status == "active").order_by(Pile.created_at.desc())
        ).scalars().all()

        results = []
        for pile in piles:
            doc_count = len(pile.documents)
            results.append(PileListItem(
                id=str(pile.id),
                name=pile.name,
                status=pile.status,
                created_at=pile.created_at.isoformat(),
                document_count=doc_count,
            ))
        return results
    finally:
        session.close()


@router.post("", response_model=CreatePileResponse)
async def create_pile(request: CreatePileRequest) -> CreatePileResponse:
    """Create a new empty pile."""
    session = SessionLocal()
    try:
        pile = Pile(
            id=uuid.uuid4(),
            name=request.name,
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata_={},
        )
        session.add(pile)
        session.commit()
        return CreatePileResponse(id=str(pile.id), name=pile.name)
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create pile: {e}")
    finally:
        session.close()


@router.get("/{pile_id}", response_model=PileDetail)
async def get_pile(pile_id: str) -> PileDetail:
    """Get pile details including its documents."""
    session = SessionLocal()
    try:
        pile = session.execute(
            select(Pile).where(Pile.id == uuid.UUID(pile_id))
        ).scalar_one_or_none()

        if pile is None:
            raise HTTPException(status_code=404, detail="Pile not found")

        docs = []
        for pd in pile.documents:
            doc = session.execute(
                select(Document).where(Document.id == pd.document_id)
            ).scalar_one_or_none()
            if doc:
                docs.append(PileDocumentItem(
                    document_id=str(doc.id),
                    filename=doc.filename,
                    mime_type=doc.mime_type,
                    added_at=pd.added_at.isoformat(),
                ))

        return PileDetail(
            id=str(pile.id),
            name=pile.name,
            status=pile.status,
            created_at=pile.created_at.isoformat(),
            documents=docs,
        )
    finally:
        session.close()


@router.post("/{pile_id}/documents", response_model=UploadToPileResponse)
async def upload_to_pile(
    pile_id: str,
    files: list[UploadFile] = File(...),
) -> UploadToPileResponse:
    """Upload one or more documents into a pile.

    Each file is stored and a Document + DocumentVersion record is created,
    then linked to the pile via pile_documents.
    """
    session = SessionLocal()
    try:
        # Verify pile exists
        pile = session.execute(
            select(Pile).where(Pile.id == uuid.UUID(pile_id))
        ).scalar_one_or_none()
        if pile is None:
            raise HTTPException(status_code=404, detail="Pile not found")

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        uploaded = []
        errors = []

        for file in files:
            try:
                mime_type = file.content_type or ""
                filename = file.filename or "unnamed"

                # Infer MIME from extension if generic
                if mime_type in ("application/octet-stream", ""):
                    ext = Path(filename).suffix.lower()
                    mime_type = EXTENSION_MIME_MAP.get(ext, mime_type)

                if mime_type not in ALLOWED_MIME_TYPES:
                    errors.append(f"{filename}: unsupported type {mime_type}")
                    continue

                content = await file.read()
                if len(content) == 0:
                    errors.append(f"{filename}: file is empty")
                    continue

                content_hash = hashlib.sha256(content).hexdigest()
                doc_id = uuid.uuid4()
                version_id = uuid.uuid4()
                ext = Path(filename).suffix or ".bin"
                stored_filename = f"{doc_id}{ext}"
                storage_path = UPLOAD_DIR / stored_filename
                storage_path.write_bytes(content)

                # Create document + version
                doc = Document(
                    id=doc_id,
                    filename=filename,
                    mime_type=mime_type,
                    ingested_at=datetime.now(timezone.utc),
                    metadata_={},
                )
                session.add(doc)

                version = DocumentVersion(
                    id=version_id,
                    document_id=doc_id,
                    content_hash=content_hash,
                    storage_ref=str(storage_path),
                    version_number=1,
                )
                session.add(version)

                # Link to pile
                pile_doc = PileDocument(
                    pile_id=uuid.UUID(pile_id),
                    document_id=doc_id,
                    added_at=datetime.now(timezone.utc),
                )
                session.add(pile_doc)

                uploaded.append({
                    "document_id": str(doc_id),
                    "filename": filename,
                    "mime_type": mime_type,
                    "size_bytes": len(content),
                })

            except Exception as e:
                errors.append(f"{file.filename or 'unknown'}: {str(e)}")

        session.commit()
        return UploadToPileResponse(
            pile_id=pile_id,
            uploaded=uploaded,
            errors=errors,
        )
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        session.close()


@router.delete("/{pile_id}")
async def delete_pile(pile_id: str) -> dict:
    """Delete a pile by archiving it (soft delete).

    Sets pile status to 'archived'. Does not remove documents from the
    documents table — they may be referenced by other piles or runs.
    """
    session = SessionLocal()
    try:
        pile = session.execute(
            select(Pile).where(Pile.id == uuid.UUID(pile_id))
        ).scalar_one_or_none()

        if pile is None:
            raise HTTPException(status_code=404, detail="Pile not found")

        pile.status = "archived"
        pile.updated_at = datetime.now(timezone.utc)
        session.commit()

        return {"id": pile_id, "status": "archived"}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete pile: {e}")
    finally:
        session.close()
