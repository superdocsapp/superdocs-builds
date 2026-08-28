"""Document upload API — accepts files and stores them for pipeline processing.

Provides a POST /documents/upload endpoint that:
1. Accepts a file via multipart form upload
2. Validates MIME type (PDF, DOCX, text/plain)
3. Stores the file locally in uploads/ directory
4. Inserts into documents + document_versions tables
5. Returns the document_id and document_version_id for pipeline execution
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database import SessionLocal
from src.models.documents import Document, DocumentVersion

# Upload directory (relative to project root)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

# Fallback MIME type detection from extension
EXTENSION_MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".text": "text/plain",
}


class UploadResponse(BaseModel):
    """Response after successful document upload."""

    document_id: str
    document_version_id: str
    filename: str
    mime_type: str
    size_bytes: int


class DocumentListItem(BaseModel):
    """Summary of a document."""

    document_id: str
    filename: str
    mime_type: str
    ingested_at: str


router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    """Upload a document file for pipeline processing.

    Accepts PDF, DOCX, or plain text files. Stores the file locally and
    creates database records for tracking.
    """
    # Determine MIME type
    mime_type = file.content_type or ""
    filename = file.filename or "unnamed"

    # If MIME type is generic, try to infer from extension
    if mime_type in ("application/octet-stream", ""):
        ext = Path(filename).suffix.lower()
        mime_type = EXTENSION_MIME_MAP.get(ext, mime_type)

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {mime_type}. "
            f"Allowed: {sorted(ALLOWED_MIME_TYPES)}",
        )

    # Read file content
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    # Compute content hash for deduplication
    content_hash = hashlib.sha256(content).hexdigest()

    # Ensure upload directory exists
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Store file with unique name
    doc_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    ext = Path(filename).suffix or ".bin"
    stored_filename = f"{doc_id}{ext}"
    storage_path = UPLOAD_DIR / stored_filename
    storage_path.write_bytes(content)

    # Insert into database
    session = SessionLocal()
    try:
        doc = Document(
            id=uuid.UUID(doc_id),
            filename=filename,
            mime_type=mime_type,
            ingested_at=datetime.now(timezone.utc),
            metadata_={},
        )
        session.add(doc)

        version = DocumentVersion(
            id=uuid.UUID(version_id),
            document_id=uuid.UUID(doc_id),
            content_hash=content_hash,
            storage_ref=str(storage_path),
            version_number=1,
        )
        session.add(version)
        session.commit()
    except Exception as e:
        session.rollback()
        # Clean up stored file on DB error
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        session.close()

    return UploadResponse(
        document_id=doc_id,
        document_version_id=version_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(content),
    )


@router.get("", response_model=list[DocumentListItem])
async def list_documents() -> list[DocumentListItem]:
    """List all uploaded documents."""
    session = SessionLocal()
    try:
        docs = session.execute(
            select(Document).order_by(Document.ingested_at.desc())
        ).scalars().all()

        return [
            DocumentListItem(
                document_id=str(doc.id),
                filename=doc.filename,
                mime_type=doc.mime_type,
                ingested_at=doc.ingested_at.isoformat(),
            )
            for doc in docs
        ]
    finally:
        session.close()
