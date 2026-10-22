from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    superdocs_session_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    original_bytes BLOB NOT NULL,
    approval_policy TEXT NOT NULL DEFAULT 'dual_consent',
    shared_channel_id TEXT NOT NULL,
    current_version TEXT NOT NULL DEFAULT 'v1',
    version_number INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deal_documents (
    id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES deals(id),
    superdocs_document_id TEXT,
    filename TEXT NOT NULL,
    original_bytes BLOB NOT NULL,
    role TEXT NOT NULL DEFAULT 'supporting',
    added_by_side TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES deals(id),
    instruction TEXT NOT NULL,
    requested_by_side TEXT NOT NULL,
    requested_by_user TEXT NOT NULL,
    state TEXT NOT NULL,
    thread_ts TEXT,
    document_id TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES deals(id),
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    change_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_html TEXT,
    new_html TEXT,
    ai_explanation TEXT NOT NULL,
    proposed_by_side TEXT NOT NULL,
    document_id TEXT,
    chunk_id TEXT,
    insert_after_chunk_id TEXT,
    vendor_decision TEXT,
    customer_decision TEXT,
    vendor_feedback TEXT,
    customer_feedback TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    card_ts TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL REFERENCES deals(id),
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    proposal_id TEXT,
    detail TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS internal_notes (
    id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES deals(id),
    side TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deal_documents_deal ON deal_documents(deal_id);
CREATE INDEX IF NOT EXISTS idx_proposals_deal ON proposals(deal_id);
CREATE INDEX IF NOT EXISTS idx_proposals_job ON proposals(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_deal ON audit_log(deal_id, seq);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class DealRow:
    id: str
    name: str
    superdocs_session_id: str
    original_filename: str
    original_bytes: bytes
    approval_policy: str
    shared_channel_id: str
    current_version: str
    status: str
    created_at: str
    version_number: int = 1

    @property
    def display_version(self) -> str:
        """A version people can say out loud.

        SuperDocs identifies versions by UUID, which is right for traceability and
        useless in a Slack message -- nobody reads 'updated to b196b9f1-4aff-...'.
        The UUID stays in current_version and in the audit trail; this is what the
        cards show.
        """
        return f"v{self.version_number}"


@dataclass
class DocumentRow:
    id: str
    deal_id: str
    superdocs_document_id: str | None
    filename: str
    original_bytes: bytes
    role: str
    added_by_side: str
    created_at: str = ""


@dataclass
class ProposalRow:
    id: str
    deal_id: str
    job_id: str
    change_id: str
    operation: str
    old_html: str | None
    new_html: str | None
    ai_explanation: str
    proposed_by_side: str
    document_id: str | None = None
    chunk_id: str | None = None
    insert_after_chunk_id: str | None = None
    vendor_decision: str | None = None
    customer_decision: str | None = None
    vendor_feedback: str | None = None
    customer_feedback: str | None = None
    state: str = "pending"
    card_ts: str | None = None
    created_at: str = ""
    resolved_at: str | None = None


@dataclass
class JobRow:
    job_id: str
    deal_id: str
    instruction: str
    requested_by_side: str
    requested_by_user: str
    state: str
    thread_ts: str | None = None
    document_id: str | None = None
    idempotency_key: str | None = None
    created_at: str = ""


@dataclass
class AuditEntry:
    seq: int
    deal_id: str
    ts: str
    actor: str
    side: str
    action: str
    proposal_id: str | None
    detail: dict[str, Any] = field(default_factory=dict)


class Store:
    def __init__(self, database_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created.

        SQLite's CREATE TABLE IF NOT EXISTS silently does nothing when the table already
        exists, so a database created by an older build keeps its old shape. Each entry
        here is idempotent: we look at the live schema and only ALTER what is missing.
        """
        added: list[tuple[str, str, str]] = [
            ("jobs", "document_id", "TEXT"),
            ("proposals", "document_id", "TEXT"),
            ("deals", "version_number", "INTEGER NOT NULL DEFAULT 1"),
            ("jobs", "idempotency_key", "TEXT"),
            ("proposals", "chunk_id", "TEXT"),
            ("proposals", "insert_after_chunk_id", "TEXT"),
        ]
        for table, column, column_type in added:
            existing = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")
            }
            if column not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            rows = cursor.fetchall()
            self._conn.commit()
            return rows

    def create_deal(
        self,
        deal_id: str,
        name: str,
        session_id: str,
        filename: str,
        original_bytes: bytes,
        approval_policy: str,
        shared_channel_id: str,
    ) -> DealRow:
        self._execute(
            "INSERT INTO deals (id, name, superdocs_session_id, original_filename,"
            " original_bytes, approval_policy, shared_channel_id, current_version,"
            " status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'v1', 'active', ?)",
            (
                deal_id,
                name,
                session_id,
                filename,
                original_bytes,
                approval_policy,
                shared_channel_id,
                utcnow(),
            ),
        )
        return self.get_deal(deal_id)

    def get_deal(self, deal_id: str) -> DealRow:
        rows = self._execute("SELECT * FROM deals WHERE id = ?", (deal_id,))
        if not rows:
            raise KeyError(f"deal {deal_id!r} not found")
        return self._deal_from_row(rows[0])

    def latest_active_deal_for_channel(self, channel_id: str) -> DealRow | None:
        rows = self._execute(
            "SELECT * FROM deals WHERE shared_channel_id = ? AND status = 'active'"
            " ORDER BY rowid DESC LIMIT 1",
            (channel_id,),
        )
        return self._deal_from_row(rows[0]) if rows else None

    def list_deals(self) -> list[DealRow]:
        rows = self._execute("SELECT * FROM deals ORDER BY rowid")
        return [self._deal_from_row(row) for row in rows]

    @staticmethod
    def _deal_from_row(row: sqlite3.Row) -> DealRow:
        return DealRow(
            id=row["id"],
            name=row["name"],
            superdocs_session_id=row["superdocs_session_id"],
            original_filename=row["original_filename"],
            original_bytes=row["original_bytes"],
            approval_policy=row["approval_policy"],
            shared_channel_id=row["shared_channel_id"],
            current_version=row["current_version"],
            version_number=row["version_number"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def add_document(self, document: DocumentRow) -> DocumentRow:
        self._execute(
            "INSERT INTO deal_documents (id, deal_id, superdocs_document_id, filename,"
            " original_bytes, role, added_by_side, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.id,
                document.deal_id,
                document.superdocs_document_id,
                document.filename,
                document.original_bytes,
                document.role,
                document.added_by_side,
                utcnow(),
            ),
        )
        return self.get_document(document.id)

    def get_document(self, document_id: str) -> DocumentRow:
        rows = self._execute("SELECT * FROM deal_documents WHERE id = ?", (document_id,))
        if not rows:
            raise KeyError(f"document {document_id!r} not found")
        return self._document_from_row(rows[0])

    def documents_for_deal(self, deal_id: str) -> list[DocumentRow]:
        rows = self._execute(
            "SELECT * FROM deal_documents WHERE deal_id = ? ORDER BY rowid",
            (deal_id,),
        )
        return [self._document_from_row(r) for r in rows]

    def document_by_superdocs_id(self, deal_id: str, superdocs_document_id: str) -> DocumentRow:
        rows = self._execute(
            "SELECT * FROM deal_documents WHERE deal_id = ? AND superdocs_document_id = ?",
            (deal_id, superdocs_document_id),
        )
        if not rows:
            raise KeyError(
                f"no document with SuperDocs id {superdocs_document_id!r} in deal {deal_id!r}"
            )
        return self._document_from_row(rows[0])

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> DocumentRow:
        return DocumentRow(
            id=row["id"],
            deal_id=row["deal_id"],
            superdocs_document_id=row["superdocs_document_id"],
            filename=row["filename"],
            original_bytes=row["original_bytes"],
            role=row["role"],
            added_by_side=row["added_by_side"],
            created_at=row["created_at"],
        )

    def set_deal_version(self, deal_id: str, version: str) -> None:
        """Record SuperDocs' version id and advance the human-facing counter."""
        self._execute(
            "UPDATE deals SET current_version = ?, version_number = version_number + 1"
            " WHERE id = ?",
            (version, deal_id),
        )

    def set_deal_status(self, deal_id: str, status: str) -> None:
        self._execute("UPDATE deals SET status = ? WHERE id = ?", (status, deal_id))

    def set_document_role(self, document_id: str, role: str) -> None:
        self._execute(
            "UPDATE deal_documents SET role = ? WHERE id = ?", (role, document_id)
        )

    def create_job(self, job: JobRow) -> None:
        self._execute(
            "INSERT INTO jobs (job_id, deal_id, instruction, requested_by_side,"
            " requested_by_user, state, thread_ts, document_id, idempotency_key, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.job_id,
                job.deal_id,
                job.instruction,
                job.requested_by_side,
                job.requested_by_user,
                job.state,
                job.thread_ts,
                job.document_id,
                job.idempotency_key,
                utcnow(),
            ),
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> JobRow:
        return JobRow(
            job_id=row["job_id"],
            deal_id=row["deal_id"],
            instruction=row["instruction"],
            requested_by_side=row["requested_by_side"],
            requested_by_user=row["requested_by_user"],
            state=row["state"],
            thread_ts=row["thread_ts"],
            document_id=row["document_id"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

    def get_job(self, job_id: str) -> JobRow:
        rows = self._execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        if not rows:
            raise KeyError(f"job {job_id!r} not found")
        return self._job_from_row(rows[0])

    def jobs_in_states(self, *states: str) -> list[JobRow]:
        placeholders = ",".join("?" for _ in states)
        rows = self._execute(
            f"SELECT * FROM jobs WHERE state IN ({placeholders})", states
        )
        return [self._job_from_row(r) for r in rows]

    def find_job_by_idempotency_key(
        self,
        deal_id: str,
        idempotency_key: str,
        active_states: tuple[str, ...],
        window_seconds: float,
    ) -> JobRow | None:
        """Find a job that a repeated request should be folded into, or None.

        A job matches when it carries the same key on the same deal AND either it is
        still in flight (any of `active_states`), or it was created inside the dedupe
        window. In-flight jobs match regardless of age on purpose: if the identical
        instruction is already sitting in review, starting a second one bills a second
        operation for a decision the humans have not made yet.
        """
        placeholders = ",".join("?" for _ in active_states)
        clauses = [f"state IN ({placeholders})"]
        params: list[Any] = [deal_id, idempotency_key, *active_states]

        # Timestamps are stored to the second, so a window of zero would still match
        # anything created in the same second. Treat "no window" as exactly that and
        # drop the clause, leaving only in-flight jobs to dedupe against.
        if window_seconds > 0:
            cutoff = (
                datetime.now(UTC) - timedelta(seconds=window_seconds)
            ).isoformat(timespec="seconds")
            clauses.append("created_at >= ?")
            params.append(cutoff)

        rows = self._execute(
            "SELECT * FROM jobs WHERE deal_id = ? AND idempotency_key = ?"
            f" AND ({' OR '.join(clauses)})"
            " ORDER BY rowid DESC LIMIT 1",
            tuple(params),
        )
        return self._job_from_row(rows[0]) if rows else None

    def set_job_state(self, job_id: str, state: str, thread_ts: str | None = None) -> None:
        if thread_ts is not None:
            self._execute(
                "UPDATE jobs SET state = ?, thread_ts = ? WHERE job_id = ?",
                (state, thread_ts, job_id),
            )
        else:
            self._execute(
                "UPDATE jobs SET state = ? WHERE job_id = ?", (state, job_id)
            )

    def insert_proposals(self, proposals: list[ProposalRow]) -> None:
        for p in proposals:
            self._execute(
                "INSERT INTO proposals (id, deal_id, job_id, change_id, operation, old_html,"
                " new_html, ai_explanation, proposed_by_side, document_id, chunk_id,"
                " insert_after_chunk_id, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    p.id,
                    p.deal_id,
                    p.job_id,
                    p.change_id,
                    p.operation,
                    p.old_html,
                    p.new_html,
                    p.ai_explanation,
                    p.proposed_by_side,
                    p.document_id,
                    p.chunk_id,
                    p.insert_after_chunk_id,
                    utcnow(),
                ),
            )

    def get_proposal(self, proposal_id: str) -> ProposalRow:
        rows = self._execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        if not rows:
            raise KeyError(f"proposal {proposal_id!r} not found")
        return self._proposal_from_row(rows[0])

    def proposals_for_job(self, job_id: str) -> list[ProposalRow]:
        rows = self._execute(
            "SELECT * FROM proposals WHERE job_id = ? ORDER BY rowid", (job_id,)
        )
        return [self._proposal_from_row(r) for r in rows]

    def proposals_for_deal(self, deal_id: str) -> list[ProposalRow]:
        rows = self._execute(
            "SELECT * FROM proposals WHERE deal_id = ? ORDER BY rowid", (deal_id,)
        )
        return [self._proposal_from_row(r) for r in rows]

    def pending_proposals_for_deal(self, deal_id: str) -> list[ProposalRow]:
        rows = self._execute(
            "SELECT * FROM proposals WHERE deal_id = ? AND state = 'pending'"
            " ORDER BY rowid",
            (deal_id,),
        )
        return [self._proposal_from_row(r) for r in rows]

    def committed_proposals_for_deal(self, deal_id: str) -> list[ProposalRow]:
        rows = self._execute(
            "SELECT * FROM proposals WHERE deal_id = ? AND state = 'committed'"
            " ORDER BY rowid",
            (deal_id,),
        )
        return [self._proposal_from_row(r) for r in rows]

    def set_proposal_card_ts(self, proposal_id: str, card_ts: str) -> None:
        self._execute(
            "UPDATE proposals SET card_ts = ? WHERE id = ?", (card_ts, proposal_id)
        )

    def record_decision(
        self, proposal_id: str, side: str, approved: bool, feedback: str | None
    ) -> ProposalRow:
        column = f"{side}_decision"
        feedback_column = f"{side}_feedback"
        state = "approved" if approved else "rejected"
        self._execute(
            f"UPDATE proposals SET {column} = ?, {feedback_column} = ? WHERE id = ?",
            (state, feedback, proposal_id),
        )
        return self.get_proposal(proposal_id)

    def resolve_proposal(self, proposal_id: str, state: str) -> ProposalRow:
        self._execute(
            "UPDATE proposals SET state = ?, resolved_at = ? WHERE id = ?",
            (state, utcnow(), proposal_id),
        )
        return self.get_proposal(proposal_id)

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> ProposalRow:
        return ProposalRow(
            id=row["id"],
            deal_id=row["deal_id"],
            job_id=row["job_id"],
            change_id=row["change_id"],
            operation=row["operation"],
            old_html=row["old_html"],
            new_html=row["new_html"],
            ai_explanation=row["ai_explanation"],
            proposed_by_side=row["proposed_by_side"],
            document_id=row["document_id"],
            chunk_id=row["chunk_id"],
            insert_after_chunk_id=row["insert_after_chunk_id"],
            vendor_decision=row["vendor_decision"],
            customer_decision=row["customer_decision"],
            vendor_feedback=row["vendor_feedback"],
            customer_feedback=row["customer_feedback"],
            state=row["state"],
            card_ts=row["card_ts"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def add_audit(
        self,
        deal_id: str,
        actor: str,
        side: str,
        action: str,
        proposal_id: str | None = None,
        **detail: Any,
    ) -> AuditEntry:
        ts = utcnow()
        self._execute(
            "INSERT INTO audit_log (deal_id, ts, actor, side, action, proposal_id, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (deal_id, ts, actor, side, action, proposal_id, json.dumps(detail)),
        )
        rows = self._execute("SELECT last_insert_rowid() AS seq")
        return AuditEntry(
            seq=int(rows[0]["seq"]),
            deal_id=deal_id,
            ts=ts,
            actor=actor,
            side=side,
            action=action,
            proposal_id=proposal_id,
            detail=detail,
        )

    def history(self, deal_id: str) -> list[AuditEntry]:
        rows = self._execute(
            "SELECT * FROM audit_log WHERE deal_id = ? ORDER BY seq", (deal_id,)
        )
        return [
            AuditEntry(
                seq=r["seq"],
                deal_id=r["deal_id"],
                ts=r["ts"],
                actor=r["actor"],
                side=r["side"],
                action=r["action"],
                proposal_id=r["proposal_id"],
                detail=json.loads(r["detail"] or "{}"),
            )
            for r in rows
        ]

    def save_internal_note(
        self, note_id: str, deal_id: str, side: str, author: str, body: str
    ) -> None:
        self._execute(
            "INSERT INTO internal_notes (id, deal_id, side, author, body, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (note_id, deal_id, side, author, body, utcnow()),
        )

    def internal_notes(self, deal_id: str, side: str | None = None) -> list[dict[str, str]]:
        if side:
            rows = self._execute(
                "SELECT * FROM internal_notes WHERE deal_id = ? AND side = ? ORDER BY rowid",
                (deal_id, side),
            )
        else:
            rows = self._execute(
                "SELECT * FROM internal_notes WHERE deal_id = ? ORDER BY rowid",
                (deal_id,),
            )
        return [
            {
                "id": r["id"],
                "side": r["side"],
                "author": r["author"],
                "body": r["body"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
