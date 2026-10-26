-- 003_chunk_text.sql: a searchable plain-text projection of every chunk.
--
-- Global search matches against text, not markup. Searching the stored HTML
-- would match tag names and attributes — a query for "class" or "p" would hit
-- every chunk in the corpus — and would miss any phrase interrupted by an
-- inline tag.
--
-- The authoritative projection is core.text.html_to_text, applied on write.
-- The expression below only backfills rows that predate this column.
--
-- Idempotent: applied at startup against databases that already exist.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_content TEXT;

UPDATE chunks
   SET text_content = btrim(
           regexp_replace(
               regexp_replace(html, '<[^>]+>', ' ', 'g'),
               '\s+', ' ', 'g'
           )
       )
 WHERE text_content IS NULL;

-- Search reads text_content for every chunk in the corpus, unfiltered by run.
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks (document_id);
