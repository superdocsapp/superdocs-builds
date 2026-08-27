-- Work that takes longer than a request should wait.
--
-- `prepare` asks SuperDocs to rewrite every finding, and SuperDocs' own guidance says an
-- operation can take from thirty seconds to several minutes. Doing that inside the HTTP
-- request meant a proxy with a sixty-second timeout returned 504 to the inspector while the
-- operation was still charged, and a database connection stayed pinned for the duration.
--
-- So the request enqueues a row and returns. A worker claims it with FOR UPDATE SKIP LOCKED,
-- which is what makes two workers safe without a broker, and holds a lease it renews while
-- it works. If the worker dies the lease expires and the row is reclaimed — as *failed*,
-- deliberately, not retried: the AI call costs money and re-running one that may already
-- have completed would spend it twice. Nothing was applied, so the honest instruction is to
-- start the review again.

CREATE TABLE IF NOT EXISTS jobs (
    id             UUID PRIMARY KEY,
    inspection_id  UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    kind           TEXT        NOT NULL,
    state          TEXT        NOT NULL DEFAULT 'queued',
    payload        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    result         JSONB,
    error          TEXT,
    attempts       INTEGER     NOT NULL DEFAULT 0,
    lease_until    TIMESTAMPTZ,
    worker         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    CONSTRAINT jobs_state_known CHECK (state IN ('queued', 'running', 'done', 'failed'))
);

-- The claim query orders by created_at over queued rows and reclaimable leases.
CREATE INDEX IF NOT EXISTS jobs_claimable ON jobs (state, created_at);
CREATE INDEX IF NOT EXISTS jobs_by_inspection ON jobs (inspection_id, created_at DESC);

-- One live job per inspection: a second `prepare` while one is in flight is a mistake, not a
-- queue. Enforced in the database so two API processes cannot both accept one.
CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_live_per_inspection
    ON jobs (inspection_id)
    WHERE state IN ('queued', 'running');
