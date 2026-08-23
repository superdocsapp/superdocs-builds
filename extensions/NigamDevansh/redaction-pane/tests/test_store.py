"""The log — the one thing this app writes down, and what it must say.

The assignment asks for *"a redaction log listing what was removed and by whom"*.
These tests hold it to that sentence and to the two things the sentence implies
but does not say: **from where**, and **which version of the document**.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from service.store import Store

ENTRY = {
    "document": "intake-summary.docx",
    "document_hash": "3f9a" + "0" * 60,
    "reviewer": "Priya",
    "text": "4111 1111 1111 1111",
    "category": "account",
    "part_type": "comment",
    "chunk_id": "comments:0",
    "char_start": 61,
    "char_end": 80,
}


def test_it_records_what_was_removed_and_by_whom(store: Store) -> None:
    store.record(**ENTRY, action="redacted", marker="[CREDIT CARD REDACTED]")

    removed = store.report(ENTRY["document_hash"])["removed"]

    assert len(removed) == 1
    assert removed[0]["text"] == "4111 1111 1111 1111"
    assert removed[0]["reviewer"] == "Priya"


def test_it_records_from_where(store: Store) -> None:
    """A log that cannot say the card number was in a *comment* has lost the
    finding that mattered: a reviewer reading the released document would never
    have seen it."""
    store.record(**ENTRY, action="redacted", marker="[CREDIT CARD REDACTED]")

    row = store.report(ENTRY["document_hash"])["removed"][0]

    assert row["part_type"] == "comment"
    assert row["chunk_id"] == "comments:0"
    assert (row["char_start"], row["char_end"]) == (61, 80)


def test_it_records_what_the_text_became(store: Store) -> None:
    """The document and the log have to agree. If one says `[REDACTED]` and the
    other says `[CREDIT CARD REDACTED]`, neither can be checked against the
    released file."""
    store.record(**ENTRY, action="redacted", marker="[CREDIT CARD REDACTED]")

    assert store.report(ENTRY["document_hash"])["removed"][0]["marker"] == (
        "[CREDIT CARD REDACTED]"
    )


def test_two_versions_of_one_filename_are_different_documents(store: Store) -> None:
    """Filenames get reused and documents get edited between reviews. Without
    the hash, "was this copy cleaned?" has no answer."""
    store.record(**ENTRY, action="redacted")
    store.record(**{**ENTRY, "document_hash": "b7c2" + "0" * 60}, action="redacted")

    assert len(store.report(ENTRY["document_hash"])["removed"]) == 1
    assert len(store.report("b7c2" + "0" * 60)["removed"]) == 1


def test_a_dismissal_is_recorded_too(store: Store) -> None:
    """"Nobody looked at this" and "somebody looked and said leave it" are
    different states, and afterwards only the log can tell them apart."""
    store.record(**ENTRY, action="dismissed", detail="party to the contract")

    report = store.report(ENTRY["document_hash"])

    assert report["removed"] == []
    assert len(report["dismissed"]) == 1


def test_a_failure_is_never_reported_as_a_removal(store: Store) -> None:
    """The one lie a redaction log must not tell."""
    store.record(**ENTRY, action="failed", detail="inside a tracked change")

    report = store.report(ENTRY["document_hash"])

    assert report["removed"] == []
    assert len(report["failed"]) == 1


def test_the_report_states_what_it_does_not_cover(store: Store) -> None:
    store.record(**ENTRY, action="redacted")

    boundary = str(store.report(ENTRY["document_hash"])["does_not_cover"])

    assert "docProps" in boundary
    assert "not a certificate" in boundary
    assert "self-declared" in boundary


def test_entries_keep_the_order_they_happened_in(store: Store) -> None:
    """Microsecond timestamps, because a reviewer answering rows quickly
    produces several entries inside one second."""
    for index in range(5):
        store.record(**{**ENTRY, "text": f"item-{index}"}, action="redacted")

    order = [row["text"] for row in store.report(ENTRY["document_hash"])["removed"]]

    assert order == [f"item-{index}" for index in range(5)]


class TestTheLeanSchema:
    def test_there_is_exactly_one_table(self, store: Store) -> None:
        """Review state lives in memory now. A table holding candidates would
        put the contents of somebody's contract back on disk, which is the thing
        moving it to memory was for."""
        store.record(**ENTRY, action="redacted")

        with store.connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

        assert tables == {"redaction_log"}

    def test_a_database_left_in_the_old_place_is_moved_not_abandoned(
        self, tmp_path: Path
    ) -> None:
        """The database used to sit at `data/redaction.db`, beside the reviewer's
        own files. Creating a fresh empty one in the new folder would look like
        it worked while silently losing their log."""
        legacy = tmp_path / "redaction.db"
        conn = sqlite3.connect(legacy)
        conn.executescript(
            "CREATE TABLE redaction_log (id TEXT PRIMARY KEY, document TEXT,"
            " document_hash TEXT, reviewer TEXT, action TEXT, text TEXT, category TEXT,"
            " part_type TEXT, chunk_id TEXT, char_start INT, char_end INT, marker TEXT,"
            " detail TEXT, at TEXT);"
            "INSERT INTO redaction_log (id, document_hash, action) VALUES ('1', 'h', 'redacted');"
        )
        conn.commit()
        conn.close()

        store = Store(tmp_path / "db" / "redaction.db")
        store.setup()

        assert not legacy.exists(), "moved, not copied — two logs would diverge"
        assert len(store.report("h")["removed"]) == 1

    def test_an_older_schema_keeps_its_log_and_loses_its_review_state(
        self, tmp_path: Path
    ) -> None:
        """Upgrading must not start a service that writes redactions nowhere —
        and must not delete a log of removals somebody actually made.
        """
        path = tmp_path / "db" / "redaction.db"
        path.parent.mkdir(parents=True)
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE redaction_log (id TEXT PRIMARY KEY, action TEXT, at TEXT);"
            "CREATE TABLE redaction_sessions (id TEXT PRIMARY KEY);"
            "CREATE TABLE redaction_candidates (id TEXT PRIMARY KEY, text TEXT);"
            "INSERT INTO redaction_log VALUES ('1', 'redacted', '2026-01-01');"
            "INSERT INTO redaction_candidates VALUES ('2', 'a name from a contract');"
        )
        conn.commit()
        conn.close()

        store = Store(path)
        store.setup()

        with store.connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            kept = conn.execute("SELECT count(*) AS n FROM redaction_log_v1").fetchone()["n"]

        assert tables == {"redaction_log", "redaction_log_v1"}, "the old log is kept, not dropped"
        assert kept == 1
        # And the new one works, which is what the failure looked like.
        store.record(**ENTRY, action="redacted")
        assert len(store.report(ENTRY["document_hash"])["removed"]) == 1
