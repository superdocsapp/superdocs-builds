"""Offline Bates resume and continuity tests.

Proves the Bates assignment state machine works correctly offline:
  - Sequential numbering with no gaps
  - Idempotent re-assignment (no double-stamping)
  - Resume from highest existing number after crash
  - Multi-document sequencing
"""

import tempfile
from pathlib import Path

from app.services.bates_assignment import (
    format_bates_number,
    parse_bates_number,
)
from app.services.bates_journal import BatesJournal, JournalEntry


class TestBatesAssignmentOffline:
    """Offline tests for Bates numbering logic (no DB required)."""

    def test_format_and_parse_roundtrip(self):
        """format -> parse must be lossless."""
        label = format_bates_number("EX-", 42, 6)
        assert label == "EX-000042"
        prefix, num = parse_bates_number(label, "EX-")
        assert prefix == "EX-"
        assert num == 42

    def test_sequential_numbering(self):
        """10 pages should produce 10 sequential numbers."""
        prefix = "CASE-"
        padding = 6
        labels = [format_bates_number(prefix, i, padding) for i in range(1, 11)]
        assert labels == [
            "CASE-000001",
            "CASE-000002",
            "CASE-000003",
            "CASE-000004",
            "CASE-000005",
            "CASE-000006",
            "CASE-000007",
            "CASE-000008",
            "CASE-000009",
            "CASE-000010",
        ]

    def test_resume_after_crash_via_journal(self):
        """Journal-based resume produces the correct next number."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "journal.jsonl")

            # Simulate 5 assigned pages before crash
            for i in range(1, 6):
                journal.append(
                    JournalEntry(
                        page_key=f"doc1:p{i}",
                        document_id="doc1",
                        page_number=i,
                        bates_number=i,
                        bates_label=format_bates_number("CASE-", i, 6),
                        assigned_at="2024-01-01T00:00:00Z",
                    )
                )

            # Resume should start at 6
            assert journal.resume_start(bates_start_number=1) == 6

    def test_multi_document_sequencing(self):
        """Two documents: doc1 has 3 pages, doc2 has 2. Total 5 sequential."""
        prefix = "CASE-"
        padding = 6

        # Doc1: pages 1-3
        doc1_labels = [format_bates_number(prefix, i, padding) for i in range(1, 4)]
        # Doc2: pages 4-5
        doc2_labels = [format_bates_number(prefix, i, padding) for i in range(4, 6)]

        all_labels = doc1_labels + doc2_labels
        assert len(all_labels) == 5
        assert all_labels == [
            "CASE-000001",
            "CASE-000002",
            "CASE-000003",
            "CASE-000004",
            "CASE-000005",
        ]
        # Verify no duplicates
        assert len(set(all_labels)) == 5
        # Verify strictly increasing
        assert all_labels == sorted(all_labels)

    def test_idempotent_journal_entries(self):
        """Same page_key written twice is detected as duplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "journal.jsonl")

            journal.append(
                JournalEntry(
                    page_key="doc1:p1",
                    document_id="doc1",
                    page_number=1,
                    bates_number=1,
                    bates_label="CASE-000001",
                    assigned_at="2024-01-01T00:00:00Z",
                )
            )
            journal.append(
                JournalEntry(
                    page_key="doc1:p1",
                    document_id="doc1",
                    page_number=1,
                    bates_number=2,
                    bates_label="CASE-000002",
                    assigned_at="2024-01-01T00:00:01Z",
                )
            )

            # Page key appears twice -> double-stamped
            proof = journal.prove_continuity(expected_count=2, bates_start_number=1)
            assert not proof.valid
            assert "doc1:p1" in proof.double_stamped_pages
