from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import Document
from backend.app.exceptions import DuplicateFileError, UnsupportedFileError, FileIngestionError
from backend.app.services.ingestion import IngestionService
from backend.app.services.retrieval import RetrievalService
from backend.app.services.storage import get_storage_service

router = APIRouter(prefix="/documents", tags=["documents"])

# Pydantic schemas for request/response validation
class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    file_size: int
    file_type: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime

class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 5

class SearchResultResponse(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    content: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    similarity_score: float

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...), 
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a single document to the startup data room.
    Initiates validation, content deduplication, parsing, chunking, and database insertion.
    """
    try:
        file_bytes = await file.read()
        ingestion_service = IngestionService(db)
        doc = await ingestion_service.ingest_document(file.filename, file_bytes)
        return doc
    except DuplicateFileError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except UnsupportedFileError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileIngestionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during ingestion: {str(e)}"
        )

@router.get("", response_model=List[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)):
    """
    List metadata of all uploaded documents in the system.
    """
    stmt = select(Document).order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Remove a document from the system. 
    Deletes the underlying database chunks and the original stored file.
    """
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    # 1. Clean up physical file storage reference
    if doc.storage_path:
        storage = get_storage_service()
        try:
            await storage.delete_file(doc.storage_path)
        except Exception:
            pass # Continue deletion of database record even if physical delete fails

    # 2. Database cascading deletion (thanks to SQLAlchemy delete cascade)
    await db.delete(doc)
    await db.commit()

@router.post("/search", response_model=List[SearchResultResponse])
async def search_documents(
    payload: SearchRequest, 
    db: AsyncSession = Depends(get_db)
):
    """
    Semantically search across the ingested documents using pgvector cosine similarity.
    """
    retrieval_service = RetrievalService(db)
    results = await retrieval_service.search_diligence_chunks(
        query=payload.query, 
        limit=payload.limit or 5
    )
    return results
