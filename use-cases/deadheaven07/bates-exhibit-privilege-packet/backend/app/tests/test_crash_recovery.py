"""Crash-recovery tests for Bates assignment continuity.

These tests prove that:
  1. After a simulated crash mid-assignment, resuming produces zero gaps
     and zero double-stamping.
  2. The journal proves continuity mathematically.
  3. No page ever receives two Bates labels.

All tests are offline (no DB, no API key).
"""

import json
import tempfile
from pathlib import Path

import pytest

from app.services.bates_assignment import format_bates_number, parse_bates_number
from app.services.bates_journal import BatesJournal, JournalEntry


class TestBatesJournalCrashRecovery:
    """Simulate crash scenarios and prove continuity is maintained."""

    def _make_entry(
        self,
        doc_id: str,
        page_num: int,
        bates_num: int,
        prefix: str = "CASE-",
        padding: int = 6,
    ) -> JournalEntry:
        return JournalEntry(
            page_key=f"{doc_id}:p{page_num}",
            document_id=doc_id,
            page_number=page_num,
            bates_number=bates_num,
            bates_label=format_bates_number(prefix, bates_num, padding),
            assigned_at="2024-01-01T00:00:00Z",
        )

    def test_crash_after_3_of_10_pages(self):
        """Simulate crash after 3 pages assigned out of 10. Resume proves continuity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "bates.jsonl")

            # Simulate: 3 pages assigned before crash
            for i in range(1, 4):
                journal.append(self._make_entry("doc1", i, i))

            # Verify: 3 entries, last number is 3
            assert len(journal.entries()) == 3
            assert journal.last_number() == 3
            assert journal.resume_start(bates_start_number=1) == 4

            # Simulate: resume assigns pages 4-10
            for i in range(4, 11):
                journal.append(self._make_entry("doc1", i, i))

            # Prove continuity
            proof = journal.prove_continuity(expected_count=10, bates_start_number=1)
            assert proof.valid, f"Continuity proof failed: {proof.as_dict()}"
            assert proof.gaps == []
            assert proof.duplicates == []
            assert proof.double_stamped_pages == []

    def test_crash_between_documents(self):
        """Simulate crash between two documents. Resume produces no gap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "bates.jsonl")

            # Document 1: 5 pages (CASE-000001 to CASE-000005)
            for i in range(1, 6):
                journal.append(self._make_entry("doc1", i, i))

            # Crash happens here
            assert journal.last_number() == 5

            # Resume: Document 2 starts at 6
            for i in range(1, 4):
                journal.append(self._make_entry("doc2", i, 5 + i))

            proof = journal.prove_continuity(expected_count=8, bates_start_number=1)
            assert proof.valid, f"Continuity proof failed: {proof.as_dict()}"

    def test_no_double_stamping(self):
        """A page assigned twice gets caught as double-stamped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "bates.jsonl")

            journal.append(self._make_entry("doc1", 1, 1))
            journal.append(self._make_entry("doc1", 1, 2))  # same page, different number

            proof = journal.prove_continuity(expected_count=2, bates_start_number=1)
            assert not proof.valid
            assert "doc1:p1" in proof.double_stamped_pages

    def test_gap_detection(self):
        """A skipped number is detected as a gap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "bates.jsonl")

            # Skip number 3
            for num in [1, 2, 4, 5]:
                page_num = num if num < 4 else num - 1
                journal.append(self._make_entry("doc1", page_num, num))

            proof = journal.prove_continuity(expected_count=5, bates_start_number=1)
            assert not proof.valid
            assert 3 in proof.gaps

    def test_journal_survives_truncated_line(self):
        """A malformed line in the journal is skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "bates.jsonl"

            # Write valid entries + a truncated line
            with open(journal_path, "w") as f:
                for i in range(1, 4):
                    entry = self._make_entry("doc1", i, i)
                    f.write(
                        json.dumps(
                            {
                                "page_key": entry.page_key,
                                "document_id": entry.document_id,
                                "page_number": entry.page_number,
                                "bates_number": entry.bates_number,
                                "bates_label": entry.bates_label,
                                "assigned_at": entry.assigned_at,
                            }
                        )
                        + "\n"
                    )
                f.write('{"truncated": true\n')  # malformed

            journal = BatesJournal(journal_path)
            entries = journal.entries()
            assert len(entries) == 3  # malformed line skipped

            proof = journal.prove_continuity(expected_count=3, bates_start_number=1)
            assert proof.valid

    def test_empty_journal_validates(self):
        """An empty journal with expected_count=0 is valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = BatesJournal(Path(tmpdir) / "bates.jsonl")
            proof = journal.prove_continuity(expected_count=0, bates_start_number=1)
            assert proof.valid
            assert proof.gaps == []
            assert proof.duplicates == []


class TestBatesFormatting:
    def test_format_bates_number(self):
        assert format_bates_number("CASE-", 1, 6) == "CASE-000001"
        assert format_bates_number("BATES-", 42, 4) == "BATES-0042"

    def test_parse_bates_number(self):
        prefix, num = parse_bates_number("CASE-000042", "CASE-")
        assert prefix == "CASE-"
        assert num == 42

    def test_parse_invalid_prefix(self):
        with pytest.raises(ValueError, match="does not match"):
            parse_bates_number("WRONG-000042", "CASE-")
