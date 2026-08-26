"""Idempotency guarantee for Slack Events API deliveries: a retried delivery (same
event_id every time — confirmed live, see issues.md) must not repeat side effects.
Same pattern as test_approve_flow.py's claim_change, applied to file_shared/app_mention."""
from app.db.session import SessionLocal
from app.db.models import ProcessedSlackEvent
from app.services.event_dedup import claim_event


def test_second_claim_for_same_event_id_is_rejected():
    db = SessionLocal()
    try:
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_test").delete()
        db.commit()

        first = claim_event(db, "Ev_dedup_test")
        second = claim_event(db, "Ev_dedup_test")

        assert first is True
        assert second is False

        count = db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_test").count()
        assert count == 1
    finally:
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_test").delete()
        db.commit()
        db.close()


def test_different_event_ids_both_claim_independently():
    db = SessionLocal()
    try:
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_a").delete()
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_b").delete()
        db.commit()

        first = claim_event(db, "Ev_dedup_a")
        second = claim_event(db, "Ev_dedup_b")

        assert first is True
        assert second is True
    finally:
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_a").delete()
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_dedup_b").delete()
        db.commit()
        db.close()
