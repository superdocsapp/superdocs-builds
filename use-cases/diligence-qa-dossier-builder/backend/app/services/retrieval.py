from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Document, DocumentChunk
from backend.app.services.embedding import get_embedding_service

class RetrievalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding_service = get_embedding_service()

    async def search_diligence_chunks(
        self, 
        query: str, 
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Performs semantic retrieval by embedding the query and searching 
        the document chunks using pgvector's cosine similarity.
        """
        if not query.strip():
            return []

        # 1. Generate query embedding vector
        query_vector = await self.embedding_service.get_embedding(query)

        # 2. Construct pgvector cosine distance query
        # cosine_distance is a helper method on the pgvector.sqlalchemy Vector type
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        
        # Calculate similarity score: 1.0 - distance
        similarity_score = (1.0 - distance).label("similarity_score")
        
        stmt = (
            select(DocumentChunk, Document.filename, similarity_score)
            .join(Document, DocumentChunk.document_id == Document.id)
            .order_by(distance)
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        search_results = []
        for chunk, filename, score in rows:
            search_results.append({
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "filename": filename,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "similarity_score": float(score) if score is not None else 0.0
            })
            
        return search_results
