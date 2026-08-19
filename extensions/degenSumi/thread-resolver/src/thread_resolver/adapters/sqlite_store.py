"""Run state persisted to SQLite.

SQLite is used rather than a JSON file for two reasons: a write is a transaction,
so a process killed mid-save leaves the previous state readable rather than a
half-written file; and two runs writing at once are serialised by the database
rather than by hoping their writes do not interleave.

Serialisation is written out by hand rather than derived. The stored shape is
part of what a resumed run depends on, so it is stated explicitly and covered by
a round-trip test.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from thread_resolver.domain.models import (
    Anchor,
    Classification,
    Comment,
    Decision,
    Disposition,
    ProposedEdit,
    ReviewItem,
    Thread,
)
from thread_resolver.domain.run import RunState, Stage, StageTiming
from thread_resolver.ports.store import RunStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    document_name TEXT NOT NULL,
    stage         TEXT NOT NULL,
    state         TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


class SqliteRunStore(RunStore):
    def __init__(self, path: Path | str = "runs.db") -> None:
        self._path = str(path)
        with self._connect() as connection:
            connection.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0, isolation_level="IMMEDIATE")
        # Lets a reader continue while another run is mid-write.
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save(self, state: RunState) -> None:
        payload = json.dumps(encode(state), separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, document_name, stage, state, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "document_name=excluded.document_name, stage=excluded.stage, "
                "state=excluded.state, updated_at=excluded.updated_at",
                (
                    state.run_id,
                    state.document_name,
                    str(state.stage),
                    payload,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def load(self, run_id: str) -> RunState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else decode(json.loads(row[0]))

    def list_runs(self) -> tuple[RunState, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT state FROM runs ORDER BY updated_at DESC").fetchall()
        return tuple(decode(json.loads(row[0])) for row in rows)


# -- serialisation ----------------------------------------------------------


def encode(state: RunState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "document_name": state.document_name,
        "stage": str(state.stage),
        "session_id": state.session_id,
        "operations_spent": state.operations_spent,
        "timings": [{"stage": str(t.stage), "seconds": t.seconds} for t in state.timings],
        "items": [_encode_item(item) for item in state.items],
    }


def decode(raw: dict[str, Any]) -> RunState:
    return RunState(
        run_id=raw["run_id"],
        document_name=raw["document_name"],
        stage=Stage(raw["stage"]),
        session_id=raw.get("session_id"),
        operations_spent=raw.get("operations_spent", 0),
        timings=tuple(
            StageTiming(stage=Stage(t["stage"]), seconds=t["seconds"])
            for t in raw.get("timings", [])
        ),
        items=tuple(_decode_item(item) for item in raw.get("items", [])),
    )


def _encode_comment(comment: Comment) -> dict[str, Any]:
    return {
        "comment_id": comment.comment_id,
        "para_id": comment.para_id,
        "author": comment.author,
        "text": comment.text,
        "created": comment.created.isoformat() if comment.created else None,
    }


def _decode_comment(raw: dict[str, Any]) -> Comment:
    return Comment(
        comment_id=raw["comment_id"],
        para_id=raw["para_id"],
        author=raw["author"],
        text=raw["text"],
        created=datetime.fromisoformat(raw["created"]) if raw["created"] else None,
    )


def _encode_item(item: ReviewItem) -> dict[str, Any]:
    thread = item.thread
    return {
        "thread": {
            "root": _encode_comment(thread.root),
            "replies": [_encode_comment(c) for c in thread.replies],
            "anchor": None
            if thread.anchor is None
            else {
                "text": thread.anchor.text,
                "paragraph_index": thread.anchor.paragraph_index,
                "chunk_id": thread.anchor.chunk_id,
            },
            "resolved": thread.resolved,
        },
        "classification": {
            "disposition": str(item.classification.disposition),
            "reason": item.classification.reason,
            "decided_by": item.classification.decided_by,
            "instruction": item.classification.instruction,
        },
        "proposed_edits": [
            {
                "change_id": e.change_id,
                "chunk_id": e.chunk_id,
                "operation": e.operation,
                "old_html": e.old_html,
                "new_html": e.new_html,
                "explanation": e.explanation,
            }
            for e in item.proposed_edits
        ],
        "decision": None if item.decision is None else str(item.decision),
        "job_id": item.job_id,
        "session_id": item.session_id,
        "notes": list(item.notes),
    }


def _decode_item(raw: dict[str, Any]) -> ReviewItem:
    thread_raw = raw["thread"]
    anchor_raw = thread_raw["anchor"]
    thread = Thread(
        root=_decode_comment(thread_raw["root"]),
        replies=tuple(_decode_comment(c) for c in thread_raw["replies"]),
        anchor=None
        if anchor_raw is None
        else Anchor(
            text=anchor_raw["text"],
            paragraph_index=anchor_raw["paragraph_index"],
            chunk_id=anchor_raw["chunk_id"],
        ),
        resolved=thread_raw["resolved"],
    )
    classification_raw = raw["classification"]
    return ReviewItem(
        thread=thread,
        classification=Classification(
            disposition=Disposition(classification_raw["disposition"]),
            reason=classification_raw["reason"],
            decided_by=classification_raw["decided_by"],
            instruction=classification_raw["instruction"],
        ),
        proposed_edits=tuple(
            ProposedEdit(
                change_id=e["change_id"],
                chunk_id=e["chunk_id"],
                operation=e["operation"],
                old_html=e["old_html"],
                new_html=e["new_html"],
                explanation=e["explanation"],
            )
            for e in raw["proposed_edits"]
        ),
        decision=None if raw["decision"] is None else Decision(raw["decision"]),
        job_id=raw["job_id"],
        session_id=raw["session_id"],
        notes=tuple(raw.get("notes", [])),
    )
