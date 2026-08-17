-- 004_chunk_order.sql: remember what order a document's chunks come in.
--
-- SuperDocs chunk ids are random UUIDs. Every read of a document ordered by
-- `chunk_id`, which is therefore arbitrary: in one stored document the <h1>
-- title sorted sixth. The viewer, the inline HTML page and the text download
-- all rendered paragraphs out of order, and nothing in the schema recorded
-- position, so the order could not be recovered by any query.
--
-- `ordinal` is written at ingest from the parse order.
--
-- Existing rows cannot be backfilled correctly — their order was never
-- recorded anywhere and the SuperDocs documents they came from have since
-- been overwritten. They keep ordinal IS NULL, and readers sort those last by
-- chunk_id, which is no worse than the behaviour they already had. Re-ingest
-- a document to give it a real order.
--
-- Idempotent: applied at startup against databases that already exist.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS ordinal INTEGER;

CREATE INDEX IF NOT EXISTS idx_chunks_document_ordinal
    ON chunks (document_id, ordinal);
