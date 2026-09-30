"""The redaction log. **One table, and the only thing this app writes down.**

The obligation is small — "what was removed and by whom" — and the schema is no
larger: eleven columns, one insert per human decision, no sessions or candidates
table. Everything else lives in memory in `review.py` and is gone at exit,
because a pane holds the contents of somebody's contract and the less of that on
disk, the better.

The document hash is why the log can answer its one question. `intake.docx`
names a file; `intake.docx @ 3f9a…` names a *version* — filenames are reused
between drafts, so without it "was this copy cleaned?" is unanswerable.

See extensions/redaction-pane/README.md § "What is stored, and what is not".
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS redaction_log (
    id            TEXT PRIMARY KEY,
    -- WHICH DOCUMENT, and which version of it.
    document      TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    -- BY WHOM. Self-declared: no sign-in, and the audit page says so. Presenting
    -- an unverified name as identity would be a false certification.
    reviewer      TEXT NOT NULL,
    -- WHAT HAPPENED: redacted / dismissed / failed / reverted. A revert is
    -- APPENDED, never a deletion — the text was removed then put back, and
    -- erasing the first row would lie about the past. Dismissals are recorded
    -- because "nobody reviewed this" and "looked and left it" differ.
    action        TEXT NOT NULL,
    -- WHAT IT WAS. Without it, "one item was redacted" answers no question.
    text          TEXT NOT NULL,
    category      TEXT NOT NULL,
    -- FROM WHERE: which part, block, and character range. tracked_del matters —
    -- an identifier inside a tracked deletion is invisible in Word.
    part_type     TEXT NOT NULL,
    chunk_id      TEXT NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    -- WHAT IT BECAME. `[CREDIT CARD REDACTED]`, not `[REDACTED]`, so the log
    -- and the released document say the same thing.
    marker        TEXT NOT NULL DEFAULT '',
    detail        TEXT NOT NULL DEFAULT '',
    at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS log_document_idx ON redaction_log (document_hash, at);
"""


def _now() -> str:
    """Microseconds: a reviewer answering quickly makes several entries in one
    second, and a log that can't order them can't be read back."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class Store:
    path: Path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def setup(self) -> None:
        _relocate_legacy(self.path)
        with self.connect() as conn:
            _retire_old_schema(conn)
            conn.executescript(SCHEMA)

    def record(
        self,
        *,
        document: str,
        document_hash: str,
        reviewer: str,
        action: str,
        text: str,
        category: str,
        part_type: str,
        chunk_id: str,
        char_start: int,
        char_end: int,
        marker: str = "",
        detail: str = "",
    ) -> None:
        """One human decision, called AFTER Word has acted. The order is the
        guarantee: the log only describes a removal that happened. Writing intent
        first would produce a log claiming clean when the write failed."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO redaction_log (id, document, document_hash, reviewer, action,"
                " text, category, part_type, chunk_id, char_start, char_end, marker, detail, at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()), document, document_hash, reviewer, action, text,
                    category, part_type, chunk_id, char_start, char_end, marker, detail, _now(),
                ),
            )

    def entries(self, document_hash: str) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM redaction_log WHERE document_hash = ? ORDER BY at, rowid",
                (document_hash,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_document(self) -> str | None:
        """For `/audit` opened without a hash — the document last worked on."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT document_hash FROM redaction_log ORDER BY at DESC LIMIT 1"
            ).fetchone()
        return str(row["document_hash"]) if row else None

    def report(self, document_hash: str) -> dict[str, object]:
        """The log as the thing a reviewer hands on. States what it does not
        cover as prominently as what it does — a log implying more coverage than
        the tool has is worse than no log."""
        entries = self.entries(document_hash)
        first = entries[0] if entries else {}
        return {
            "document": first.get("document", ""),
            "document_hash": document_hash,
            "reviewer": first.get("reviewer", ""),
            "started_at": first.get("at", ""),
            "removed": [row for row in entries if row["action"] == "redacted"],
            "dismissed": [row for row in entries if row["action"] == "dismissed"],
            "failed": [row for row in entries if row["action"] == "failed"],
            "reverted": [row for row in entries if row["action"] == "reverted"],
            "covers": (
                "Visible document text: body, headers, footers, footnotes, endnotes, "
                "comments and the contents of tracked deletions."
            ),
            "does_not_cover": (
                "Document properties and file metadata (docProps/*) are outside this "
                "pipeline and are never modified. This log is a record of human "
                "decisions; it is not a certificate that a document is safe to release, "
                "and every removal in it required a human click. The reviewer name is "
                "self-declared — this tool has no sign-in and does not verify it."
            ),
            "entries": entries,
        }


def _relocate_legacy(path: Path) -> None:
    """Move a database left at `data/redaction.db` into `data/db/`. Moved, never
    recreated: the old file is somebody's log, and a fresh empty one beside it
    would silently lose it."""
    legacy = path.parent.parent / path.name
    if legacy.exists() and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(path)


def _retire_old_schema(conn: sqlite3.Connection) -> None:
    """Make room for the lean table without destroying anybody's log.

    An earlier version had three tables. `CREATE TABLE IF NOT EXISTS` does
    nothing when the old wide `redaction_log` is present, then the index fails on
    a missing column — a service that starts, accepts redactions and writes them
    nowhere. So the old log is renamed, never dropped; the two review-state
    tables are dropped, since that state is now in memory.
    """
    existing = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "redaction_log" in existing:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(redaction_log)")}
        if "document_hash" not in columns:
            conn.execute("DROP TABLE IF EXISTS redaction_log_v1")
            conn.execute("ALTER TABLE redaction_log RENAME TO redaction_log_v1")
    for table in ("redaction_candidates", "redaction_sessions"):
        if table in existing:
            conn.execute(f"DROP TABLE {table}")


def as_json(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2)


CSV_COLUMNS = (
    ("at", "at"),
    ("action", "action"),
    ("reviewer", "reviewer"),
    ("text", "text"),
    ("category", "category"),
    ("part", "part_type"),
    ("block", "chunk_id"),
    ("char_start", "char_start"),
    ("char_end", "char_end"),
    ("replaced_with", "marker"),
    ("detail", "detail"),
    ("document", "document"),
    ("document_hash", "document_hash"),
)

_FORMULA = ("=", "+", "-", "@", "\t", "\r")
"""Characters Excel/Sheets treat as a formula start. Every `text` cell is
verbatim contract content, so `=HYPERLINK(...)` becomes a live formula when the
log opens — CSV injection, the same hole the audit page's HTML escaping closes."""


def _safe(value: object) -> str:
    """Neutralise a leading formula character without altering the text. A
    leading apostrophe is Excel's literal marker — the cell still reads as the
    original and is not evaluated; stripping it would change what the log says."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def as_csv(report: dict[str, object]) -> str:
    """The log as a spreadsheet, newest last. Every entry, not just removals —
    a reader filters on `action`, and dropping dismissals could not answer "was
    this reviewed?"."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for label, _ in CSV_COLUMNS])
    document = report.get("document", "")
    digest = report.get("document_hash", "")
    for row in report.get("entries") or []:  # type: ignore[union-attr]
        values = {**row, "document": document, "document_hash": digest}
        writer.writerow([_safe(values.get(key, "")) for _, key in CSV_COLUMNS])
    return buffer.getvalue()
