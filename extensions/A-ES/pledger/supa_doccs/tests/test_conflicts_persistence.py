"""Conflicts from incremental updates survive a real process restart.

Scenario mirrors the original Phase 5.1 test
(test_incremental_update.TestContradictionGoesToApprovalQueue): an
incremental update delivers a claim for the same section key with a
different value → contradiction → routed to the approval queue as an
item_type='conflict' item, never auto-applied.

Design decision exercised here: conflicts REUSE approval_queue (not a
new table) because the queue was designed with a 'conflict' item type,
already carries the pending→approved/rejected lifecycle with decisions,
and is Postgres-backed since migration 010.

Phase A runs the engine in one process; phase B is a brand-new process
that reads conflicts through the LIVE HTTP endpoint. Nothing is shared.

Requires PostgreSQL with migrations applied (docdb_test).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "CONFLICTS_TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/docdb_test",
)
ADMIN_DATABASE_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"

_BOOTSTRAP = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})
"""

# Original-5.1 scenario: existing rate claim contradicted by a new document.
_EXISTING_VALUE = "15% per annum"
_NEW_VALUE = "24% per annum"
_SECTION_KEY = "loan_agreement.interest_rate"
_DOC_A = "11111111-aaaa-aaaa-aaaa-111111111111"  # existing claim's source
_DOC_B = "22222222-bbbb-bbbb-bbbb-222222222222"  # contradicting document

_PHASE_TRIGGER_CONFLICT = f'''
import json, os, uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.pipeline.approval import ApprovalService
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.deliverable import Deliverable, SectionClaim
from src.pipeline.incremental import ClaimTypeRetrievalLayer, IncrementalUpdateEngine

engine = create_engine(os.environ["CONFLICTS_DATABASE_URL"])
session_factory = sessionmaker(bind=engine)

run_id = str(uuid.uuid4())
approval_service = ApprovalService(PostgresApprovalStore(session_factory))

# Existing deliverable state: interest_rate claimed as 15% per annum (doc A)
deliverable = Deliverable()
deliverable.add_claim(SectionClaim(
    claim_id="loan_agreement.interest_rate_001",
    claim_type="{_SECTION_KEY}",
    extracted_text="{_EXISTING_VALUE}",
    confidence=0.92,
    source_document_id="{_DOC_A}",
))
deliverable.compute_all_hashes()

# New document B claims the SAME field with a DIFFERENT value → contradiction
new_claims = [SectionClaim(
    claim_id="loan_agreement.interest_rate_002",
    claim_type="{_SECTION_KEY}",
    extracted_text="{_NEW_VALUE}",
    confidence=0.9,
    source_document_id="{_DOC_B}",
)]

eng = IncrementalUpdateEngine(
    retrieval_layer=ClaimTypeRetrievalLayer(),
    approval_service=approval_service,
    run_id=run_id,
)
result = eng.update(
    deliverable=deliverable,
    new_document_claims=new_claims,
    new_document_id="{_DOC_B}",
)

assert len(result.conflicts) == 1, f"expected 1 conflict, got {{result.conflicts}}"
assert len(result.approval_items_created) == 1
# The contradicting value must NOT have been applied
_sec = deliverable.sections["{_SECTION_KEY}"]
assert _sec.claims[0].extracted_text == "{_EXISTING_VALUE}"
assert "{_NEW_VALUE}" not in [c.extracted_text for c in _sec.claims]

print(json.dumps({{"run_id": run_id,
                   "conflict_item_id": result.approval_items_created[0]}}))
'''

_PHASE_VERIFY_VIA_ENDPOINT = '''
import json, os, sys

os.environ["DATABASE_URL"] = os.environ["CONFLICTS_DATABASE_URL"]

from fastapi.testclient import TestClient
from src.main import app  # lifespan wires SQL history store + PG approval store

run_id = sys.argv[1]
item_id = sys.argv[2]

with TestClient(app) as client:
    resp = client.get(f"/runs/{run_id}/conflicts")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Cross-check against the generic queue endpoint too
    qresp = client.get(f"/approval/runs/{run_id}/queue")
    assert qresp.status_code == 200
    queue_data = qresp.json()

print(json.dumps({"conflicts": data, "queue": {
    "total": queue_data["total"],
    "pending": queue_data["pending"],
}}))
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
    """Run a phase in a brand-new Python process; parse its last JSON line."""
    result = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP + script] + (args or []),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "CONFLICTS_DATABASE_URL": TEST_DATABASE_URL},
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Subprocess phase failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not reachable — restart test requires a live DB",
)


class TestConflictsSurviveProcessRestart:
    def test_conflict_retrievable_and_pending_after_restart(self, clean_test_db):
        # Process A: trigger the contradiction, then exit.
        phase1 = _run_phase(_PHASE_TRIGGER_CONFLICT)
        run_id = phase1["run_id"]
        item_id = phase1["conflict_item_id"]

        # Process A is gone. Phase B boots a fresh process, imports the
        # REAL app, and asks the LIVE endpoint.
        phase2 = _run_phase(_PHASE_VERIFY_VIA_ENDPOINT, [run_id, item_id])
        data = phase2["conflicts"]

        # The conflict survived the restart...
        assert data["total"] == 1
        assert data["pending"] == 1
        assert data["resolved"] == 0

        conflict = data["items"][0]
        assert conflict["id"] == item_id
        assert conflict["status"] == "pending"

        # ...still awaiting review — NOT auto-resolved by the restart
        assert conflict["decision"] is None
        assert conflict["reviewer_id"] is None
        assert conflict["justification"] is None

        # Full attribution survived: both sides of the contradiction
        payload = conflict["payload"]
        assert payload["section_key"] == _SECTION_KEY
        assert payload["existing_value"] == _EXISTING_VALUE
        assert payload["existing_source_document"] == _DOC_A
        assert payload["new_value"] == _NEW_VALUE
        assert payload["new_source_document"] == _DOC_B
        assert "different" in payload["reason"].lower() or "contradic" in payload["reason"].lower()

        # And it sits in the regular review queue too (one pending item).
        assert phase2["queue"]["total"] == 1
        assert phase2["queue"]["pending"] == 1

    def test_unknown_run_returns_empty_not_error(self, clean_test_db):
        phase = _run_phase(
            _PHASE_UNKNOWN_RUN, [str(uuid.uuid4())]
        )
        assert phase["status_code"] == 200
        assert phase["total"] == 0


_PHASE_UNKNOWN_RUN = '''
import json, os, sys

os.environ["DATABASE_URL"] = os.environ["CONFLICTS_DATABASE_URL"]

from fastapi.testclient import TestClient
from src.main import app

with TestClient(app) as client:
    resp = client.get(f"/runs/{sys.argv[1]}/conflicts")
print(json.dumps({
    "status_code": resp.status_code,
    "total": resp.json()["total"],
}))
'''
