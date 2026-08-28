"""Durability tests for the Postgres-backed approval store.

Invariant (docs/invariants.md §5, hardened): the approval queue and any
decisions already made survive a full PROCESS RESTART — not just the
replacement of in-app state. Each phase below runs in its own Python
subprocess with its own SQLAlchemy engine; the parent test process never
holds queue objects across phases.

Requires a live PostgreSQL instance (docker compose up postgres).
Uses the dedicated docdb_test database so production data is untouched.
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
    "APPROVAL_TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/docdb_test",
)
ADMIN_DATABASE_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"

_SUBPROCESS_BOOTSTRAP = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})
"""

# ---------------------------------------------------------------------------
# Phase scripts (executed inside fresh subprocesses)
# ---------------------------------------------------------------------------

_PHASE_SEED_AND_DECIDE = '''
import json, os, uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.approval import DecisionValue, QueueItem

engine = create_engine(os.environ["APPROVAL_DATABASE_URL"])
store = PostgresApprovalStore(sessionmaker(bind=engine))

run_id = str(uuid.uuid4())
item_a = QueueItem(
    id=str(uuid.uuid4()), run_id=run_id, item_type="finding",
    payload={"claim_text": "principal is 100000 USD", "confidence": 0.93},
)
item_b = QueueItem(
    id=str(uuid.uuid4()), run_id=run_id, item_type="conflict",
    payload={"claim_text": "interest is 8.5 percent", "rule_id": "RULE-5"},
)
item_c = QueueItem(
    id=str(uuid.uuid4()), run_id=run_id, item_type="finding",
    payload={"claim_text": "term is 36 months"},
)
for it in (item_a, item_b, item_c):
    store.enqueue(it)

# One decision before the restart: approve item A.
store.record_decision(item_a.id, DecisionValue.APPROVED,
                      reviewer_id="reviewer-1",
                      justification="Verified against source span")

print(json.dumps({"run_id": run_id,
                  "ids": [item_a.id, item_b.id, item_c.id]}))
'''

_PHASE_SEED_ONLY = '''
import json, os, uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.approval import QueueItem

engine = create_engine(os.environ["APPROVAL_DATABASE_URL"])
store = PostgresApprovalStore(sessionmaker(bind=engine))

run_id = str(uuid.uuid4())
ix = QueueItem(id=str(uuid.uuid4()), run_id=run_id,
               item_type="finding",
               payload={"n": 1, "deep": {"a": [1, 2, 3]}})
iy = QueueItem(id=str(uuid.uuid4()), run_id=run_id,
               item_type="proposed_update",
               payload={"section": "terms"})
store.enqueue(ix)
store.enqueue(iy)
print(json.dumps({"run_id": run_id, "ids": [ix.id, iy.id]}))
'''

_PHASE_DECIDE = '''
import json, os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.approval import DecisionValue

engine = create_engine(os.environ["APPROVAL_DATABASE_URL"])
store = PostgresApprovalStore(sessionmaker(bind=engine))

item = store.record_decision(
    sys.argv[1], DecisionValue.APPROVED,
    reviewer_id="reviewer-2", justification="Decided in a separate process",
)
print(json.dumps({"success": True, "status": item.status.value}))
'''

_PHASE_READ_FULL = '''
import json, os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.pipeline.approval_postgres import PostgresApprovalStore

engine = create_engine(os.environ["APPROVAL_DATABASE_URL"])
store = PostgresApprovalStore(sessionmaker(bind=engine))

run_id = sys.argv[1]
items = {i.id: i for i in store.get_all_for_run(run_id)}

def dump(i):
    return {
        "id": i.id, "status": i.status.value,
        "item_type": i.item_type,
        "decision": i.decision.value if i.decision else None,
        "reviewer_id": i.reviewer_id,
        "justification": i.justification,
        "payload": i.payload,
        "queued_at": i.queued_at.isoformat(),
        "decided_at": i.decided_at.isoformat() if i.decided_at else None,
    }

print(json.dumps({
    "items": {k: dump(v) for k, v in items.items()},
    "pending_ids": sorted(i.id for i in store.get_pending_for_run(run_id)),
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
    """Apply pending migrations to the test database (idempotent)."""
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
            sql_text = path.read_text(encoding="utf-8")
            cleaned = re.sub(
                r"^\s*(BEGIN|COMMIT)\s*;\s*$", "", sql_text,
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
    """Ensure docdb_test exists with migrations applied."""
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
    """Run a phase in a brand-new Python process; parse its last JSON line.

    The subprocess constructs its own engine from scratch — nothing is
    shared with the parent test process or prior phases.
    """
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_BOOTSTRAP + script] + (args or []),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, "APPROVAL_DATABASE_URL": TEST_DATABASE_URL},
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Subprocess phase failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not reachable — durability test requires a live DB",
)


class TestApprovalSurvivesProcessRestart:
    """The Phase 2.3 invariant for real: state survives process death."""

    def test_queue_and_decisions_survive_full_process_restart(
        self, clean_test_db
    ):
        # Phase 1 (process A): seed 3 items, decide one, exit.
        phase1 = _run_phase(_PHASE_SEED_AND_DECIDE)
        run_id = phase1["run_id"]
        id_a, id_b, id_c = phase1["ids"]

        # Process A's interpreter is fully gone at this point.
        # Phase 2 boots a brand-new process to read the queue back.
        phase2 = _run_phase(_PHASE_READ_FULL, [run_id])
        items = phase2["items"]

        # All three items survived the restart.
        assert set(items.keys()) == {id_a, id_b, id_c}

        # The pre-restart decision survived intact.
        a = items[id_a]
        assert a["status"] == "approved"
        assert a["decision"] == "approved"
        assert a["reviewer_id"] == "reviewer-1"
        assert a["justification"] == "Verified against source span"
        assert a["decided_at"] is not None

        # Undecided items are still pending, payloads intact.
        b = items[id_b]
        assert b["status"] == "pending"
        assert b["decision"] is None
        assert b["payload"]["claim_text"] == "interest is 8.5 percent"
        assert b["payload"]["rule_id"] == "RULE-5"

        c = items[id_c]
        assert c["status"] == "pending"

        assert phase2["pending_ids"] == sorted([id_b, id_c])

    def test_decision_from_middle_process_visible_to_later_process(
        self, clean_test_db
    ):
        # Process A: seed two items.
        phase1 = _run_phase(_PHASE_SEED_ONLY)
        run_id = phase1["run_id"]
        id_x, id_y = phase1["ids"]

        # Process B: decide item X, then exit.
        phase2 = _run_phase(_PHASE_DECIDE, [id_x])
        assert phase2["success"] is True

        # Process C: seeding AND process B's decision both still visible.
        phase3 = _run_phase(_PHASE_READ_FULL, [run_id])
        items = phase3["items"]

        assert items[id_x]["status"] == "approved"
        assert items[id_x]["decision"] == "approved"
        assert items[id_x]["reviewer_id"] == "reviewer-2"
        assert items[id_x]["payload"]["deep"] == {"a": [1, 2, 3]}
        assert items[id_y]["status"] == "pending"
        assert items[id_y]["item_type"] == "proposed_update"
        assert phase3["pending_ids"] == [id_y]

    def test_uuid_run_ids_isolated_between_runs(self, clean_test_db):
        # Two separate runs must not see each other's items.
        p1 = _run_phase(_PHASE_SEED_ONLY)
        p2 = _run_phase(_PHASE_SEED_ONLY)

        r1 = _run_phase(_PHASE_READ_FULL, [p1["run_id"]])
        r2 = _run_phase(_PHASE_READ_FULL, [p2["run_id"]])

        assert set(r1["items"].keys()) == set(p1["ids"])
        assert set(r2["items"].keys()) == set(p2["ids"])
