PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    expectation TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 2,
    linkable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS documents (
    session_slot_id TEXT PRIMARY KEY,
    durable_document_id TEXT UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('manual', 'procedure', 'generated')),
    name TEXT NOT NULL,
    version_hash TEXT NOT NULL DEFAULT '',
    last_seen_event_id INTEGER NOT NULL DEFAULT 0,
    bound_at TEXT
);

CREATE TABLE IF NOT EXISTS links (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
    durable_document_id TEXT NOT NULL REFERENCES documents(durable_document_id),
    chunk_id TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    quote_excerpt TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('covered', 'stale', 'gap')),
    last_verified_at TEXT,
    last_verified_job TEXT,
    UNIQUE (clause_id, durable_document_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS edits (
    edit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    durable_document_id TEXT,
    session_slot_id TEXT,
    chunk_id TEXT,
    operation TEXT NOT NULL,
    old_excerpt TEXT,
    new_excerpt TEXT,
    occurred_at TEXT NOT NULL,
    causing_instruction TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'api'
);
CREATE INDEX IF NOT EXISTS idx_edits_job ON edits(job_id);
CREATE INDEX IF NOT EXISTS idx_edits_chunk ON edits(chunk_id);

CREATE TABLE IF NOT EXISTS gaps (
    gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
    clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
    durable_document_id TEXT NOT NULL REFERENCES documents(durable_document_id),
    cause_edit_id INTEGER NOT NULL REFERENCES edits(edit_id),
    detected_at TEXT NOT NULL,
    narrative TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gaps_clause ON gaps(clause_id);

CREATE TABLE IF NOT EXISTS runs (
    run_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    ops_charged INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS usage_log (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    call TEXT NOT NULL,
    job_id TEXT,
    ops_charged INTEGER NOT NULL DEFAULT 0,
    was_billable INTEGER NOT NULL DEFAULT 0,
    monthly_used INTEGER,
    monthly_remaining INTEGER,
    quota_exhausted INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS our_jobs (
    job_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shortlists (
    shortlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    clause_id TEXT NOT NULL,
    durable_document_id TEXT,
    chunk_id TEXT,
    heading_path TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('local', 'search')),
    score REAL,
    discovered_at TEXT NOT NULL
);
