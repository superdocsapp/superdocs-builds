import tempfile

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.storage.sqlite_backend import SqliteHistoryStore, SqliteReviewQueue
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline
from app.workflow.review_queue import ReviewQueue

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Value: $84,000
"""


def make_pipeline(**kwargs):
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None, **kwargs)
    return box, sd, pipeline


def test_history_entries_carry_a_source_session_id():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    counterparty_entries = [e for e in report.history_entries if e.field_name == "counterparty_name"]
    assert len(counterparty_entries) == 1
    entry = counterparty_entries[0]
    assert entry.source_session_id is not None
    assert entry.source_session_id.startswith("sess-")


def test_different_fields_can_carry_different_session_ids():
    """Each stage runs its own SuperDocs chat() call with its own
    session -- doc_class comes from classify, counterparty_name from
    extract, normalized/retention_category from normalize. Provenance
    should reflect that, not collapse to one session for the whole
    run."""
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    report = pipeline.process("f1")

    by_field = {e.field_name: e.source_session_id for e in report.history_entries}
    assert by_field["doc_class"] != by_field["counterparty_name"]
    assert by_field["counterparty_name"] != by_field.get("normalized")


def test_low_confidence_field_review_entry_carries_source_session_id():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    pipeline.process("f1")

    pending = pipeline.review_queue.list_pending(file_id="f1")
    assert len(pending) == 1
    assert pending[0].field_name == "contract_value"
    assert pending[0].source_session_id is not None


def test_review_approval_preserves_original_session_id_in_history():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    pipeline.process("f1")
    review = pipeline.review_queue.list_pending(file_id="f1")[0]
    original_session = review.source_session_id

    pipeline.apply_review_decision(review.review_id, approve=True)

    history = pipeline.history.get_history("f1")
    approved_entries = [
        e for e in history if e.field_name == "contract_value" and e.reason == "review approved"
    ]
    assert len(approved_entries) == 1
    assert approved_entries[0].source_session_id == original_session


def test_apply_review_decision_feeds_the_calibration_tracker():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    pipeline.process("f1")
    review = pipeline.review_queue.list_pending(file_id="f1")[0]  # contract_value, low confidence

    pipeline.apply_review_decision(review.review_id, approve=True)

    rows = pipeline.calibration_tracker.bucket_report("contract_value")
    assert len(rows) == 1
    assert rows[0]["approved"] == 1
    assert rows[0]["total"] == 1


def test_suggest_thresholds_endpoint_over_http_after_accumulated_decisions():
    from fastapi.testclient import TestClient

    import app.api.main as m
    from app.api.main import app

    client = TestClient(app)
    ctx = m._tenants.context_for("default")
    for i in range(12):
        ctx.box.seed_file(f"thresh-http-{i}", f"c{i}.txt", CONTRACT_TEXT)
        client.post(f"/process/thresh-http-{i}")
        pending = ctx.pipeline.review_queue.list_pending(file_id=f"thresh-http-{i}")
        for r in pending:
            client.post(f"/reviews/{r.review_id}/approve")

    resp = client.get("/calibration-report/suggest-thresholds")
    assert resp.status_code == 200
    body = resp.json()
    assert "contract_value" in body
    assert body["contract_value"]["total_samples"] == 12


def test_calibration_tracker_accumulates_across_multiple_files_and_decisions():
    box, sd, pipeline = make_pipeline()
    for i in range(3):
        box.seed_file(f"f{i}", f"contract{i}.txt", CONTRACT_TEXT)
        pipeline.process(f"f{i}")
        review = pipeline.review_queue.list_pending(file_id=f"f{i}")[0]
        pipeline.apply_review_decision(review.review_id, approve=(i != 1))  # reject the middle one

    rows = pipeline.calibration_tracker.bucket_report("contract_value")
    assert rows[0]["total"] == 3
    assert rows[0]["approved"] == 2
    assert rows[0]["rejected"] == 1


def test_sqlite_history_store_persists_source_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/test.db"
        store = SqliteHistoryStore(db_path)
        store.record_diff(
            "f1", "sha1abc", {"counterparty_name": "Acme"}, reason="processed",
            session_ids={"counterparty_name": "sess-abc123"},
        )
        history = store.get_history("f1")
        assert history[0].source_session_id == "sess-abc123"

        # Re-opening the same db file (simulating a process restart)
        # still has it.
        reopened = SqliteHistoryStore(db_path)
        history2 = reopened.get_history("f1")
        assert history2[0].source_session_id == "sess-abc123"


def test_sqlite_review_queue_persists_source_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/test.db"
        store = SqliteReviewQueue(db_path)
        review = store.stage("f1", "sha1abc", "contract_value", "$1000", 0.5, source_session_id="sess-xyz")
        assert review.source_session_id == "sess-xyz"

        reopened = SqliteReviewQueue(db_path)
        fetched = reopened.get(review.review_id)
        assert fetched.source_session_id == "sess-xyz"


def test_in_memory_history_store_omits_session_id_when_not_supplied():
    """Backward compatible: callers that don't pass session_ids (or a
    key the run didn't populate, e.g. a value from human review vs. a
    live SuperDocs call) get an honest None, not a crash or a made-up
    value."""
    store = MetadataHistoryStore()
    entries = store.record_diff("f1", "sha1", {"some_field": "value"}, reason="processed")
    assert entries[0].source_session_id is None


def test_in_memory_review_queue_stage_without_session_id_defaults_to_none():
    rq = ReviewQueue()
    review = rq.stage("f1", "sha1", "contract_value", "$1000", 0.5)
    assert review.source_session_id is None


# --- hash chain, end to end through the pipeline and SQLite ----------------


def test_pipeline_run_produces_a_verifiable_hash_chain():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    pipeline.process("f1")
    result = pipeline.history.verify_history("f1")
    assert result.valid is True
    assert result.checked_count > 0


def test_reprocessing_extends_the_same_chain_validly():
    box, sd, pipeline = make_pipeline()
    box.seed_file("f1", "contract.txt", CONTRACT_TEXT)
    pipeline.process("f1")
    box.bump_version("f1", CONTRACT_TEXT + b"\nAmendment: extended term.", "2")
    pipeline.process("f1")
    result = pipeline.history.verify_history("f1")
    assert result.valid is True


def test_directly_editing_a_row_in_the_sqlite_history_table_is_detected():
    """Simulates exactly the threat model this feature exists for:
    someone with raw access to the .db file UPDATEs a row directly,
    bypassing record_diff entirely. verify_history() must catch it."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/test.db"
        store = SqliteHistoryStore(db_path)
        store.record_diff(
            "f1", "sha1abc", {"counterparty_name": "Acme", "contract_value": "$1000"}, reason="processed"
        )
        assert store.verify_history("f1").valid is True

        # Tamper: directly rewrite a stored value, as if bypassing the
        # application entirely (e.g. a rogue DB admin).
        store._conn.execute(
            "UPDATE history SET new_value = ? WHERE file_id = ? AND field_name = ?",
            ("$999999", "f1", "contract_value"),
        )
        store._conn.commit()

        result = store.verify_history("f1")
        assert result.valid is False
        assert "contract_value" in result.detail


def test_verify_endpoint_logic_reports_intact_and_broken_chains():
    """Exercises the same logic app.api.main's
    GET /files/{file_id}/history/verify calls, at the store level --
    this repo's existing tests consistently test through the
    store/pipeline layer rather than spinning up a TestClient with a
    tenant fixture, and this keeps the same pattern rather than
    inventing a new one."""
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteHistoryStore(f"{tmp}/test.db")
        store.record_diff("f1", "sha1", {"counterparty_name": "Acme"}, reason="processed")
        intact = store.verify_history("f1")
        assert intact.valid is True

        store._conn.execute(
            "UPDATE history SET reason = ? WHERE file_id = ?", ("tampered", "f1")
        )
        store._conn.commit()
        broken = store.verify_history("f1")
        assert broken.valid is False
        assert broken.first_break_index == 0


def test_verify_endpoint_over_http_reports_intact_chain_after_a_real_run():
    from fastapi.testclient import TestClient

    import app.api.main as m
    from app.api.main import app

    client = TestClient(app)
    m._tenants.context_for("default").box.seed_file("prov-http-1", "contract.pdf", CONTRACT_TEXT)
    process_resp = client.post("/process/prov-http-1")
    assert process_resp.status_code == 200

    verify_resp = client.get("/files/prov-http-1/history/verify")
    assert verify_resp.status_code == 200
    body = verify_resp.json()
    assert body["valid"] is True
    assert body["checked_count"] > 0
    assert body["first_break_index"] is None

    history_resp = client.get("/files/prov-http-1/history")
    changes = history_resp.json()["changes"]
    assert all(c["entry_hash"] for c in changes)
    assert any(c["source_session_id"] for c in changes)
