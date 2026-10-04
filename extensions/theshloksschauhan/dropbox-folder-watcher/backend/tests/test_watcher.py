"""Tests for the watcher service.

Proves:
- Anti-loop events are skipped (Test 4 integration)
- Duplicate revs are skipped (Test 3: idempotent job creation)
- Unstable files wait (Test 2 integration)
- Extension filtering works
- Disabled folders are skipped
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.models.dropbox_event import DropboxEvent
from app.services.watcher import WatcherService
from app.services.antiloop import register_output
from tests.fixtures.fake_dropbox import FakeDropboxClient, make_stable_file, make_output_file


def _setup_folder(db, preview=False, extensions=None, enabled=True):
    """Create a client and folder config for testing."""
    client = Client(id=uuid.uuid4(), name="Test", dropbox_folder_root="/test")
    db.add(client)
    db.flush()

    folder = FolderConfig(
        id=uuid.uuid4(), client_id=client.id,
        dropbox_folder_path="/test/inbox",
        treatment="normalized",
        instruction_text="Normalize formatting",
        allowed_extensions=extensions,
        enabled=enabled,
        preview_mode=preview,
        debounce_seconds=0,  # Zero debounce for tests — instant stability
    )
    db.add(folder)
    db.flush()
    return client, folder


class TestWatcherAntiLoop:
    """Anti-loop events are skipped during folder scan."""

    def test_own_output_skipped(self, db_session):
        """If a file in the folder is a known output, the watcher skips it."""
        client, folder = _setup_folder(db_session)

        # Register a known output
        job = Job(
            id=uuid.uuid4(), client_id=client.id, folder_config_id=folder.id,
            source_path="/test/inbox/original.docx", source_rev="rev_orig",
            status=JobStatus.COMPLETED,
        )
        db_session.add(job)
        db_session.flush()

        output_path = "/test/inbox/original.superdocs.normalized.docx"
        register_output(db_session, job.id, output_path,
                       output_content_hash="output_hash_abc")
        db_session.commit()

        # Set up Dropbox with both the original and our output
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/test/inbox/new_file.docx"))
        fake_dbx.add_file(make_output_file(output_path))  # Our own output

        watcher = WatcherService(dropbox=fake_dbx)

        # Pre-record a stable observation for the new file
        _seed_stable_observation(db_session, "/test/inbox/new_file.docx",
                                make_stable_file("/test/inbox/new_file.docx"))

        jobs = watcher.scan_folder(db_session, folder)

        # Only the new file should have a job — the output should be skipped
        assert len(jobs) == 1
        assert "new_file" in jobs[0].source_path


class TestWatcherDuplicates:
    """Duplicate revisions are skipped (idempotent job creation)."""

    def test_same_rev_not_duplicated(self, db_session):
        """If a job already exists for this rev, don't create another."""
        client, folder = _setup_folder(db_session)

        stable_meta = make_stable_file("/test/inbox/report.docx")
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(stable_meta)

        # Create an existing job for this rev
        existing = Job(
            id=uuid.uuid4(), client_id=client.id, folder_config_id=folder.id,
            source_path=stable_meta.path, source_rev=stable_meta.rev,
            status=JobStatus.PROCESSING,
        )
        db_session.add(existing)
        db_session.commit()

        watcher = WatcherService(dropbox=fake_dbx)
        jobs = watcher.scan_folder(db_session, folder)

        # No new job — the rev is already being processed
        assert len(jobs) == 0


class TestWatcherStability:
    """Unstable files are not queued."""

    def test_first_seen_file_waits(self, db_session):
        """A file seen for the first time needs at least one debounce cycle.
        With debounce_seconds > 0, it won't be queued on the first scan."""
        client, folder = _setup_folder(db_session)
        # Override to require debounce
        folder.debounce_seconds = 30
        db_session.commit()

        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/test/inbox/report.docx"))

        watcher = WatcherService(dropbox=fake_dbx)
        jobs = watcher.scan_folder(db_session, folder)

        # First scan: file is recorded but not yet stable
        assert len(jobs) == 0


class TestWatcherFiltering:
    """Extension filtering and disabled folders."""

    def test_extension_filter(self, db_session):
        """Only allowed extensions are processed."""
        client, folder = _setup_folder(db_session, extensions=[".docx", ".pdf"])

        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/test/inbox/report.docx"))
        fake_dbx.add_file(make_stable_file("/test/inbox/image.png"))
        fake_dbx.add_file(make_stable_file("/test/inbox/notes.pdf"))

        _seed_stable_observation(db_session, "/test/inbox/report.docx",
                                make_stable_file("/test/inbox/report.docx"))
        _seed_stable_observation(db_session, "/test/inbox/notes.pdf",
                                make_stable_file("/test/inbox/notes.pdf"))

        watcher = WatcherService(dropbox=fake_dbx)
        jobs = watcher.scan_folder(db_session, folder)

        # Only .docx and .pdf should be processed, not .png
        paths = [j.source_path for j in jobs]
        assert any("report.docx" in p for p in paths)
        assert any("notes.pdf" in p for p in paths)
        assert not any("image.png" in p for p in paths)

    def test_disabled_folder_skipped(self, db_session):
        """Disabled folders are not scanned."""
        _, folder = _setup_folder(db_session, enabled=False)

        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(make_stable_file("/test/inbox/report.docx"))

        watcher = WatcherService(dropbox=fake_dbx)
        jobs = watcher.scan_folder(db_session, folder)

        assert len(jobs) == 0


class TestWatcherJobCreation:
    """Stable files get proper jobs created."""

    def test_stable_file_becomes_queued_job(self, db_session):
        """A stable file goes DISCOVERED -> STABILIZING -> QUEUED."""
        client, folder = _setup_folder(db_session)  # debounce_seconds=0

        meta = make_stable_file("/test/inbox/report.docx")
        fake_dbx = FakeDropboxClient()
        fake_dbx.add_file(meta)

        # Pre-seed a stable observation (simulates prior scan)
        _seed_stable_observation(db_session, meta.path, meta)

        watcher = WatcherService(dropbox=fake_dbx)
        jobs = watcher.scan_folder(db_session, folder)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == JobStatus.QUEUED
        assert job.source_path == meta.path
        assert job.source_rev == meta.rev
        assert job.source_content_hash == meta.content_hash
        assert job.preview == folder.preview_mode


# ---------- Helpers ----------

def _seed_stable_observation(db, path, meta, seconds_ago=60):
    """Pre-seed a stable observation so the file passes debounce check."""
    event = DropboxEvent(
        dropbox_path=path,
        content_hash=meta.content_hash,
        rev=meta.rev,
        size=meta.size,
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
    )
    db.add(event)
    db.flush()
