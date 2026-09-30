"""The split log. One table, and only what a split actually did.

The master's content lives in memory while the tab is open; what reaches disk is
the record — which document, into how many parts, whether they reconstructed it,
and when. The coverage verdict is the column that matters.

See use-cases/doc-splitter/README.md § "What is stored".
"""

from __future__ import annotations

import csv
import io
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS split_log (
    id             TEXT PRIMARY KEY,
    document       TEXT NOT NULL,
    document_hash  TEXT NOT NULL,
    part_number    INTEGER NOT NULL,
    part_title     TEXT NOT NULL DEFAULT '',
    blocks         INTEGER NOT NULL DEFAULT 0,
    headings       INTEGER NOT NULL DEFAULT 0,
    characters     INTEGER NOT NULL DEFAULT 0,
    file           TEXT NOT NULL DEFAULT '',
    -- The verdict for the WHOLE split, repeated on each part's row. Denormalised
    -- on purpose: read as a flat CSV, a "part 2 of 3" row that doesn't say
    -- whether the three added up is useless.
    coverage_ok    INTEGER NOT NULL DEFAULT 0,
    coverage       TEXT NOT NULL DEFAULT '',
    at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS split_document_idx ON split_log (document_hash, at);
"""


def _now() -> str:
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
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def record(self, rows: list[dict[str, object]]) -> None:
        """One insert per part, written **after** the exports came back."""
        stamp = _now()
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    "INSERT INTO split_log (id, document, document_hash, part_number,"
                    " part_title, blocks, headings, characters, file, coverage_ok,"
                    " coverage, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()), row["document"], row["document_hash"],
                        row["part_number"], row["part_title"], row["blocks"],
                        row["headings"], row["characters"], row["file"],
                        int(bool(row["coverage_ok"])), row["coverage"], stamp,
                    ),
                )

    def entries(self, document_hash: str = "") -> list[dict[str, object]]:
        with self.connect() as conn:
            if document_hash:
                rows = conn.execute(
                    "SELECT * FROM split_log WHERE document_hash = ? ORDER BY at, part_number",
                    (document_hash,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM split_log ORDER BY at DESC, part_number LIMIT 200"
                ).fetchall()
        return [dict(row) for row in rows]


_FORMULA = ("=", "+", "-", "@", "\t", "\r")
"""What Excel reads as a formula start. Titles come from the document, so a
heading beginning `=` would run when the CSV opens — CSV injection."""


def _safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def as_csv(rows: list[dict[str, object]]) -> str:
    columns = (
        "at", "document", "document_hash", "part_number", "part_title",
        "blocks", "headings", "characters", "file", "coverage_ok", "coverage",
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe(row.get(name, "")) for name in columns])
    return buffer.getvalue()
