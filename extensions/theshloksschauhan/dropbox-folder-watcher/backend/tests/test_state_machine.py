"""Tests for the state machine.

Proves:
- Valid transitions are enforced
- Invalid transitions are rejected
- Terminal states have no exits
- Every transition creates an audit event
- The claim_job atomic lease works
- FAILED -> QUEUED retry path works

All tests use in-memory SQLite — no database server needed.
"""
import uuid
import pytest

from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.models.event import Event
from app.services.state_machine import (
    transition,
    can_transition,
    get_allowed_transitions,
    is_terminal,
    InvalidTransition,
    VALID_TRANSITIONS,
    claim_job,
)


# ---------- Helpers ----------

def _create_job(db, status=JobStatus.DISCOVERED):
    """Create a minimal client -> folder_config -> job chain."""
    client = Client(id=uuid.uuid4(), name="Test", dropbox_folder_root="/test")
    db.add(client)
    db.flush()

    folder = FolderConfig(
        id=uuid.uuid4(), client_id=client.id,
        dropbox_folder_path=f"/test/inbox_{uuid.uuid4().hex[:8]}",
        treatment="normalize",
    )
    db.add(folder)
    db.flush()

    job = Job(
        id=uuid.uuid4(), client_id=client.id,
        folder_config_id=folder.id,
        source_path="/test/file.docx",
        source_rev=f"rev_{uuid.uuid4().hex[:8]}",
        status=status,
    )
    db.add(job)
    db.flush()
    return job


class TestValidTransitions:
    """Prove the happy-path state machine flow."""

    def test_full_lifecycle(self, db_session):
        """Walk through the complete lifecycle:
        DISCOVERED -> STABILIZING -> QUEUED -> PROCESSING ->
        REVIEW_PENDING -> APPROVED -> EXPORTING -> WRITING_BACK -> COMPLETED"""
        job = _create_job(db_session, JobStatus.DISCOVERED)

        states = [
            JobStatus.STABILIZING,
            JobStatus.QUEUED,
            JobStatus.PROCESSING,
            JobStatus.REVIEW_PENDING,
            JobStatus.APPROVED,
            JobStatus.EXPORTING,
            JobStatus.WRITING_BACK,
            JobStatus.COMPLETED,
        ]

        for target_state in states:
            job = transition(db_session, job, target_state, actor="test")
            assert job.status == target_state

        db_session.commit()

        # Verify audit trail has all transitions
        events = db_session.query(Event).filter(Event.job_id == job.id).all()
        assert len(events) == len(states)

    def test_rejection_path(self, db_session):
        """REVIEW_PENDING -> REJECTED is valid and terminal."""
        job = _create_job(db_session, JobStatus.REVIEW_PENDING)
        job = transition(db_session, job, JobStatus.REJECTED,
                        actor="human:reviewer@test.com",
                        detail="Changes not appropriate")
        assert job.status == JobStatus.REJECTED
        assert is_terminal(job)

    def test_failure_from_any_non_terminal(self, db_session):
        """Most states can transition to FAILED."""
        failing_states = [
            JobStatus.DISCOVERED, JobStatus.STABILIZING, JobStatus.QUEUED,
            JobStatus.PROCESSING, JobStatus.APPROVED,
            JobStatus.EXPORTING, JobStatus.WRITING_BACK,
        ]
        for state in failing_states:
            job = _create_job(db_session, state)
            job = transition(db_session, job, JobStatus.FAILED,
                           actor="system", detail=f"Test failure from {state.value}")
            assert job.status == JobStatus.FAILED
            assert job.error_message is not None

    def test_retry_from_failed(self, db_session):
        """FAILED -> QUEUED: retry path for recoverable failures."""
        job = _create_job(db_session, JobStatus.FAILED)
        job = transition(db_session, job, JobStatus.QUEUED,
                        actor="system", detail="Retrying after transient failure")
        assert job.status == JobStatus.QUEUED


class TestInvalidTransitions:
    """Prove that invalid transitions are rejected."""

    def test_completed_is_terminal(self, db_session):
        """COMPLETED has no valid transitions."""
        job = _create_job(db_session, JobStatus.COMPLETED)
        assert is_terminal(job)
        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.PROCESSING)

    def test_rejected_is_terminal(self, db_session):
        """REJECTED has no valid transitions."""
        job = _create_job(db_session, JobStatus.REJECTED)
        assert is_terminal(job)
        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.APPROVED)

    def test_cannot_skip_states(self, db_session):
        """DISCOVERED -> PROCESSING is invalid (must go through STABILIZING/QUEUED)."""
        job = _create_job(db_session, JobStatus.DISCOVERED)
        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.PROCESSING)

    def test_cannot_go_backwards(self, db_session):
        """PROCESSING -> QUEUED is invalid (no backwards transitions)."""
        job = _create_job(db_session, JobStatus.PROCESSING)
        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.QUEUED)

    def test_review_pending_only_approve_reject_or_fail(self, db_session):
        """REVIEW_PENDING can go to APPROVED, REJECTED, or FAILED."""
        job = _create_job(db_session, JobStatus.REVIEW_PENDING)

        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.PROCESSING)
        with pytest.raises(InvalidTransition):
            transition(db_session, job, JobStatus.COMPLETED)

        # But APPROVED, REJECTED, and FAILED are valid
        assert can_transition(job, JobStatus.APPROVED)
        assert can_transition(job, JobStatus.REJECTED)
        assert can_transition(job, JobStatus.FAILED)


class TestAuditTrail:
    """Prove every transition creates an immutable event record."""

    def test_event_recorded_on_transition(self, db_session):
        """Each transition creates exactly one Event."""
        job = _create_job(db_session, JobStatus.DISCOVERED)
        transition(db_session, job, JobStatus.STABILIZING, actor="watcher",
                  detail="File detected, starting debounce")
        db_session.commit()

        events = db_session.query(Event).filter(Event.job_id == job.id).all()
        assert len(events) == 1
        assert events[0].from_state == "DISCOVERED"
        assert events[0].to_state == "STABILIZING"
        assert events[0].actor == "watcher"
        assert events[0].detail == "File detected, starting debounce"

    def test_invalid_transition_creates_no_event(self, db_session):
        """A rejected transition should not leave a partial event."""
        job = _create_job(db_session, JobStatus.COMPLETED)
        try:
            transition(db_session, job, JobStatus.PROCESSING)
        except InvalidTransition:
            pass
        db_session.commit()

        events = db_session.query(Event).filter(Event.job_id == job.id).all()
        assert len(events) == 0

    def test_failure_detail_preserved(self, db_session):
        """FAILED transitions store the error detail on both the job and event."""
        job = _create_job(db_session, JobStatus.PROCESSING)
        error_msg = "SuperDocs API returned 500"
        transition(db_session, job, JobStatus.FAILED, actor="worker-1",
                  detail=error_msg)
        db_session.commit()

        assert job.error_message == error_msg
        event = db_session.query(Event).filter(Event.job_id == job.id).first()
        assert event.detail == error_msg


class TestTransitionHelpers:
    """Test utility functions."""

    def test_can_transition_true(self, db_session):
        job = _create_job(db_session, JobStatus.QUEUED)
        assert can_transition(job, JobStatus.PROCESSING) is True

    def test_can_transition_false(self, db_session):
        job = _create_job(db_session, JobStatus.QUEUED)
        assert can_transition(job, JobStatus.COMPLETED) is False

    def test_get_allowed_transitions(self, db_session):
        job = _create_job(db_session, JobStatus.REVIEW_PENDING)
        allowed = get_allowed_transitions(job)
        assert allowed == {JobStatus.APPROVED, JobStatus.REJECTED, JobStatus.FAILED}

    def test_all_states_have_transition_entry(self):
        """Every JobStatus should appear in the transition map."""
        for status in JobStatus:
            assert status in VALID_TRANSITIONS, f"{status} missing from VALID_TRANSITIONS"


class TestClaimLease:
    def test_second_claim_loses(self, db_session):
        job = _create_job(db_session, JobStatus.QUEUED)
        db_session.commit()

        first = claim_job(db_session, job.id, "worker-a")
        second = claim_job(db_session, job.id, "worker-b")

        assert first is not None
        assert first.locked_by == "worker-a"
        assert first.status == JobStatus.PROCESSING
        assert second is None

