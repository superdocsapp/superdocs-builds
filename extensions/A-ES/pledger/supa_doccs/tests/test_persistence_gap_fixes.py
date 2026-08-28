"""B-fix followups: approval enqueue dedup + persistence-gap visibility.

1. _node_human_review invoked twice for the same run/claim must yield
   exactly one pending item (same dedup guarantee as populate-queue).
2. A durability write failure (claims or audit_events) after one retry
   must mark the run so it ends as 'completed_with_persistence_gap',
   visible via the /runs list endpoint — never a plain 'completed'.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.pipeline.approval import ApprovalService, InMemoryApprovalStore, ItemStatus
from src.pipeline.state import create_initial_state
from src.pipeline.config import load_config


# ---------------------------------------------------------------------------
# Fix 1: enqueue dedup at the primary site
# ---------------------------------------------------------------------------


def _state_for(claim_ids: list[str]) -> dict:
    state = create_initial_state(
        run_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        config=load_config(),
    )
    state["queue_buckets"] = {"auto_approve": [], "escalate": list(claim_ids), "auto_reject": []}
    state["claims"] = [
        {"claim_id": cid, "claim_text": f"claim {cid}", "confidence": 0.8,
         "citation_status": "grounded"}
        for cid in claim_ids
    ]
    return state


class TestHumanReviewEnqueueDedup:
    def test_double_invocation_yields_single_pending_item(self):
        from src.pipeline.demo_executor import _node_human_review
        from src.pipeline.approval_api import set_approval_service

        service = ApprovalService(InMemoryApprovalStore())
        set_approval_service(service)
        try:
            run_id = str(uuid.uuid4())
            ctx = {"run_id": run_id}
            state = _state_for(["claim-1"])

            asyncio.run(_node_human_review(state, ctx))
            asyncio.run(_node_human_review(state, ctx))

            pending = service.get_pending(run_id)
            assert len(pending) == 1
            assert pending[0].status == ItemStatus.PENDING
            assert pending[0].payload["details"]["claim_id"] == "claim-1"
        finally:
            set_approval_service(None)

    def test_distinct_claims_still_enqueued_after_dedup(self):
        from src.pipeline.demo_executor import _node_human_review
        from src.pipeline.approval_api import set_approval_service

        service = ApprovalService(InMemoryApprovalStore())
        set_approval_service(service)
        try:
            run_id = str(uuid.uuid4())
            ctx = {"run_id": run_id}

            asyncio.run(_node_human_review(_state_for(["claim-1"]), ctx))
            asyncio.run(_node_human_review(_state_for(["claim-2"]), ctx))

            assert len(service.get_pending(run_id)) == 2
        finally:
            set_approval_service(None)


# ---------------------------------------------------------------------------
# Fix 2: persistence gap → distinct run status, visible in /runs
# ---------------------------------------------------------------------------


class _ExplodingSessionFactory:
    """session_factory() raises immediately — simulates DB outage."""

    def __call__(self):
        raise RuntimeError("simulated durability write failure")


def test_extract_claims_marks_gap_when_persistence_fails(monkeypatch):
    """Claims-table write failing twice ⇒ node completes but flags the gap."""
    from src.pipeline import demo_executor
    from src.pipeline import source_linker as sl

    calls = {"n": 0}

    def always_fail(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(sl, "persist_extraction_results", always_fail)

    chunks = [{"index": 0, "text": "principal is 100000 USD",
               "start_offset": 0, "end_offset": 24}]
    state = create_initial_state(
        run_id=str(uuid.uuid4()), document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()), config=load_config(),
    )
    state["chunks"] = chunks
    state["classification_label"] = None  # forces LLM path in demo node

    async def fake_llm(**kwargs):
        return (
            {"claims": [{"claim_text": "principal is 100000 USD",
                         "confidence": 0.9, "category": "amount"}]},
            10, 20,
        )

    monkeypatch.setattr(demo_executor, "chat_completion_json", fake_llm)

    result = asyncio.run(
        demo_executor._node_extract_claims(state, {"run_id": state["run_id"],
                                                   "session_factory": _ExplodingSessionFactory()})
    )

    assert result["node_status"] == "completed"          # node still succeeds
    assert result["_persistence_gap"] is True            # but the gap is flagged
    assert calls["n"] == 2                               # exactly ONE retry


def test_extract_claims_retry_succeeds_no_gap(monkeypatch):
    """First attempt fails, retry succeeds ⇒ no gap flag."""
    from src.pipeline import demo_executor
    from src.pipeline import source_linker as sl

    attempts = {"n": 0}

    def fails_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return len(kwargs.get("claims", [])) if "claims" in kwargs else 1

    monkeypatch.setattr(sl, "persist_extraction_results", fails_once)

    chunks = [{"index": 0, "text": "rate is 15%", "start_offset": 0, "end_offset": 11}]
    state = create_initial_state(
        run_id=str(uuid.uuid4()), document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()), config=load_config(),
    )
    state["chunks"] = chunks

    async def fake_llm(**kwargs):
        return ({"claims": [{"claim_text": "rate is 15%",
                             "confidence": 0.9, "category": "rate"}]}, 10, 20)

    monkeypatch.setattr(demo_executor, "chat_completion_json", fake_llm)

    result = asyncio.run(
        demo_executor._node_extract_claims(state, {"run_id": state["run_id"],
                                                   "session_factory": _ExplodingSessionFactory()})
    )
    # second attempt went through a REAL factory? No — factory explodes on
    # session creation, but our patched persist fn never touches it.
    assert result["_persistence_gap"] is not True
    assert attempts["n"] == 2


def test_history_emit_failure_flags_gap():
    """_emit_history_event retries once then marks the gap."""
    from src.pipeline import demo_executor

    state = {"_persistence_gap": False}

    def always_raises(sf, **kwargs):
        raise RuntimeError("audit down")

    demo_executor._emit_history_event(always_raises, object(), state, run_id="r")
    assert state["_persistence_gap"] is True

    state_ok = {"_persistence_gap": False}
    flaky_calls = {"n": 0}

    def fails_then_succeeds(sf, **kwargs):
        flaky_calls["n"] += 1
        if flaky_calls["n"] == 1:
            raise RuntimeError("blip")

    demo_executor._emit_history_event(fails_then_succeeds, object(), state_ok, run_id="r")
    assert state_ok["_persistence_gap"] is False
    assert flaky_calls["n"] == 2


def test_resolve_final_status():
    from src.pipeline.demo_executor import _resolve_final_status

    assert _resolve_final_status({}) == "completed"
    assert _resolve_final_status({"_persistence_gap": False}) == "completed"
    assert _resolve_final_status({"_persistence_gap": True}) == (
        "completed_with_persistence_gap"
    )


class TestGapStatusVisibleInRunsList:
    @pytest.fixture()
    def client(self):
        from src.main import app

        with TestClient(app) as c:
            yield c

    def test_update_run_status_writes_new_status(self):
        """The executor's status writer accepts and persists the gap status."""
        from src.pipeline.demo_executor import _update_run_status

        engine = create_engine(TEST_DB_URL)
        _ensure_db_and_migrations()
        sf = sessionmaker(bind=engine)
        run_id = str(uuid.uuid4())

        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO runs (id, status, initiator, config_snapshot) "
                "VALUES (CAST(:r AS uuid), 'pending', 'gap-test', '{}'::jsonb)"
            ), {"r": run_id})

        asyncio.run(_update_run_status(sf, run_id, "running"))
        asyncio.run(_update_run_status(sf, run_id, "completed_with_persistence_gap"))

        with engine.connect() as c:
            row = c.execute(text(
                "SELECT status, ended_at FROM runs WHERE id = CAST(:r AS uuid)"
            ), {"r": run_id}).first()
        assert row[0] == "completed_with_persistence_gap"
        assert row[1] is not None  # treated as terminal

        with engine.begin() as c:
            c.execute(text("DELETE FROM runs WHERE id = CAST(:r AS uuid)"), {"r": run_id})

    def test_runs_list_surfaces_gap_status(self, client):
        """A reviewer sees the distinction in GET /runs without opening details."""
        from src.database import SessionLocal
        from sqlalchemy import text as sqltext

        run_id = str(uuid.uuid4())
        with SessionLocal() as s:
            s.execute(sqltext(
                "INSERT INTO runs (id, status, initiator, config_snapshot) "
                "VALUES (CAST(:id AS uuid), 'completed_with_persistence_gap', "
                "'gap-test', '{}'::jsonb)"
            ), {"id": run_id})
            s.commit()
        try:
            resp = client.get("/runs")
            assert resp.status_code == 200
            statuses = {r["id"]: r["status"] for r in resp.json()}
            assert statuses[run_id] == "completed_with_persistence_gap"
            assert "completed_with_persistence_gap" in set(statuses.values())
        finally:
            with SessionLocal() as s:
                s.execute(sqltext("DELETE FROM runs WHERE id = CAST(:id AS uuid)"),
                          {"id": run_id})
                s.commit()


TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/docdb_test"


def _ensure_db_and_migrations():
    import psycopg2
    import re
    from pathlib import Path

    admin = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    dbname = TEST_DB_URL.rsplit("/", 1)[-1]
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{dbname}"')
    conn.close()

    engine = create_engine(TEST_DB_URL)
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    pattern = re.compile(r"^(\d+)_.+\.sql$")
    files = sorted(
        (int(m.group(1)), e)
        for e in migrations_dir.iterdir()
        if (m := pattern.match(e.name)) and e.is_file()
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
        applied = {row[0] for row in c.execute(
            text("SELECT id FROM schema_migrations")).fetchall()}
        for mid, path in files:
            if mid <= max(applied, default=-1):
                continue
            cleaned = re.sub(r"^\s*(BEGIN|COMMIT)\s*;\s*$", "",
                             path.read_text(encoding="utf-8"),
                             flags=re.MULTILINE | re.IGNORECASE)
            c.execute(text(cleaned))
            c.execute(text("INSERT INTO schema_migrations (id, filename) VALUES (:id,:fn)"),
                      {"id": mid, "fn": path.name})
            c.commit()
    engine.dispose()
