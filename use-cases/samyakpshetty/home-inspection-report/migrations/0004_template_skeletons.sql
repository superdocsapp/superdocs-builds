-- The skeleton a report is built on, as SuperDocs handed it back.
--
-- A format is a Word document registered with SuperDocs, and the report is built on the
-- document SuperDocs returns when asked to load it — not on our local copy. That round trip
-- is the point: delete the template from the account and no report can be produced.
--
-- It is also an operation, and an operation costs money. A format changes when a firm changes
-- its format, which is roughly never, while reports are produced daily — so the skeleton is
-- cached here against the content hash of the .docx it came from. One operation per format
-- version, not per report. Editing the format changes the hash, which is a different row, so
-- a changed format is picked up without anything being invalidated by hand.
--
-- Keyed by content hash rather than by format name so that two versions of the same format
-- can coexist: reports produced last month were built on the skeleton of last month's bytes.

CREATE TABLE IF NOT EXISTS template_skeletons (
    content_sha   TEXT PRIMARY KEY,
    format_key    TEXT        NOT NULL,
    template_name TEXT        NOT NULL,
    html          TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
