-- 001_init.sql: Full schema for Documentation Drift Detector
-- §7 Data Model from drift-detector-spec.md

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_ref TEXT,
    feed_ref TEXT,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE run_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    node TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    output_ref JSONB,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    UNIQUE (run_id, node, input_hash)
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    superdocs_doc_id TEXT,
    session_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, file_hash)
);

CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id),
    chunk_id TEXT NOT NULL,
    html TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding vector(1536),
    UNIQUE (document_id, chunk_id)
);

CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE change_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    evidence_span TEXT,
    source_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    change_fact_id UUID REFERENCES change_facts(id),
    chunk_id TEXT,
    document_id UUID REFERENCES documents(id),
    state TEXT NOT NULL,
    evidence_quote TEXT,
    evidence_chunk_id TEXT,
    proposed_old TEXT,
    proposed_new TEXT,
    verifier_verdict TEXT,
    judge_verdict TEXT,
    ai_explanation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE review_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID NOT NULL REFERENCES findings(id),
    decision TEXT NOT NULL,
    feedback TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (finding_id)
);

CREATE TABLE applied_edits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID NOT NULL REFERENCES findings(id),
    superdocs_job_id TEXT NOT NULL,
    superdocs_change_id TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE queues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID NOT NULL REFERENCES findings(id),
    kind TEXT NOT NULL,
    reason TEXT,
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE trace (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id),
    node TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    decision TEXT,
    evidence JSONB,
    tokens_in INTEGER,
    tokens_out INTEGER,
    superdocs_ops INTEGER NOT NULL DEFAULT 0,
    ms INTEGER NOT NULL DEFAULT 0,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    agent TEXT NOT NULL,
    payload JSONB,
    result JSONB,
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_jobs_kind_status ON jobs (kind, status);
CREATE INDEX idx_trace_run_id ON trace (run_id);
CREATE INDEX idx_findings_run_id ON findings (run_id);
CREATE INDEX idx_chunks_content_hash ON chunks (content_hash);
CREATE INDEX idx_run_steps_lookup ON run_steps (run_id, node, status);

CREATE OR REPLACE VIEW cost_ledger AS
SELECT
    run_id,
    node,
    COUNT(*) AS steps,
    COALESCE(SUM(tokens_in), 0) AS total_tokens_in,
    COALESCE(SUM(tokens_out), 0) AS total_tokens_out,
    COALESCE(SUM(superdocs_ops), 0) AS total_superdocs_ops,
    COALESCE(SUM(ms), 0) AS total_ms
FROM trace
GROUP BY run_id, node;