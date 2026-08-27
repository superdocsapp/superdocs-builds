"""The durable ledger.

Everything the runner is allowed to believe after a crash lives here. SQLite in WAL
mode with ``synchronous=FULL``: a transaction that returns has reached the platter,
so a ``SIGKILL`` (or the machine losing power) cannot roll it back.

Two properties matter more than speed:

* **Compare-and-swap transitions.** A step moves state only from the exact state the
  caller expected. Two runners racing on one step means one of them loses the CAS and
  backs off, rather than both issuing the same edit.
* **Append-only commit log.** ``commits`` is the oracle the proof suite compares. It is
  never updated or deleted, only appended.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .model import (
    Commit,
    Decision,
    Document,
    Proposal,
    Run,
    Step,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    spec_path   TEXT NOT NULL,
    spec_hash   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    meta_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents (
    run_id        TEXT NOT NULL,
    slug          TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    title         TEXT NOT NULL,
    document_id   TEXT,
    state         TEXT NOT NULL,
    PRIMARY KEY (run_id, slug)
);

CREATE TABLE IF NOT EXISTS steps (
    run_id       TEXT NOT NULL,
    step_index   INTEGER NOT NULL,
    step_id      TEXT NOT NULL,
    doc_slug     TEXT NOT NULL,
    instruction  TEXT NOT NULL,
    token        TEXT NOT NULL,
    state        TEXT NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 0,
    job_id       TEXT,
    disposition  TEXT,
    evidence     TEXT,
    pre_hash     TEXT,
    post_hash    TEXT,
    started_at   REAL,
    ended_at     REAL,
    billable_ops INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    verify_json  TEXT,
    verification TEXT,
    verification_detail TEXT,
    PRIMARY KEY (run_id, step_index)
);

CREATE TABLE IF NOT EXISTS proposals (
    run_id         TEXT NOT NULL,
    step_index     INTEGER NOT NULL,
    change_id      TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    operation      TEXT NOT NULL,
    chunk_id       TEXT,
    document_id    TEXT,
    old_html       TEXT NOT NULL DEFAULT '',
    new_html       TEXT NOT NULL DEFAULT '',
    ai_explanation TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, step_index, change_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    run_id     TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    change_id  TEXT NOT NULL,
    approved   INTEGER NOT NULL,
    feedback   TEXT,
    decided_by TEXT NOT NULL,
    decided_at REAL NOT NULL,
    PRIMARY KEY (run_id, step_index, change_id)
);

-- Append-only. Never UPDATEd, never DELETEd.
CREATE TABLE IF NOT EXISTS commits (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    step_index  INTEGER NOT NULL,
    change_id   TEXT NOT NULL,
    approved    INTEGER NOT NULL,
    document_id TEXT,
    version     TEXT,
    at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS leases (
    run_id     TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    fence      INTEGER NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    step_index INTEGER,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    at         REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events (run_id, seq);
CREATE INDEX IF NOT EXISTS idx_commits_run ON commits (run_id, seq);
"""


class LedgerError(RuntimeError):
    """Base class for ledger failures."""


class ConcurrentTransition(LedgerError):
    """A step was not in the state the caller expected.

    Raised when a compare-and-swap loses: another runner already moved this step.
    The correct response is to reload and re-decide, never to force the write.
    """


class LeaseLost(LedgerError):
    """This runner no longer holds the run's lease."""


_STEP_COLUMNS = (
    "run_id, step_index, step_id, doc_slug, instruction, token, state, attempt, "
    "job_id, disposition, evidence, pre_hash, post_hash, started_at, ended_at, "
    "billable_ops, duration_ms, error, verify_json, verification, verification_detail"
)

_MUTABLE_STEP_FIELDS = frozenset({
    "attempt", "job_id", "disposition", "evidence", "pre_hash", "post_hash",
    "started_at", "ended_at", "billable_ops", "duration_ms", "error",
    "verification", "verification_detail",
})


def _row_to_step(row: sqlite3.Row) -> Step:
    return Step(
        run_id=row["run_id"],
        step_index=row["step_index"],
        step_id=row["step_id"],
        doc_slug=row["doc_slug"],
        instruction=row["instruction"],
        token=row["token"],
        state=row["state"],
        attempt=row["attempt"],
        job_id=row["job_id"],
        disposition=row["disposition"],
        evidence=row["evidence"],
        pre_hash=row["pre_hash"],
        post_hash=row["post_hash"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        billable_ops=row["billable_ops"],
        duration_ms=row["duration_ms"],
        error=row["error"],
        verify_json=row["verify_json"],
        verification=row["verification"],
        verification_detail=row["verification_detail"],
    )


class Ledger:
    """Durable state for every run. Safe to open from several processes at once."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread. SQLite forbids sharing a connection across threads,
        # and its own file locking already serialises writers — so per-thread connections
        # give the web server's worker and its request handlers the same concurrency
        # story as two separate processes, rather than a second, different one.
        self._local = threading.local()
        self._connect()  # fail fast on an unusable database, and install the schema

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        return conn if conn is not None else self._connect()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL keeps readers from blocking the writer; FULL means a committed
        # transaction has been fsynced before we act on it having "happened".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One atomic, durable write. BEGIN IMMEDIATE takes the write lock up front,
        so two processes serialise here instead of discovering the conflict at COMMIT."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    # --- runs -------------------------------------------------------------

    def create_run(
        self, run: Run, documents: list[Document], steps: list[Step]
    ) -> None:
        """Write a whole plan in one transaction: a run either exists fully or not at all."""
        now = time.time()
        with self._write() as c:
            c.execute(
                "INSERT INTO runs (run_id, spec_path, spec_hash, session_id, status, "
                "created_at, updated_at, meta_json) VALUES (?,?,?,?,?,?,?,?)",
                (run.run_id, run.spec_path, run.spec_hash, run.session_id,
                 run.status, now, now, json.dumps(run.meta, sort_keys=True)),
            )
            c.executemany(
                "INSERT INTO documents (run_id, slug, source_path, source_sha256, "
                "title, document_id, state) VALUES (?,?,?,?,?,?,?)",
                [(d.run_id, d.slug, d.source_path, d.source_sha256, d.title,
                  d.document_id, d.state) for d in documents],
            )
            c.executemany(
                "INSERT INTO steps (run_id, step_index, step_id, doc_slug, instruction, "
                "token, state, verify_json) VALUES (?,?,?,?,?,?,?,?)",
                [(s.run_id, s.step_index, s.step_id, s.doc_slug, s.instruction,
                  s.token, s.state, s.verify_json) for s in steps],
            )
            c.execute(
                "INSERT INTO events (run_id, step_index, kind, detail, at) VALUES (?,?,?,?,?)",
                (run.run_id, None, "run.planned",
                 f"{len(steps)} steps over {len(documents)} documents", now),
            )

    def get_run(self, run_id: str) -> Run | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return Run(
            run_id=row["run_id"], spec_path=row["spec_path"], spec_hash=row["spec_hash"],
            session_id=row["session_id"], status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            meta=json.loads(row["meta_json"]),
        )

    def list_runs(self) -> list[Run]:
        rows = self._conn.execute(
            "SELECT run_id FROM runs ORDER BY created_at DESC"
        ).fetchall()
        return [r for r in (self.get_run(row["run_id"]) for row in rows) if r]

    def set_run_status(self, run_id: str, status: str) -> None:
        with self._write() as c:
            c.execute(
                "UPDATE runs SET status=?, updated_at=? WHERE run_id=?",
                (status, time.time(), run_id),
            )

    # --- documents --------------------------------------------------------

    def get_documents(self, run_id: str) -> list[Document]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE run_id=? ORDER BY slug", (run_id,)
        ).fetchall()
        return [
            Document(
                run_id=r["run_id"], slug=r["slug"], source_path=r["source_path"],
                source_sha256=r["source_sha256"], title=r["title"],
                document_id=r["document_id"], state=r["state"],
            )
            for r in rows
        ]

    def get_document(self, run_id: str, slug: str) -> Document | None:
        for d in self.get_documents(run_id):
            if d.slug == slug:
                return d
        return None

    def bind_document(self, run_id: str, slug: str, document_id: str) -> None:
        """Record the SuperDocs id for a local document. Idempotent by design:
        binding the same id twice is a no-op, binding a different one is a conflict."""
        with self._write() as c:
            cur = c.execute(
                "UPDATE documents SET document_id=?, state='uploaded' "
                "WHERE run_id=? AND slug=? AND (document_id IS NULL OR document_id=?)",
                (document_id, run_id, slug, document_id),
            )
            if cur.rowcount == 0:
                raise ConcurrentTransition(
                    f"document {slug} is already bound to a different SuperDocs id"
                )
            c.execute(
                "INSERT INTO events (run_id, step_index, kind, detail, at) VALUES (?,?,?,?,?)",
                (run_id, None, "document.bound", f"{slug} -> {document_id}", time.time()),
            )

    # --- steps ------------------------------------------------------------

    def get_steps(self, run_id: str) -> list[Step]:
        rows = self._conn.execute(
            f"SELECT {_STEP_COLUMNS} FROM steps WHERE run_id=? ORDER BY step_index",
            (run_id,),
        ).fetchall()
        return [_row_to_step(r) for r in rows]

    def get_step(self, run_id: str, step_index: int) -> Step:
        row = self._conn.execute(
            f"SELECT {_STEP_COLUMNS} FROM steps WHERE run_id=? AND step_index=?",
            (run_id, step_index),
        ).fetchone()
        if row is None:
            raise LedgerError(f"no step {step_index} in run {run_id}")
        return _row_to_step(row)

    def transition(
        self,
        run_id: str,
        step_index: int,
        *,
        expect: str | tuple[str, ...],
        to: str,
        fence: int | None = None,
        **fields: Any,
    ) -> Step:
        """Move a step from an expected state to a new one, atomically and durably.

        The CAS on ``state`` is the whole point: if another process already advanced
        this step, this call raises :class:`ConcurrentTransition` rather than writing.
        """
        expected = (expect,) if isinstance(expect, str) else tuple(expect)
        unknown = set(fields) - _MUTABLE_STEP_FIELDS
        if unknown:
            raise LedgerError(f"not writable step fields: {sorted(unknown)}")

        assignments = ["state=?"]
        params: list[Any] = [to]
        for key, value in sorted(fields.items()):
            assignments.append(f"{key}=?")
            params.append(value)
        placeholders = ",".join("?" for _ in expected)
        params.extend([run_id, step_index, *expected])

        with self._write() as c:
            if fence is not None:
                self._assert_fence(c, run_id, fence)
            cur = c.execute(
                f"UPDATE steps SET {', '.join(assignments)} "
                f"WHERE run_id=? AND step_index=? AND state IN ({placeholders})",
                params,
            )
            if cur.rowcount == 0:
                current = c.execute(
                    "SELECT state FROM steps WHERE run_id=? AND step_index=?",
                    (run_id, step_index),
                ).fetchone()
                found = current["state"] if current else "<missing>"
                raise ConcurrentTransition(
                    f"step {step_index}: expected {expected}, found {found!r}"
                )
            c.execute(
                "INSERT INTO events (run_id, step_index, kind, detail, at) VALUES (?,?,?,?,?)",
                (run_id, step_index, "step.transition",
                 f"{'|'.join(expected)} -> {to}", time.time()),
            )
        return self.get_step(run_id, step_index)

    def set_step_fields(self, run_id: str, step_index: int, **fields: Any) -> None:
        """Update bookkeeping fields without touching state (timings, cost, error)."""
        unknown = set(fields) - _MUTABLE_STEP_FIELDS
        if unknown:
            raise LedgerError(f"not writable step fields: {sorted(unknown)}")
        if not fields:
            return
        assignments = [f"{k}=?" for k in sorted(fields)]
        params = [fields[k] for k in sorted(fields)] + [run_id, step_index]
        with self._write() as c:
            c.execute(
                f"UPDATE steps SET {', '.join(assignments)} WHERE run_id=? AND step_index=?",
                params,
            )

    # --- proposals --------------------------------------------------------

    def put_proposals(self, proposals: list[Proposal]) -> None:
        """Persist proposed changes verbatim, so the gate survives a crash without
        needing to re-ask the model for them."""
        if not proposals:
            return
        with self._write() as c:
            for ordinal, p in enumerate(proposals):
                c.execute(
                    "INSERT OR REPLACE INTO proposals (run_id, step_index, change_id, "
                    "ordinal, operation, chunk_id, document_id, old_html, new_html, "
                    "ai_explanation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (p.run_id, p.step_index, p.change_id, ordinal, p.operation,
                     p.chunk_id, p.document_id, p.old_html, p.new_html, p.ai_explanation),
                )

    def get_proposals(self, run_id: str, step_index: int) -> list[Proposal]:
        rows = self._conn.execute(
            "SELECT * FROM proposals WHERE run_id=? AND step_index=? ORDER BY ordinal",
            (run_id, step_index),
        ).fetchall()
        return [
            Proposal(
                run_id=r["run_id"], step_index=r["step_index"], change_id=r["change_id"],
                operation=r["operation"], chunk_id=r["chunk_id"],
                document_id=r["document_id"], old_html=r["old_html"],
                new_html=r["new_html"], ai_explanation=r["ai_explanation"],
            )
            for r in rows
        ]

    # --- decisions --------------------------------------------------------

    def put_decisions(self, decisions: list[Decision]) -> None:
        if not decisions:
            return
        with self._write() as c:
            for d in decisions:
                c.execute(
                    "INSERT OR REPLACE INTO decisions (run_id, step_index, change_id, "
                    "approved, feedback, decided_by, decided_at) VALUES (?,?,?,?,?,?,?)",
                    (d.run_id, d.step_index, d.change_id, int(d.approved), d.feedback,
                     d.decided_by, d.decided_at),
                )

    def get_decisions(self, run_id: str, step_index: int) -> list[Decision]:
        rows = self._conn.execute(
            "SELECT d.* FROM decisions d JOIN proposals p "
            "  ON d.run_id=p.run_id AND d.step_index=p.step_index AND d.change_id=p.change_id "
            "WHERE d.run_id=? AND d.step_index=? ORDER BY p.ordinal",
            (run_id, step_index),
        ).fetchall()
        return [
            Decision(
                run_id=r["run_id"], step_index=r["step_index"], change_id=r["change_id"],
                approved=bool(r["approved"]), feedback=r["feedback"],
                decided_by=r["decided_by"], decided_at=r["decided_at"],
            )
            for r in rows
        ]

    # --- commits (append-only) --------------------------------------------

    def append_commits(self, commits: list[Commit]) -> None:
        if not commits:
            return
        with self._write() as c:
            for cm in commits:
                c.execute(
                    "INSERT INTO commits (run_id, step_index, change_id, approved, "
                    "document_id, version, at) VALUES (?,?,?,?,?,?,?)",
                    (cm.run_id, cm.step_index, cm.change_id, int(cm.approved),
                     cm.document_id, cm.version, cm.at),
                )

    def get_commits(self, run_id: str) -> list[Commit]:
        rows = self._conn.execute(
            "SELECT * FROM commits WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [
            Commit(
                seq=r["seq"], run_id=r["run_id"], step_index=r["step_index"],
                change_id=r["change_id"], approved=bool(r["approved"]),
                document_id=r["document_id"], version=r["version"], at=r["at"],
            )
            for r in rows
        ]

    # --- leases -----------------------------------------------------------

    def acquire_lease(self, run_id: str, owner: str, ttl: float = 60.0) -> int:
        """Claim exclusive execution of a run. Returns a monotonic fencing token.

        A killed process never releases its lease, so a lease must be reclaimable two
        ways. Both are used:

        * **Provably dead** — the holder is on this host and its pid is gone. Reclaimed
          at once, because waiting out a timer for a process that cannot return is only
          downtime. This is the ordinary case after a crash.
        * **Expired** — the holder is elsewhere, or its liveness cannot be established.
          Reclaimed once the lease times out; the runner renews on every step, so a dead
          holder's lease lapses within one TTL.

        The fence increases on every claim, so a process that somehow resurrects after
        losing its lease cannot write with a stale one.
        """
        now = time.time()
        with self._write() as c:
            row = c.execute("SELECT * FROM leases WHERE run_id=?", (run_id,)).fetchone()
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                if _owner_is_alive(row["owner"]) is not False:
                    raise LeaseLost(
                        f"run {run_id} is held by {row['owner']} for another "
                        f"{row['expires_at'] - now:.0f}s"
                    )
                c.execute(
                    "INSERT INTO events (run_id, step_index, kind, detail, at) "
                    "VALUES (?,?,?,?,?)",
                    (run_id, None, "lease.reclaimed",
                     f"{row['owner']} is gone from this host", now),
                )
            fence = (row["fence"] + 1) if row is not None else 1
            c.execute(
                "INSERT OR REPLACE INTO leases (run_id, owner, fence, expires_at) "
                "VALUES (?,?,?,?)",
                (run_id, owner, fence, now + ttl),
            )
            c.execute(
                "INSERT INTO events (run_id, step_index, kind, detail, at) VALUES (?,?,?,?,?)",
                (run_id, None, "lease.acquired", f"{owner} fence={fence}", now),
            )
        return fence

    def renew_lease(self, run_id: str, owner: str, fence: int, ttl: float = 60.0) -> None:
        with self._write() as c:
            self._assert_fence(c, run_id, fence, owner=owner)
            c.execute(
                "UPDATE leases SET expires_at=? WHERE run_id=? AND fence=?",
                (time.time() + ttl, run_id, fence),
            )

    def release_lease(self, run_id: str, owner: str, fence: int) -> None:
        with self._write() as c:
            c.execute(
                "DELETE FROM leases WHERE run_id=? AND owner=? AND fence=?",
                (run_id, owner, fence),
            )

    @staticmethod
    def _assert_fence(
        c: sqlite3.Connection, run_id: str, fence: int, owner: str | None = None
    ) -> None:
        row = c.execute("SELECT * FROM leases WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row["fence"] != fence or (owner and row["owner"] != owner):
            held = f"{row['owner']}/{row['fence']}" if row else "<none>"
            raise LeaseLost(f"run {run_id}: fence {fence} is stale (held: {held})")

    # --- events -----------------------------------------------------------

    def event(
        self, run_id: str, kind: str, detail: str = "", step_index: int | None = None
    ) -> None:
        with self._write() as c:
            c.execute(
                "INSERT INTO events (run_id, step_index, kind, detail, at) VALUES (?,?,?,?,?)",
                (run_id, step_index, kind, detail, time.time()),
            )

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def _owner_is_alive(owner: str) -> bool | None:
    """Is the lease holder still running? ``None`` when it cannot be established.

    Only answers for owners on this host, where a pid can actually be probed. Anything
    else is unknown, and unknown is treated as alive so the TTL decides — never guessing
    a remote holder is dead is what keeps two hosts from running the same run at once.
    """
    # Parsed from the right: a hostname may itself contain colons. This machine started
    # reporting "Unknown_86:ae:73:f8:f0:67" after a network change, and splitting from the
    # left made every owner unparseable — so every dead lease looked alive and no crashed
    # run could ever be resumed. The pid and the nonce are always the last two fields.
    try:
        host, pid_text, _nonce = owner.rsplit(":", 2)
        pid = int(pid_text)
    except ValueError:
        return None
    if host != os.uname().nodename:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The pid exists under another user. Existing is enough to count as alive.
        return True
    except OSError:
        return None
    return True


def new_owner_id() -> str:
    """Identify one runner process: host, pid, and a nonce so a recycled pid is distinct.

    The host is written verbatim, colons and all, and :func:`_owner_is_alive` parses from
    the right. Sanitising it here would not help: leases written by an older version are
    still in the ledger, and they have to stay readable.
    """
    return f"{os.uname().nodename}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
