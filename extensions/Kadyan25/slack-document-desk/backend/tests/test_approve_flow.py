"""Idempotency guarantee: a duplicate button click (Slack's own retry-on-timeout
behavior firing the same interaction payload twice) must not double-apply."""
from app.db.session import SessionLocal
from app.db.models import ProcessedChange
from app.services.approvals import claim_change


def test_second_claim_for_same_change_is_rejected():
    db = SessionLocal()
    try:
        db.query(ProcessedChange).filter_by(job_id="job_idempotency_test").delete()
        db.commit()

        first = claim_change(db, "job_idempotency_test", "chg_1", approved=True)
        second = claim_change(db, "job_idempotency_test", "chg_1", approved=True)

        assert first is True
        assert second is False

        count = (
            db.query(ProcessedChange)
            .filter_by(job_id="job_idempotency_test", change_id="chg_1")
            .count()
        )
        assert count == 1
    finally:
        db.query(ProcessedChange).filter_by(job_id="job_idempotency_test").delete()
        db.commit()
        db.close()


def test_different_change_ids_on_same_job_both_claim_independently():
    db = SessionLocal()
    try:
        db.query(ProcessedChange).filter_by(job_id="job_batch_test").delete()
        db.commit()

        first = claim_change(db, "job_batch_test", "chg_a", approved=True)
        second = claim_change(db, "job_batch_test", "chg_b", approved=False)

        assert first is True
        assert second is True
    finally:
        db.query(ProcessedChange).filter_by(job_id="job_batch_test").delete()
        db.commit()
        db.close()
