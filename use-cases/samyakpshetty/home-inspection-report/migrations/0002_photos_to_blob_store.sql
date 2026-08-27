-- Photograph bytes move out of the database and into a blob store; the row keeps a key.
--
-- Storing them as BYTEA works and is transactional, which is why it was the right call for a
-- build that has to run from one `docker compose up`. It does not survive contact with a
-- firm doing five inspections a day at thirty photographs each: every backup, restore and
-- replica carries hundreds of gigabytes a year of image data.
--
-- The old columns are kept and made nullable rather than dropped. A row written before this
-- migration still has its bytes and still serves correctly — the read path falls back to the
-- column when `storage_key` is null. Once a deployment has backfilled its blobs, a later
-- migration can drop the columns; doing it here would destroy data on the way past.

ALTER TABLE photos ADD COLUMN IF NOT EXISTS storage_key   TEXT;
ALTER TABLE photos ADD COLUMN IF NOT EXISTS thumbnail_key TEXT;

ALTER TABLE photos ALTER COLUMN bytes DROP NOT NULL;

-- A key is referenced by every row sharing those bytes, so this is not unique.
CREATE INDEX IF NOT EXISTS photos_by_storage_key ON photos (storage_key);
