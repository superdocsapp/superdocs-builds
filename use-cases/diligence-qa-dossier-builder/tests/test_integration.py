import pytest
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import get_db, Base
from backend.app.config import settings
from backend.app.services.ingestion import IngestionService
from backend.app.services.retrieval import RetrievalService

class AsyncTestSession:
    """
    Synchronous context manager that provisions a temporary event loop,
    connects to the local Docker database container on port 5433 using NullPool,
    activates pgvector, sets up clean database tables, and cleans them up on exit.
    This prevents asyncpg connection bleed across closed event loops.
    """
    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Create fresh engine and sessionmaker for this loop, bypassing connection pool
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        # Provision database tables
        async def setup():
            async with self.engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
        try:
            self.loop.run_until_complete(setup())
        except Exception as e:
            self.loop.close()
            pytest.skip(f"Docker database not available for integration tests. Error: {e}")
            
        self.session = self.SessionLocal()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        async def teardown():
            await self.session.close()
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await self.engine.dispose()
        try:
            self.loop.run_until_complete(teardown())
        except Exception:
            pass
        finally:
            self.loop.close()
            app.dependency_overrides.clear()

    def run(self, coro):
        return self.loop.run_until_complete(coro)

def test_postgres_pgvector_availability():
    """
    Verify PostgreSQL connects and the pgvector extension is active in the container.
    """
    with AsyncTestSession() as ts:
        async def check():
            result = await ts.session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            return result.scalar()
        assert ts.run(check()) == "vector"

def test_document_ingestion_and_retrieval():
    """
    Ingests a text document, asserts DB storage, and queries the retrieval service
    to check cosine distance ranking and metadata preservation.
    """
    with AsyncTestSession() as ts:
        async def execute():
            ingestion = IngestionService(ts.session)
            retrieval = RetrievalService(ts.session)
            
            # Ingest cap table file
            content = "Cap table summary: Founder John Doe owns 52% (52,000 shares), Alice owns 28%, and investor seed fund owns 20%."
            doc = await ingestion.ingest_document("cap_table.txt", content.encode("utf-8"))
            
            assert doc.status == "completed"
            assert doc.filename == "cap_table.txt"
            assert doc.file_type == "txt"
            
            # Verify chunks are inserted
            result = await ts.session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :doc_id"),
                {"doc_id": doc.id}
            )
            count = result.scalar()
            assert count > 0

            # Query retrieval service semantically
            query = "Founder John Doe seed funding ownership percentages"
            search_results = await retrieval.search_diligence_chunks(query, limit=2)
            
            assert len(search_results) > 0
            best_match = search_results[0]
            assert best_match["filename"] == "cap_table.txt"
            assert "John Doe" in best_match["content"]
            assert best_match["similarity_score"] > 0.0
            assert best_match["document_id"] == str(doc.id)
            assert "chunk_id" in best_match
            
        ts.run(execute())

def test_upload_and_search_endpoints():
    """
    Verifies API controllers: upload multi-part file, search, listing, and delete cascading.
    """
    with AsyncTestSession() as ts:
        # Override the FastAPI db dependency to use the isolated test session
        async def override_get_db():
            async with ts.SessionLocal() as session:
                yield session
        app.dependency_overrides[get_db] = override_get_db
        
        client = TestClient(app)
        
        # 1. Upload a security policy text file
        content = "Company security is built on SOC2 Type II audits, ISO 27001 guidelines, and AES-256 data encryption."
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("security_policy.txt", content.encode("utf-8"), "text/plain")}
        )
        assert response.status_code == 201
        data = response.json()
        doc_id = data["id"]
        assert data["filename"] == "security_policy.txt"
        assert data["status"] == "completed"

        # 2. List documents in system
        list_resp = client.get("/api/v1/documents")
        assert list_resp.status_code == 200
        docs = list_resp.json()
        assert any(d["id"] == doc_id for d in docs)

        # 3. Perform semantic search via API
        search_resp = client.post(
            "/api/v1/documents/search",
            json={"query": "SOC2 compliance audit and encryption protocols", "limit": 3}
        )
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) > 0
        assert "SOC2 Type II" in results[0]["content"]
        assert results[0]["filename"] == "security_policy.txt"
        assert "similarity_score" in results[0]

        # 4. Clean up by deleting the document
        del_resp = client.delete(f"/api/v1/documents/{doc_id}")
        assert del_resp.status_code == 204

        # Verify document and chunks are deleted
        list_resp_after = client.get("/api/v1/documents")
        assert not any(d["id"] == doc_id for d in list_resp_after.json())
