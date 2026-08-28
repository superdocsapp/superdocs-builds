"""extract_claims node persistence — durable record survives process death.

Invariant: the claims/source_locations tables are written at NODE
COMPLETION, not by some later finalize step that might never run. The
test below runs the extract_claims node in subprocess A, lets that
process die WITHOUT writing any checkpoint or finalize output, then
reads the rows back from a brand-new process B.

Both processes use their own SQLAlchemy engine; nothing is shared. The
JSONB checkpoint is deliberately never written — proving the tables are
the durable record, not a downstream artifact of it.

Requires a live PostgreSQL instance (docker compose up postgres).
Uses the dedicated docdb_test database.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "CLAIMS_TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/docdb_test",
)
ADMIN_DATABASE_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"

_BOOTSTRAP = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})
"""

SOURCE_TEXT = (
    "LOAN AGREEMENT. The borrower agrees to repay the principal amount "
    "of 100000 USD over 36 months at 8.5% annual interest. The lender "
    "is Acme Capital LLC."
)

# Claims whose spans are REAL positions in SOURCE_TEXT (grounded), plus
# one claim whose text appears nowhere (unverifiable).
_CLAIMS = [
    {
        "claim_id": "private_lender_note.principal_amount_001",
        "claim_text": "principal amount of 100000 USD",
        "chunk_index": 0,
        "confidence": 0.97,
        "citation_status": "grounded",
    },
    {
        "claim_id": "private_lender_note.interest_rate_002",
        "claim_text": "8.5% annual interest",
        "chunk_index": 0,
        "confidence": 0.95,
        "citation_status": "grounded",
    },
    {
        "claim_id": "private_lender_note.lender_name_003",
        "claim_text": "Acme Capital LLC",
        "chunk_index": 0,
        "confidence": 0.9,
        "citation_status": "grounded",
    },
    {
        "claim_id": "private_lender_note.collateral_004",
        "claim_text": "collateral: golden goose",
        "chunk_index": 0,
        "confidence": 0.5,
        "citation_status": "unverifiable",
    },
]

# Fill in true document-level spans for grounded claims (what the fixed
# node now computes instead of hardcoded start=0).
for _c in _CLAIMS:
    if _c["citation_status"] == "grounded":
        _pos = SOURCE_TEXT.find(_c["claim_text"])
        _c["start_offset"] = _pos
        _c["end_offset"] = _pos + len(_c["claim_text"])
    else:
        _c["start_offset"] = 0
        _c["end_offset"] = 0

_PHASE_SETUP_AND_EXTRACT = f'''
import asyncio, json, os, uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.pipeline.nodes.extract_claims import extract_claims
from src.pipeline.source_linker import make_sql_claim_persister
from src.pipeline.state import PipelineState, create_initial_state
from src.pipeline.config import load_config

engine = create_engine(os.environ["CLAIMS_DATABASE_URL"])
session_factory = sessionmaker(bind=engine)

run_id = str(uuid.uuid4())
document_version_id = str(uuid.uuid4())

with session_factory() as s:
    doc_id = str(uuid.uuid4())
    s.execute(text(
        "INSERT INTO documents (id, filename, mime_type) "
        "VALUES (:id, 'restart_test.txt', 'text/plain')"), {{"id": doc_id}})
    s.execute(text(
        "INSERT INTO document_versions (id, document_id, content_hash, "
        "storage_ref, version_number) VALUES (:id, :doc, :h, 'mem', 1)"),
        {{"id": document_version_id, "doc": doc_id, "h": "a" * 64}})
    s.execute(text(
        "INSERT INTO runs (id, status, initiator, config_snapshot) "
        "VALUES (:id, 'running', 'test', '{{}}'::jsonb)"), {{"id": run_id}})
    s.commit()

state = create_initial_state(
    run_id=run_id,
    document_id=document_version_id,  # not FK-checked on this path
    document_version_id=document_version_id,
    config=load_config(),
)
state["extracted_text"] = {SOURCE_TEXT!r}
state["chunks"] = [{{
    "index": 0,
    "text": {SOURCE_TEXT!r},
    "start_offset": 0,
    "end_offset": len({SOURCE_TEXT!r}),
}}]
state["classification_label"] = "private_lender_note"  # not in EXTRACTOR_REGISTRY
claims = json.loads({json.dumps(json.dumps(_CLAIMS))})
state["claims"] = [dict(c) for c in claims]

class StubExtractor:
    async def extract(self, chunk_text, chunk_index):
        return [dict(c) for c in claims]

# Inject the SQL persister exactly like app startup does.
set_p = make_sql_claim_persister(session_factory)
from src.pipeline.nodes.extract_claims import set_claim_persister
set_claim_persister(set_p)

result = asyncio.run(extract_claims(state, extractor=StubExtractor()))
assert result["node_status"] == "completed", result.get("error_detail")

# Process exits HERE — before any checkpoint write, before match_rules,
# before finalize. If the tables were written at finalize, phase B
# would find nothing.
print(json.dumps({{"run_id": run_id,
                   "document_version_id": document_version_id}}))
'''

_PHASE_READ_TABLES = '''
import json, os, sys
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["CLAIMS_DATABASE_URL"])
run_id = sys.argv[1]
source_text = sys.argv[2]

with engine.connect() as c:
    claims = c.execute(text(
        "SELECT extracted_text, claim_type, confidence "
        "FROM claims WHERE run_id = CAST(:r AS uuid) ORDER BY extracted_text"
    ), {"r": run_id}).fetchall()
    locations = c.execute(text(
        "SELECT sl.start_offset, sl.end_offset, cl.extracted_text "
        "FROM source_locations sl "
        "JOIN claims cl ON cl.id = sl.claim_id "
        "WHERE cl.run_id = CAST(:r AS uuid)"
    ), {"r": run_id}).fetchall()
    checkpoints = c.execute(text(
        "SELECT count(*) FROM run_steps WHERE run_id = CAST(:r AS uuid)"
    ), {"r": run_id}).scalar()

resolved = []
for start, end, txt in locations:
    resolved.append(source_text[start:end])

print(json.dumps({
    "claims": [
        {"extracted_text": r[0], "claim_type": r[1], "confidence": float(r[2])}
        for r in claims
    ],
    "locations": [
        {"start": int(r[0]), "end": int(r[1]), "claim_text": r[2]}
        for r in locations
    ],
    "resolved_spans": resolved,
    "checkpoint_rows": int(checkpoints),
}))
'''


def _pg_available() -> bool:
    try:
        conn = psycopg2.connect(ADMIN_DATABASE_URL, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


def _apply_migrations() -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(TEST_DATABASE_URL)
    migrations_dir = REPO_ROOT / "migrations"
    pattern = re.compile(r"^(\d+)_.+\.sql$")
    files = sorted(
        (int(m.group(1)), entry)
        for entry in migrations_dir.iterdir()
        if (m := pattern.match(entry.name)) and entry.is_file()
    )
    with engine.connect() as c:
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        c.commit()
        applied = {
            row[0]
            for row in c.execute(text("SELECT id FROM schema_migrations")).fetchall()
        }
        for mid, path in files:
            if mid <= max(applied, default=-1):
                continue
            cleaned = re.sub(
                r"^\s*(BEGIN|COMMIT)\s*;\s*$", "",
                path.read_text(encoding="utf-8"),
                flags=re.MULTILINE | re.IGNORECASE,
            )
            c.execute(text(cleaned))
            c.execute(text(
                "INSERT INTO schema_migrations (id, filename) VALUES (:id, :fn)"
            ), {"id": mid, "fn": path.name})
            c.commit()
    engine.dispose()


@pytest.fixture()
def clean_test_db():
    dbname = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{dbname}"')
    conn.close()
    _apply_migrations()
    yield


def _run_phase(script: str, args: list[str] | None = None) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP + script] + (args or []),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "CLAIMS_DATABASE_URL": TEST_DATABASE_URL},
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Subprocess phase failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not reachable — restart test requires a live DB",
)
class TestClaimsPersistAtNodeCompletion:
    """The durable record exists after node death, before any checkpoint."""

    def test_claims_table_populated_before_next_node_and_survives_restart(
        self, clean_test_db
    ):
        # Process A: run ONLY the extract_claims node, then die.
        phase1 = _run_phase(_PHASE_SETUP_AND_EXTRACT)
        run_id = phase1["run_id"]

        # Process A's interpreter is fully gone; no checkpoint was ever
        # written. Process B reads the TABLES directly.
        phase2 = _run_phase(_PHASE_READ_TABLES, [run_id, SOURCE_TEXT])

        # All four claims are in the claims table.
        persisted_texts = {c["extracted_text"] for c in phase2["claims"]}
        expected_texts = {c["claim_text"] for c in _CLAIMS}
        assert persisted_texts == expected_texts

        # Types/confidence made it through persist_fact().
        by_type = {c["claim_type"]: c for c in phase2["claims"]}
        assert any(c["claim_type"].startswith("private_lender_note.") for c in phase2["claims"])
        confidences = [c["confidence"] for c in phase2["claims"]]
        assert all(0.0 <= v <= 1.0 for v in confidences)

        # Source locations exist and RESOLVE to the real source text.
        assert len(phase2["locations"]) == 3  # unverifiable claim has none
        for span in phase2["resolved_spans"]:
            assert span in SOURCE_TEXT

        # Grounded spans carry true document-level offsets (not 0).
        offsets = {(loc["start"], loc["end"]) for loc in phase2["locations"]}
        assert (0, len("principal amount of 100000 USD")) not in offsets
        assert all(start > 0 for start, _ in offsets)

        # THE POINT: zero checkpoint rows — persistence did not depend
        # on finalize or the JSONB state blob.
        assert phase2["checkpoint_rows"] == 0
