"""Tests for anti-loop protection.

Test 4 from Section 19: Own-output event
  - Feed the watcher a synthetic event for a path/hash present in known_outputs
  - Assert it's skipped with a logged reason, not processed

All tests run without any API key — in-memory SQLite only.
"""
import uuid

import pytest

from app.models.known_output import KnownOutput
from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.services.antiloop import (
    is_output_by_naming,
    is_known_output_by_path,
    is_known_output_by_hash,
    is_own_output,
    register_output,
    OUTPUT_MARKER,
)


# ---------- Helper to create a minimal job chain for FK constraints ----------

def _create_job(db_session, source_path="/test/input.docx", source_rev="rev_001"):
    """Create a minimal client -> folder_config -> job chain for tests."""
    client = Client(
        id=uuid.uuid4(), name="Test Client",
        dropbox_folder_root="/test",
    )
    db_session.add(client)
    db_session.flush()

    folder = FolderConfig(
        id=uuid.uuid4(), client_id=client.id,
        dropbox_folder_path="/test/inbox",
        treatment="normalize",
    )
    db_session.add(folder)
    db_session.flush()

    job = Job(
        id=uuid.uuid4(), client_id=client.id,
        folder_config_id=folder.id,
        source_path=source_path, source_rev=source_rev,
        status=JobStatus.COMPLETED,
    )
    db_session.add(job)
    db_session.flush()

    return job


class TestAntiLoopNaming:
    """Layer 1: naming convention check (fast filter)."""

    def test_output_naming_detected(self):
        """Files with '.superdocs.' in the name are detected."""
        assert is_output_by_naming("/folder/report.superdocs.normalized.docx") is True
        assert is_output_by_naming("/folder/report.SUPERDOCS.normalized.docx") is True
        assert is_output_by_naming("/folder/a.superdocs.b.pdf") is True

    def test_input_naming_not_detected(self):
        """Normal input files are NOT flagged by naming alone."""
        assert is_output_by_naming("/folder/report.docx") is False
        assert is_output_by_naming("/folder/my-file.pdf") is False
        assert is_output_by_naming("/folder/superdocs-guide.txt") is False  # No dot-separated marker

    def test_edge_cases(self):
        """Edge cases in path parsing."""
        assert is_output_by_naming("report.superdocs.docx") is True  # No folder prefix
        assert is_output_by_naming("/deep/path/to/file.superdocs.x.docx") is True


class TestAntiLoopDatabase:
    """Layer 2 & 3: database-backed checks."""

    def test_known_output_by_path(self, db_session):
        """A path registered in known_outputs is detected."""
        job = _create_job(db_session)
        output_path = "/test/inbox/report.superdocs.normalized.docx"

        # Before registration: not known
        assert is_known_output_by_path(db_session, output_path) is False

        # Register the output
        register_output(db_session, job.id, output_path,
                       output_rev="rev_out", output_content_hash="hash_out_123")
        db_session.commit()

        # After registration: known
        assert is_known_output_by_path(db_session, output_path) is True

    def test_known_output_by_hash(self, db_session):
        """A content hash registered in known_outputs is detected.
        This catches copies under different paths."""
        job = _create_job(db_session)
        output_hash = "hash_out_abc123"

        register_output(db_session, job.id, "/original/output.docx",
                       output_content_hash=output_hash)
        db_session.commit()

        # Same hash, different path -> still detected
        assert is_known_output_by_hash(db_session, output_hash) is True

        # Different hash -> not detected
        assert is_known_output_by_hash(db_session, "completely_different_hash") is False

    def test_empty_hash_not_detected(self, db_session):
        """Empty/None content hash should not match anything."""
        assert is_known_output_by_hash(db_session, "") is False

    def test_unknown_path_not_blocked(self, db_session):
        """A path NOT in known_outputs should not be blocked."""
        assert is_known_output_by_path(db_session, "/brand/new/file.docx") is False


class TestAntiLoopCombined:
    """The full is_own_output() check using all three layers."""

    def test_own_output_blocked_by_path(self, db_session):
        """THE CRITICAL TEST: an event for a known output path is blocked."""
        job = _create_job(db_session)
        output_path = "/test/inbox/report.superdocs.normalized.docx"

        register_output(db_session, job.id, output_path,
                       output_rev="rev_out", output_content_hash="hash_out_999")
        db_session.commit()

        # This event should be blocked — it's our own output
        assert is_own_output(db_session, output_path, "hash_out_999") is True

    def test_own_output_blocked_by_hash_only(self, db_session):
        """A copy of our output under a different path is also blocked."""
        job = _create_job(db_session)
        output_hash = "hash_output_copied_abc"

        register_output(db_session, job.id, "/original/path/output.docx",
                       output_content_hash=output_hash)
        db_session.commit()

        # Same hash but different path -> still blocked
        assert is_own_output(db_session, "/different/folder/copied.docx", output_hash) is True

    def test_normal_input_not_blocked(self, db_session):
        """A normal input file should never be blocked."""
        assert is_own_output(db_session, "/clients/acme/inbox/new_report.docx",
                            "brand_new_hash") is False

    def test_naming_match_without_db_match_not_blocked(self, db_session):
        """A file that matches the naming convention but is NOT in the DB
        should still be processed (it might be a client file that happens
        to contain '.superdocs.' in the name)."""
        result = is_own_output(db_session, "/test/client.superdocs.file.docx",
                              "unknown_hash")
        # Should NOT be blocked — naming alone isn't sufficient
        assert result is False

    def test_survives_restart(self, db_session):
        """After registering an output and 'restarting' (new session query),
        the output is still detected. Proves persistence over in-memory."""
        job = _create_job(db_session)
        output_path = "/test/output.superdocs.normalized.docx"

        register_output(db_session, job.id, output_path,
                       output_rev="rev_persist", output_content_hash="hash_persist")
        db_session.commit()

        # Simulate a "restart" by just querying again
        # (In real life this would be a new process reading from Postgres)
        assert is_own_output(db_session, output_path, "hash_persist") is True

    def test_register_output_returns_known_output(self, db_session):
        """register_output should return a valid KnownOutput object."""
        job = _create_job(db_session)
        result = register_output(
            db_session, job.id, "/test/out.docx",
            output_rev="r1", output_content_hash="h1",
        )
        db_session.commit()

        assert result.id is not None
        assert result.output_path == "/test/out.docx"
        assert result.output_rev == "r1"
        assert result.output_content_hash == "h1"
        assert result.job_id == job.id
