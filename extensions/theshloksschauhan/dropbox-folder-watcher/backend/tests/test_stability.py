"""Tests for file stability detection.

These tests prove the card's named differentiator:
"survives Dropbox's sync behaviour without processing half-written files."

Test 2 from Section 19: Half-written file
  - Simulate content_hash changing across the debounce window
  - Assert the file is NOT processed until stable

All tests run without any Dropbox API key — they use the fake client
and an in-memory SQLite database.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.dropbox_event import DropboxEvent
from app.services.stability import (
    check_stability,
    record_observation,
    has_hash_changed_since_observation,
    StabilityResult,
)
from app.services.dropbox_client import FileMetadata
from tests.fixtures.fake_dropbox import make_stable_file, make_unstable_file_sequence


class TestStabilityDetection:
    """Prove that half-written files are never processed."""

    def test_first_observation_is_never_stable(self, db_session):
        """A file seen for the first time must NOT be considered stable.
        It needs at least one debounce cycle to prove it isn't changing."""
        meta = make_stable_file()
        result = check_stability(db_session, meta.path, meta, debounce_seconds=30)
        db_session.commit()

        assert result.is_stable is False
        assert "First observation" in result.reason

    def test_stable_after_debounce_window(self, db_session):
        """A file whose hash+rev haven't changed for the full debounce window
        should be marked STABLE."""
        meta = make_stable_file()

        # First observation — recorded with a timestamp in the past
        record_observation(db_session, meta.path, meta)
        db_session.commit()

        # Backdate the observation to simulate time passing
        event = db_session.query(DropboxEvent).first()
        event.observed_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        db_session.commit()

        # Second check — same hash, debounce window elapsed
        result = check_stability(db_session, meta.path, meta, debounce_seconds=30)

        assert result.is_stable is True
        assert "Stable for" in result.reason

    def test_unstable_within_debounce_window(self, db_session):
        """A file whose hash hasn't changed but debounce hasn't elapsed
        should NOT be marked stable."""
        meta = make_stable_file()

        # First observation — just now
        record_observation(db_session, meta.path, meta)
        db_session.commit()

        # Second check — immediately, no time has passed
        result = check_stability(db_session, meta.path, meta, debounce_seconds=30)

        assert result.is_stable is False
        assert "elapsed" in result.reason

    def test_half_written_file_detected(self, db_session):
        """THE CRITICAL TEST: a file whose content_hash changes between
        observations is never processed.

        Simulates a large file being uploaded — each time we check,
        the hash is different because more bytes have arrived."""
        sequence = make_unstable_file_sequence()

        # Observation 1: partial upload
        result1 = check_stability(db_session, sequence[0].path, sequence[0], debounce_seconds=5)
        db_session.commit()
        assert result1.is_stable is False

        # Observation 2: hash changed (more bytes uploaded)
        # This is a DIFFERENT hash, so the debounce clock resets
        result2 = check_stability(db_session, sequence[1].path, sequence[1], debounce_seconds=5)
        db_session.commit()
        assert result2.is_stable is False
        assert "First observation" in result2.reason  # New hash = new clock

        # Observation 3: hash changed again
        result3 = check_stability(db_session, sequence[2].path, sequence[2], debounce_seconds=5)
        db_session.commit()
        assert result3.is_stable is False

        # Observation 4: hash SAME as observation 3, but need to backdate for debounce
        # First, backdate observation 3
        events = db_session.query(DropboxEvent).filter(
            DropboxEvent.content_hash == sequence[2].content_hash
        ).all()
        for e in events:
            e.observed_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db_session.commit()

        # Now check again with the same hash — should be stable
        result4 = check_stability(db_session, sequence[3].path, sequence[3], debounce_seconds=5)
        assert result4.is_stable is True

    def test_missing_content_hash_is_never_stable(self, db_session):
        """Files with no content_hash (rare, but possible during sync) are rejected."""
        meta = FileMetadata(
            path="/test/file.docx", name="file.docx",
            rev="some_rev", content_hash="",  # Empty hash
            size=1000,
        )
        result = check_stability(db_session, meta.path, meta, debounce_seconds=5)
        assert result.is_stable is False
        assert "Missing content_hash" in result.reason

    def test_different_debounce_windows(self, db_session):
        """Different folder configs can have different debounce windows."""
        meta = make_stable_file()

        record_observation(db_session, meta.path, meta)
        db_session.commit()

        # Backdate by 15 seconds
        event = db_session.query(DropboxEvent).first()
        event.observed_at = datetime.now(timezone.utc) - timedelta(seconds=15)
        db_session.commit()

        # With 10s debounce -> stable
        result_short = check_stability(db_session, meta.path, meta, debounce_seconds=10)
        assert result_short.is_stable is True

        # With 30s debounce -> NOT stable yet
        result_long = check_stability(db_session, meta.path, meta, debounce_seconds=30)
        assert result_long.is_stable is False

    def test_has_hash_changed_detects_change(self, db_session):
        """Utility function correctly detects hash changes."""
        meta1 = FileMetadata(
            path="/test/file.docx", name="file.docx",
            rev="rev1", content_hash="hash_aaa", size=1000,
        )
        meta2 = FileMetadata(
            path="/test/file.docx", name="file.docx",
            rev="rev2", content_hash="hash_bbb", size=2000,
        )

        record_observation(db_session, meta1.path, meta1)
        db_session.commit()

        # Same hash -> not changed
        assert has_hash_changed_since_observation(db_session, meta1.path, meta1) is False

        # Different hash -> changed
        assert has_hash_changed_since_observation(db_session, meta2.path, meta2) is True

    def test_no_prior_observation_means_changed(self, db_session):
        """If we've never seen a file before, treat it as 'changed'."""
        meta = make_stable_file("/test/brand_new.docx")
        assert has_hash_changed_since_observation(db_session, meta.path, meta) is True
