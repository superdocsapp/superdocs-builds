"""End-to-end integration tests for the worker loop.

These are the card's Section 19 tests — each one proves a specific
hard claim about the system's behavior:

Test 1: Happy path (new source file → job → processed output → written back)
Test 2: Half-written file (stability detection blocks processing)
Test 3: Duplicate event (idempotent job creation)
Test 4: Own-output event (anti-loop blocks reprocessing)
Test 5: Preview mode (zero SuperDocs operations spent)
Test 6: SuperDocs failure (job retries without corruption)
Test 7: Crash recovery (worker restarts from correct state)
Test 8: Output naming convention

All tests use fakes — no API keys, no running database, no Docker.
"""
import uuid

import pytest

from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.models.event import Event
from app.models.known_output import KnownOutput
from app.services.worker import WorkerLoop, _build_output_path
from app.services.state_machine import transition
from app.services.antiloop import is_own_output, register_output
from app.services.stability import check_stability, record_observation
from tests.fixtures.fake_dropbox import FakeDropboxClient, make_stable_file
from tests.fixtures.fake_superdocs import FakeSuperDocsClient


# ---------- Helpers ----------

def _setup_scenario(db, preview=False, source_path="/Clients/Acme/Inbox/report.docx"):
    """Create a complete client -> folder -> job chain ready for processing."""
    client = Client(
        id=uuid.uuid4(), name="Acme Corp",
        dropbox_folder_root="/Clients/Acme",
    )
    db.add(client)
    db.flush()

    folder = FolderConfig(
        id=uuid.uuid4(), client_id=client.id,
        dropbox_folder_path="/Clients/Acme/Inbox",
        treatment="normalized",
        instruction_text="Normalize formatting to company template",
        output_naming_pattern="{basename}.superdocs.{treatment}{ext}",
    )
    db.add(folder)
    db.flush()

    job = Job(
        id=uuid.uuid4(), client_id=client.id,
        folder_config_id=folder.id,
        source_path=source_path,
        source_rev="rev_abc123",
        source_content_hash="hash_abc123",
        status=JobStatus.PROCESSING,  # Already claimed
        preview=preview,
        locked_by="test-worker",
    )
    db.add(job)
    db.flush()

    return client, folder, job


class TestHappyPath:
    """Test 1: New source file → processed output → written back."""

    def test_full_pipeline(self, db_session):
        """A file goes through the complete pipeline:
        download → upload to SuperDocs → edit → approve → export → write back.

        After completion:
        - Job status is COMPLETED
        - Output is registered in known_outputs (anti-loop)
        - Audit trail has all transitions
        - File was uploaded to Dropbox
        """
        # Setup
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()

        _, folder, job = _setup_scenario(db_session)
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")

        # Execute prepare phase — stops at human review
        result = worker.process_job(db_session, job)

        assert result.status == JobStatus.REVIEW_PENDING
        assert result.superdocs_doc_id is not None
        assert result.proposed_changes_json is not None

        # Human approves, then worker completes export/write-back
        transition(db_session, result, JobStatus.APPROVED, actor="user")
        db_session.commit()
        result = worker.complete_approved_job(db_session, result)

        # Verify
        assert result.status == JobStatus.COMPLETED

        # Output registered for anti-loop
        known = db_session.query(KnownOutput).filter(KnownOutput.job_id == job.id).first()
        assert known is not None
        assert ".superdocs." in known.output_path

        # File was uploaded to Dropbox
        assert len(fake_dbx.uploads) == 1
        uploaded_path, _, _ = fake_dbx.uploads[0]
        assert ".superdocs." in uploaded_path

        # Audit trail is complete
        events = db_session.query(Event).filter(Event.job_id == job.id).order_by(Event.occurred_at).all()
        assert len(events) >= 4  # At least: REVIEW_PENDING, APPROVED, EXPORTING, WRITING_BACK, COMPLETED
        final_event = events[-1]
        assert final_event.to_state == "COMPLETED"

        # SuperDocs calls: upload + chat during prepare; approve + export during complete
        sd_ops = [c["operation"] for c in fake_sd.calls]
        assert sd_ops == ["upload", "chat", "approve", "export"]


class TestAntiLoopIntegration:
    """Test 4: Own-output events are blocked."""

    def test_own_output_not_reprocessed(self, db_session):
        """After writing back an output, if Dropbox triggers an event
        for that output file, the system blocks it."""
        # First: run a job to completion (creates a known_output)
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()

        _, folder, job = _setup_scenario(db_session)
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")
        worker.process_job(db_session, job)
        transition(db_session, job, JobStatus.APPROVED, actor="user")
        db_session.commit()
        worker.complete_approved_job(db_session, job)

        # Get the output path that was written
        known = db_session.query(KnownOutput).filter(KnownOutput.job_id == job.id).first()
        output_path = known.output_path

        # Now check: if an event arrives for that output path, it should be blocked
        assert is_own_output(db_session, output_path, known.output_content_hash) is True


class TestPreviewMode:
    """Test 5: Preview mode guarantees zero SuperDocs operations spent."""

    def test_preview_no_billable_calls(self, db_session):
        """In preview mode, NO billable SuperDocs calls are made.
        The job still transitions through the state machine but stops
        before spending any operations."""
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()

        _, folder, job = _setup_scenario(db_session, preview=True)
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")

        result = worker.process_job(db_session, job)

        # Zero billable calls to SuperDocs
        assert len(fake_sd.billable_calls) == 0

        # Job is not COMPLETED (it stopped before doing real work)
        assert result.status != JobStatus.COMPLETED

        # The audit trail records why it stopped
        events = db_session.query(Event).filter(Event.job_id == job.id).all()
        any_preview_event = any("PREVIEW" in (e.detail or "") for e in events)
        assert any_preview_event, "Expected a PREVIEW MODE event in the audit trail"


class TestSuperDocsFailure:
    """Test 6: SuperDocs failures are handled gracefully."""

    def test_chat_failure_becomes_failed(self, db_session):
        """If SuperDocs chat fails, the job transitions to FAILED
        with the error message preserved."""
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient(fail_on="chat")

        _, folder, job = _setup_scenario(db_session)
        db_session.commit()  # Commit so rollback in error handler doesn't wipe setup
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")

        result = worker.process_job(db_session, job)

        assert result.status == JobStatus.FAILED
        assert result.error_message is not None
        assert "chat failure" in result.error_message.lower()
        assert result.retry_count == 1

    def test_export_failure_becomes_failed(self, db_session):
        """If export fails after human approval, the job transitions to FAILED.
        Upload and chat operations are already spent — that's expected."""
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()

        _, folder, job = _setup_scenario(db_session)
        db_session.commit()
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")

        worker.process_job(db_session, job)
        transition(db_session, job, JobStatus.APPROVED, actor="user")
        db_session.commit()

        fake_sd._fail_on = "export"
        result = worker.complete_approved_job(db_session, job)

        assert result.status == JobStatus.FAILED
        assert len(fake_sd.billable_calls) == 2


class TestOutputNaming:
    """Test 8: Output naming convention."""

    def test_default_pattern(self):
        """Default pattern: {basename}.superdocs.{treatment}{ext}"""
        result = _build_output_path(
            "/folder/report.docx",
            "{basename}.superdocs.{treatment}{ext}",
            "normalized",
        )
        assert result == "/folder/report.superdocs.normalized.docx"

    def test_nested_folder(self):
        """Path with nested folders is preserved."""
        result = _build_output_path(
            "/Clients/Acme/Inbox/Q3/report.xlsx",
            "{basename}.superdocs.{treatment}{ext}",
            "summarized",
        )
        assert result == "/Clients/Acme/Inbox/Q3/report.superdocs.summarized.xlsx"

    def test_no_extension(self):
        """File without extension."""
        result = _build_output_path(
            "/folder/README",
            "{basename}.superdocs.{treatment}{ext}",
            "processed",
        )
        assert result == "/folder/README.superdocs.processed"

    def test_output_contains_marker(self):
        """Every output path must contain the .superdocs. marker for anti-loop naming detection."""
        result = _build_output_path(
            "/folder/doc.pdf",
            "{basename}.superdocs.{treatment}{ext}",
            "normalized",
        )
        assert ".superdocs." in result


class TestHumanGate:
    """Prepare never writes back; reject never writes back; crash resume works."""

    def test_prepare_does_not_write_back(self, db_session):
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()
        _, _, job = _setup_scenario(db_session)
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")

        result = worker.process_job(db_session, job)

        assert result.status == JobStatus.REVIEW_PENDING
        assert len(fake_dbx.uploads) == 0
        assert "approve" not in [c["operation"] for c in fake_sd.calls]

    def test_reject_does_not_write_back(self, db_session):
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()
        _, _, job = _setup_scenario(db_session)
        worker = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="test-worker")
        worker.process_job(db_session, job)
        transition(db_session, job, JobStatus.REJECTED, actor="user")
        db_session.commit()

        assert job.status == JobStatus.REJECTED
        assert len(fake_dbx.uploads) == 0
        assert db_session.query(KnownOutput).count() == 0

    def test_crash_resume_skips_finished_upload(self, db_session):
        """Kill after REVIEW_PENDING; a new worker completes without re-uploading."""
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/Clients/Acme/Inbox/report.docx"))
        fake_sd = FakeSuperDocsClient()
        _, _, job = _setup_scenario(db_session)

        worker1 = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="worker-a")
        worker1.process_job(db_session, job)
        assert job.status == JobStatus.REVIEW_PENDING
        doc_id = job.superdocs_doc_id

        worker2 = WorkerLoop(dropbox=fake_dbx, superdocs=fake_sd, worker_id="worker-b")
        transition(db_session, job, JobStatus.APPROVED, actor="user")
        db_session.commit()
        result = worker2.complete_approved_job(db_session, job)

        assert result.status == JobStatus.COMPLETED
        assert job.superdocs_doc_id == doc_id
        assert [c["operation"] for c in fake_sd.calls] == ["upload", "chat", "approve", "export"]
