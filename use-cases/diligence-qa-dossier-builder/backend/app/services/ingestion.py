import hashlib
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Document, DocumentChunk
from backend.app.exceptions import DuplicateFileError, FileIngestionError, UnsupportedFileError
from backend.app.services.storage import get_storage_service
from backend.app.services.parsing import extract_document_text, ExtractedSegment
from backend.app.services.embedding import get_embedding_service

class TextChunk(BaseModel):
    content: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    chunk_index: int

def chunk_segments(
    segments: List[ExtractedSegment], 
    chunk_size: int = 1000, 
    chunk_overlap: int = 200
) -> List[TextChunk]:
    """
    Groups consecutive extracted segments that share the same metadata 
    (page number and section context), combines their text, and splits them
    into overlapping chunks. This preserves local context and citation precision.
    """
    chunks = []
    chunk_idx = 0
    current_meta = (None, None)
    current_buffer = []

    def flush_buffer(buffer: List[str], page: Optional[int], sec: Optional[str]):
        nonlocal chunk_idx
        combined_text = "\n".join(buffer).strip()
        if not combined_text:
            return []
        
        sub_chunks = []
        start = 0
        while start < len(combined_text):
            end = min(start + chunk_size, len(combined_text))
            sub_chunks.append(TextChunk(
                content=combined_text[start:end],
                page_number=page,
                section=sec,
                chunk_index=chunk_idx
            ))
            chunk_idx += 1
            if end == len(combined_text):
                break
            start += chunk_size - chunk_overlap
        return sub_chunks

    for seg in segments:
        meta = (seg.page_number, seg.section)
        if meta == current_meta:
            current_buffer.append(seg.content)
        else:
            if current_buffer:
                chunks.extend(flush_buffer(current_buffer, current_meta[0], current_meta[1]))
            current_buffer = [seg.content]
            current_meta = meta

    if current_buffer:
        chunks.extend(flush_buffer(current_buffer, current_meta[0], current_meta[1]))

    return chunks

class IngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_service()
        self.embedding = get_embedding_service()

    async def ingest_document(self, filename: str, file_bytes: bytes) -> Document:
        # 1. Size Validation (Max 10MB)
        MAX_SIZE = 10 * 1024 * 1024
        if len(file_bytes) > MAX_SIZE:
            raise FileIngestionError(f"File size exceeds maximum limit of 10MB: {len(file_bytes)} bytes")

        # 2. Compute SHA-256 content hash
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # 3. Duplicate Detection
        stmt = select(Document).where(Document.hash_sha256 == sha256)
        result = await self.db.execute(stmt)
        existing_doc = result.scalar_one_or_none()
        if existing_doc:
            raise DuplicateFileError(f"Duplicate document detected: '{filename}' has same content as already uploaded '{existing_doc.filename}'")

        # 4. Save to physical storage
        ext = filename.lower().split(".")[-1]
        storage_path = None
        try:
            storage_path = await self.storage.save_file(filename, file_bytes)
        except Exception as e:
            raise FileIngestionError(f"Failed to write file to storage: {e}")

        # 5. Insert document in PENDING state
        doc = Document(
            filename=filename,
            file_size=len(file_bytes),
            file_type=ext,
            hash_sha256=sha256,
            storage_path=storage_path,
            status="pending"
        )
        self.db.add(doc)
        await self.db.flush()  # Populates doc.id

        try:
            # Move to processing state
            doc.status = "processing"
            await self.db.flush()

            # Parse file and extract segments
            segments = extract_document_text(filename, file_bytes)

            # Chunk content segments
            chunks = chunk_segments(segments)
            if not chunks:
                raise FileIngestionError("No readable text content extracted from the document.")

            # Batch generate embeddings
            texts = [c.content for c in chunks]
            embeddings = await self.embedding.get_embeddings(texts)

            # Bulk insert chunks
            for idx, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    content=chunk.content,
                    embedding=embeddings[idx]
                )
                self.db.add(db_chunk)

            # Complete transaction
            doc.status = "completed"
            await self.db.commit()
            return doc

        except Exception as e:
            # Rollback database changes
            await self.db.rollback()

            # Remove physical file if saved
            if storage_path:
                try:
                    await self.storage.delete_file(storage_path)
                except Exception:
                    pass

            # Write failed state document for audit/visibility
            failed_doc = Document(
                filename=filename,
                file_size=len(file_bytes),
                file_type=ext,
                hash_sha256=sha256,
                status="failed",
                error_message=str(e)
            )
            self.db.add(failed_doc)
            await self.db.commit()

            # Re-raise target exception
            if isinstance(e, (DuplicateFileError, UnsupportedFileError)):
                raise e
            raise FileIngestionError(f"Ingestion failed: {e}")
