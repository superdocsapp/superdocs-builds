-- Production PostgreSQL migration. SQLite is used only for deterministic offline tests.
CREATE EXTENSION IF NOT EXISTS vector;

-- The portable ORM stores the deterministic embedding payload as JSON for SQLite.
-- A production deployment may materialize this column as vector(384) and create:
-- CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
--   ON document_chunks USING hnsw (embedding_vector vector_cosine_ops);
