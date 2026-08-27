"""Where the inbound graph's execution state lives between a crash and a restart.

The review round itself is the Store's job; this is the *graph's* own checkpoint — the
propose → gate → apply position, so a killed run resumes at the gate rather than re-proposing.
An in-memory saver is enough within one process (the demo, the keyless suite); a durable review
that pauses for days needs the state on disk, which is a file-backed SQLite saver keyed by round.

Postgres is the documented scale substrate (``langgraph.checkpoint.postgres``); it is wired the
same way once a ``DATABASE_URL`` is present, and left out here so the keyless path needs no server.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver


def open_checkpointer(sqlite_path: str | None) -> Any:
    """Return a graph checkpointer: file-backed SQLite when a path is given, else in-memory.

    A file path makes the checkpoint outlive the process, so ``submit`` can resume a round that
    ``start`` paused at the gate in an earlier run — the true "survives being stopped" behaviour.
    """
    if not sqlite_path:
        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
