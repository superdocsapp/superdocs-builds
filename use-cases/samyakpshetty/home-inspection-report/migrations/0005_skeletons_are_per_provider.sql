-- A cached skeleton belongs to the service that produced it.
--
-- 0004 keyed the cache on the format's content hash alone. The hash describes the .docx we
-- registered, not the document that came back — so a skeleton materialised against the
-- offline fake was served to a live run, which then reported `cache` and built the report on
-- bytes the fake had produced. The one thing the round trip exists to prove is that the
-- document came from SuperDocs, and that is exactly what the cache quietly undid.
--
-- Dropped rather than migrated: it is a cache with no other reader, and every row in it is
-- one call away from being rebuilt correctly. Keeping them would mean keeping the ones that
-- caused the problem.

DROP TABLE IF EXISTS template_skeletons;

CREATE TABLE template_skeletons (
    content_sha   TEXT        NOT NULL,
    provider      TEXT        NOT NULL,
    format_key    TEXT        NOT NULL,
    template_name TEXT        NOT NULL,
    html          TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (content_sha, provider)
);
