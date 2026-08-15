"""The claim register: one SQLite file, and the only thing both halves read.

The reconciler writes claims and findings into it; the readiness pack reads the
same rows and formats them. Neither is a bolt-on to the other, and there is no
second store anywhere in this project — a coverage number that disagrees with
the review queue is the failure this design exists to prevent.

## Why SQLite and not a directory of JSON

Because two sweeps can run at once and must not corrupt each other, and because
resume-after-kill has to be exact rather than approximate. Both are transaction
problems, and a directory of files solves neither without reimplementing a
database badly. WAL mode plus a busy timeout gives concurrent readers during a
write, and every mutation below is a single statement inside a transaction, so
a process killed mid-sweep leaves the register at a row boundary rather than
half way through one.

## Idempotency

Every write is an upsert keyed by `claim_id` or `finding_id`, both of which are
content-derived (see `claims.py`). Running the same sweep twice produces the
same ids and therefore the same rows — the second run updates `last_seen` and
changes nothing else. This is what makes "kill it and start again" safe, and it
is why no code in this project checks whether it has already done something
before doing it: doing it twice is defined to be the same as doing it once.

The one exception is deliberate and is the reason `decision` and `applied_at`
are updated by their own narrow methods rather than by the general upsert: a
re-run must never quietly un-approve something a human approved, so
`upsert_finding` preserves those three columns when a row already exists.

## Timestamps

UTC ISO-8601, seconds resolution, stored as text. SQLite has no date type and
inventing one here would only mean two ways to read the same column.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reconciler.claims import Anchor, Claim, Decision, Finding, Verdict

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id     TEXT PRIMARY KEY,
    page_id      TEXT NOT NULL,
    page_version INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    subject      TEXT NOT NULL,
    asserted     TEXT NOT NULL,
    excerpt      TEXT NOT NULL,
    heading_path TEXT NOT NULL,
    node_index   INTEGER NOT NULL,
    occurrence   INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL,
    editable     INTEGER NOT NULL,
    refusal      TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS claims_by_page ON claims(page_id);
CREATE INDEX IF NOT EXISTS claims_by_subject ON claims(subject);

CREATE TABLE IF NOT EXISTS findings (
    finding_id    TEXT PRIMARY KEY,
    claim_id      TEXT REFERENCES claims(claim_id),
    page_id       TEXT,
    rule_id       TEXT NOT NULL,
    kind          TEXT NOT NULL,
    subject       TEXT NOT NULL,
    verdict       TEXT NOT NULL CHECK (verdict IN ('agrees', 'contradicts', 'unverifiable')),
    observed      TEXT,
    evidence_file TEXT NOT NULL,
    evidence_line INTEGER,
    confidence    REAL NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    tags          TEXT NOT NULL DEFAULT '[]',
    proposed      TEXT,
    decision      TEXT CHECK (decision IN ('approved', 'rejected')),
    decided_at    TEXT,
    applied_at    TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS findings_by_verdict ON findings(verdict);
CREATE INDEX IF NOT EXISTS findings_by_page ON findings(page_id);
CREATE UNIQUE INDEX IF NOT EXISTS findings_one_per_claim
    ON findings(claim_id, rule_id) WHERE claim_id IS NOT NULL;

-- A SuperDocs batch parked awaiting approval, and which finding each change
-- answers. This is state that has to survive a restart: a turn left at
-- `awaiting_approval` holds its session, so a run that forgets about one leaves
-- a session that answers `409 session_busy` for ever. `rr status` reads this
-- table to find them.
CREATE TABLE IF NOT EXISTS proposals (
    finding_id  TEXT PRIMARY KEY REFERENCES findings(finding_id),
    page_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    job_id      TEXT,
    document_id TEXT,
    durable_id  TEXT,
    change_id   TEXT,
    proposed    TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    settled_at  TEXT
);

CREATE INDEX IF NOT EXISTS proposals_by_job ON proposals(job_id);

-- Every version of every page this tool has written, and the mechanism behind
-- rule 6: never re-trigger on our own writes.
--
-- The plan expected `client.account_id()` to do this job -- see the page in
-- the runbook, ignore the version whose author is us. That endpoint turns out
-- to be unreachable with a scoped API token (`401 Unauthorized; scope does not
-- match` from /wiki/api/v2/users/current, /wiki/rest/api/user/current and
-- api.atlassian.com/me alike, with read:user:confluence granted), so the
-- watcher cannot ask who wrote a version.
--
-- It can ask what *we* wrote, which is strictly better evidence anyway: an
-- author id says a human sharing the integration account edited the page, and
-- this says the byte-exact version number our own PUT produced. Recorded in
-- the same transaction that marks the finding applied, so a crash cannot leave
-- a write the watcher does not recognise as its own.
CREATE TABLE IF NOT EXISTS page_writes (
    page_id    TEXT NOT NULL,
    version    INTEGER NOT NULL,
    written_at TEXT NOT NULL,
    PRIMARY KEY (page_id, version)
);

-- Cost and timing accounting. Behaviour ten of the brief: a run can report
-- what it spent and where the time went, stage by stage. Kept in the register
-- rather than printed and forgotten so `rr report` can answer it afterwards,
-- and so the zero-spend claim is a query anyone can run rather than prose.
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    mode        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    note        TEXT NOT NULL DEFAULT ''
);

-- `seq` rather than ordering by `started_at`. Timestamps here are
-- second-resolution and a whole local sweep finishes inside one second, so
-- ordering by time returned the stages in whatever order the index scan felt
-- like -- which read as "the run started with the check stage". The order of a
-- run's stages is data, not an accident of clock resolution.
CREATE TABLE IF NOT EXISTS run_stages (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    stage       TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    seconds     REAL,
    operations  INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, stage)
);
"""


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Register:
    """The register, as a connection plus the handful of queries anyone needs.

    Not an ORM and not a repository pattern. Every method here is a query
    somebody actually asks — the sweep, the review queue, the readiness pack —
    and the SQL is in the open where it can be read.
    """

    def __init__(self, path: str | Path = "register.db") -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        # WAL lets a reader (the review queue, a readiness pack export) run
        # while a sweep is writing. busy_timeout is what turns the *other*
        # sweep's write from `database is locked` into a wait -- without it,
        # "two runs at once" is a crash rather than a queue.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(SCHEMA_VERSION),),
        )

    # ------------------------------------------------------------ plumbing --

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Register:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One unit of work that either lands or does not.

        Used by the multi-page apply path: rule 7 says never leave a multi-page
        update half applied, and the register half of that promise is this.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # -------------------------------------------------------------- claims --

    def upsert_claim(self, claim: Claim) -> str:
        now = utcnow()
        anchor = claim.anchor
        self._conn.execute(
            """
            INSERT INTO claims (claim_id, page_id, page_version, kind, subject, asserted,
                                excerpt, heading_path, node_index, occurrence, content_hash,
                                char_start, char_end, editable, refusal, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(claim_id) DO UPDATE SET
                page_version = excluded.page_version,
                node_index   = excluded.node_index,
                char_start   = excluded.char_start,
                char_end     = excluded.char_end,
                editable     = excluded.editable,
                refusal      = excluded.refusal,
                last_seen    = excluded.last_seen
            """,
            (
                claim.claim_id,
                claim.page_id,
                claim.page_version,
                claim.kind,
                claim.subject,
                claim.asserted,
                claim.excerpt,
                json.dumps(list(claim.anchor.heading_path)),
                anchor.node_index,
                anchor.occurrence,
                anchor.content_hash,
                anchor.char_start,
                anchor.char_end,
                int(anchor.editable),
                anchor.refusal,
                now,
                now,
            ),
        )
        return claim.claim_id

    def upsert_claims(self, claims: Iterable[Claim]) -> list[str]:
        with self.transaction():
            return [self.upsert_claim(claim) for claim in claims]

    def claim(self, claim_id: str) -> Claim | None:
        row = self._conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        return _claim_from_row(row) if row else None

    def claims_for_page(self, page_id: str) -> list[Claim]:
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE page_id = ? ORDER BY node_index, char_start",
            (page_id,),
        ).fetchall()
        return [_claim_from_row(row) for row in rows]

    def claims_for_subject(self, subject: str) -> list[Claim]:
        """Every page that asserts something about one subject.

        This is the multi-document consistency query: the same threshold in the
        runbook, the SLO document and the DR plan comes back as three rows, and
        a fix that lands on one of them is visibly incomplete.
        """
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE subject = ? ORDER BY page_id", (subject,)
        ).fetchall()
        return [_claim_from_row(row) for row in rows]

    def claims_like(self, fragment: str) -> list[Claim]:
        """Every claim whose subject mentions an entity, by any of its names.

        The readiness pack's join. `LIKE` with the fragment bracketed by
        separators rather than a bare substring: `api` must not match
        `payments-api`, or one service's row absorbs another's evidence.
        """
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE subject = ? OR subject LIKE ? OR subject LIKE ? "
            "OR subject LIKE ? ORDER BY page_id, subject",
            (fragment, f"{fragment}:%", f"%:{fragment}", f"%:{fragment}:%"),
        ).fetchall()
        return [_claim_from_row(row) for row in rows]

    def multi_page_subjects(self) -> dict[str, int]:
        """Subjects documented on more than one page, and how many spellings.

        A count of 1 is the good case and worth reporting as loudly as the bad
        one: ten facts repeated across two pages each and agreeing is what
        multi-document consistency looks like when it is working, and a report
        that only ever mentions disagreement cannot show that.
        """
        rows = self._conn.execute(
            "SELECT subject, COUNT(DISTINCT asserted) AS spellings FROM claims "
            "GROUP BY subject HAVING COUNT(DISTINCT page_id) > 1 ORDER BY subject"
        ).fetchall()
        return {row["subject"]: int(row["spellings"]) for row in rows}

    def subjects_with_conflicting_assertions(self) -> dict[str, list[tuple[str, str]]]:
        """Subjects that more than one page asserts, and disagrees about.

        Multi-document consistency, as one query rather than as a pass over
        every claim in Python. Deliberately independent of the estate: two
        documents contradicting each other is worth surfacing even where neither
        can be checked against anything, and it is the one class of problem the
        vertical checker structurally cannot see.
        """
        rows = self._conn.execute("""
            SELECT subject, page_id, asserted FROM claims
            WHERE subject IN (
                SELECT subject FROM claims
                GROUP BY subject
                HAVING COUNT(DISTINCT asserted) > 1 AND COUNT(DISTINCT page_id) > 1
            )
            ORDER BY subject, page_id
            """).fetchall()
        out: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            out.setdefault(row["subject"], []).append((row["page_id"], row["asserted"]))
        return out

    def forget_page(self, page_id: str) -> int:
        """Drop a page's claims and their findings.

        Used when a page is deleted or unlabelled. Findings first: the foreign
        key is real and `PRAGMA foreign_keys=ON` means it is enforced.
        """
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM findings WHERE claim_id IN (SELECT claim_id FROM claims WHERE page_id = ?)",
                (page_id,),
            )
            cursor = conn.execute("DELETE FROM claims WHERE page_id = ?", (page_id,))
            return cursor.rowcount

    # ------------------------------------------------------------ findings --

    def upsert_finding(self, finding: Finding) -> str:
        """Record a verdict, without ever overwriting a human's decision.

        `decision`, `decided_at` and `applied_at` are absent from the update
        clause on purpose. A sweep re-running over a page must not un-approve
        what somebody approved five minutes ago, and the way to guarantee that
        is for the general write path to be structurally incapable of touching
        those columns. `decide()` and `mark_applied()` are the only ways in.
        """
        now = utcnow()
        self._conn.execute(
            """
            INSERT INTO findings (finding_id, claim_id, page_id, rule_id, kind, subject,
                                  verdict, observed, evidence_file, evidence_line, confidence,
                                  detail, tags, proposed, decision, decided_at, applied_at,
                                  first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(finding_id) DO UPDATE SET
                verdict       = excluded.verdict,
                observed      = excluded.observed,
                evidence_file = excluded.evidence_file,
                evidence_line = excluded.evidence_line,
                confidence    = excluded.confidence,
                detail        = excluded.detail,
                tags          = excluded.tags,
                proposed      = COALESCE(excluded.proposed, findings.proposed),
                last_seen     = excluded.last_seen
            """,
            (
                finding.finding_id,
                finding.claim_id,
                finding.page_id,
                finding.rule_id,
                finding.kind,
                finding.subject,
                finding.verdict,
                finding.observed,
                finding.evidence_file,
                finding.evidence_line,
                finding.confidence,
                finding.detail,
                json.dumps(list(finding.tags)),
                finding.proposed,
                finding.decision,
                finding.decided_at,
                finding.applied_at,
                now,
                now,
            ),
        )
        return finding.finding_id

    def upsert_findings(self, findings: Iterable[Finding]) -> list[str]:
        with self.transaction():
            return [self.upsert_finding(f) for f in findings]

    def finding(self, finding_id: str) -> Finding | None:
        row = self._conn.execute(
            "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
        ).fetchone()
        return _finding_from_row(row) if row else None

    def findings(
        self,
        verdict: Verdict | None = None,
        page_id: str | None = None,
        undecided_only: bool = False,
        unapplied_only: bool = False,
        subject: str | None = None,
    ) -> list[Finding]:
        sql = "SELECT * FROM findings WHERE 1=1"
        params: list[Any] = []
        if verdict:
            sql += " AND verdict = ?"
            params.append(verdict)
        if page_id:
            sql += " AND page_id = ?"
            params.append(page_id)
        if subject:
            # Bracketed by separators, like `claims_like`: an entity called
            # `api` must not collect `payments-api`'s findings.
            sql += " AND (subject = ? OR subject LIKE ? OR subject LIKE ? OR subject LIKE ?)"
            params += [subject, f"{subject}:%", f"%:{subject}", f"%:{subject}:%"]
        if undecided_only:
            sql += " AND decision IS NULL"
        if unapplied_only:
            sql += " AND applied_at IS NULL"
        sql += " ORDER BY page_id IS NULL, page_id, subject"
        return [_finding_from_row(row) for row in self._conn.execute(sql, params).fetchall()]

    def review_queue(self) -> list[Finding]:
        """What a human is asked to look at: contradictions nobody has ruled on."""
        return self.findings(verdict="contradicts", undecided_only=True)

    def approved_unapplied(self) -> list[Finding]:
        """Approved, not yet written. The resume path's work list.

        A crash between the approval and the Confluence write leaves rows here,
        and that is the point: the next run finds them rather than losing them.
        """
        rows = self._conn.execute(
            "SELECT * FROM findings WHERE decision = 'approved' AND applied_at IS NULL "
            "ORDER BY page_id, subject"
        ).fetchall()
        return [_finding_from_row(row) for row in rows]

    def decide(self, finding_id: str, decision: Decision) -> None:
        self._conn.execute(
            "UPDATE findings SET decision = ?, decided_at = ? WHERE finding_id = ?",
            (decision, utcnow(), finding_id),
        )

    def set_proposed(self, finding_id: str, proposed: str) -> None:
        self._conn.execute(
            "UPDATE findings SET proposed = ? WHERE finding_id = ?", (proposed, finding_id)
        )

    def mark_applied(self, finding_id: str, when: str | None = None) -> None:
        self._conn.execute(
            "UPDATE findings SET applied_at = ? WHERE finding_id = ?",
            (when or utcnow(), finding_id),
        )

    def summary(self) -> dict[str, int]:
        """The three verdicts and the queue depth, for every summary line.

        `unverifiable` is in here because it is in *every* summary. A count that
        can be omitted is a count that gets omitted on the day it looks bad.
        """
        counts = {
            row["verdict"]: row["n"]
            for row in self._conn.execute(
                "SELECT verdict, COUNT(*) AS n FROM findings GROUP BY verdict"
            )
        }
        return {
            "agrees": counts.get("agrees", 0),
            "contradicts": counts.get("contradicts", 0),
            "unverifiable": counts.get("unverifiable", 0),
            "claims": self._conn.execute("SELECT COUNT(*) AS n FROM claims").fetchone()["n"],
            "awaiting_review": len(self.review_queue()),
            "approved_unapplied": len(self.approved_unapplied()),
        }

    # ------------------------------------------------------------ proposals --

    def record_proposal(
        self,
        finding_id: str,
        page_id: str,
        session_id: str,
        job_id: str | None,
        document_id: str | None,
        durable_id: str | None,
        change_id: str | None,
        proposed: str,
        explanation: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO proposals (finding_id, page_id, session_id, job_id, document_id,
                                   durable_id, change_id, proposed, explanation, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(finding_id) DO UPDATE SET
                session_id  = excluded.session_id,
                job_id      = excluded.job_id,
                document_id = excluded.document_id,
                durable_id  = excluded.durable_id,
                change_id   = excluded.change_id,
                proposed    = excluded.proposed,
                explanation = excluded.explanation
            """,
            (
                finding_id,
                page_id,
                session_id,
                job_id,
                document_id,
                durable_id,
                change_id,
                proposed,
                explanation,
                utcnow(),
            ),
        )
        # The proposal is the answer to the finding, so the finding carries it
        # too. One read for the review queue rather than a join every time.
        self.set_proposed(finding_id, proposed)

    def proposal(self, finding_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE finding_id = ?", (finding_id,)
        ).fetchone()
        return dict(row) if row else None

    def open_batches(self) -> list[dict[str, Any]]:
        """SuperDocs turns still parked awaiting a decision.

        A parked turn holds its session, and a session that nobody ever answers
        refuses every later turn with `409 session_busy`. This is how `rr status`
        finds them after a crash instead of somebody discovering it a week later.
        """
        rows = self._conn.execute(
            "SELECT page_id, session_id, job_id, COUNT(*) AS changes, MIN(created_at) AS opened "
            "FROM proposals WHERE settled_at IS NULL AND job_id IS NOT NULL "
            "GROUP BY session_id, job_id ORDER BY opened"
        ).fetchall()
        return [dict(row) for row in rows]

    def settle_batch(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE proposals SET settled_at = ? WHERE job_id = ? AND settled_at IS NULL",
            (utcnow(), job_id),
        )

    # --------------------------------------------------------- our own writes --

    def record_page_write(self, page_id: str, version: int) -> None:
        """The version our own PUT produced. See the `page_writes` schema note."""
        self._conn.execute(
            "INSERT INTO page_writes (page_id, version, written_at) VALUES (?,?,?) "
            "ON CONFLICT(page_id, version) DO NOTHING",
            (page_id, int(version), utcnow()),
        )

    def wrote_version(self, page_id: str, version: int) -> bool:
        """Did this tool produce that exact version of that page?

        Rule 6, as a query. The watcher asks it before deciding a version bump
        is somebody else's work worth re-sweeping for.
        """
        row = self._conn.execute(
            "SELECT 1 FROM page_writes WHERE page_id = ? AND version = ?",
            (page_id, int(version)),
        ).fetchone()
        return row is not None

    # ----------------------------------------------------------- accounting --

    def start_run(self, mode: str, note: str = "") -> str:
        run_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO runs (run_id, mode, started_at, note) VALUES (?,?,?,?)",
            (run_id, mode, utcnow(), note),
        )
        return run_id

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (utcnow(), status, run_id),
        )

    def record_stage(
        self, run_id: str, stage: str, seconds: float, operations: int = 0, detail: str = ""
    ) -> None:
        now = utcnow()
        self._conn.execute(
            """
            INSERT INTO run_stages (run_id, stage, seq, started_at, finished_at,
                                    seconds, operations, detail)
            VALUES (?, ?, (SELECT COUNT(*) FROM run_stages WHERE run_id = ?), ?,?,?,?,?)
            ON CONFLICT(run_id, stage) DO UPDATE SET
                finished_at = excluded.finished_at,
                seconds     = excluded.seconds,
                operations  = excluded.operations,
                detail      = excluded.detail
            """,
            (run_id, stage, run_id, now, now, seconds, operations, detail),
        )

    def run_cost(self, run_id: str) -> dict[str, Any]:
        stages = [
            dict(row)
            for row in self._conn.execute(
                "SELECT stage, seconds, operations, detail FROM run_stages WHERE run_id = ? "
                "ORDER BY seq",
                (run_id,),
            )
        ]
        return {
            "run_id": run_id,
            "operations": sum(int(s["operations"]) for s in stages),
            "seconds": round(sum(float(s["seconds"] or 0.0) for s in stages), 3),
            "stages": stages,
        }

    def last_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
        ]


def _claim_from_row(row: sqlite3.Row) -> Claim:
    return Claim(
        page_id=row["page_id"],
        page_version=row["page_version"],
        kind=row["kind"],
        subject=row["subject"],
        asserted=row["asserted"],
        excerpt=row["excerpt"],
        anchor=Anchor(
            heading_path=tuple(json.loads(row["heading_path"])),
            node_index=row["node_index"],
            content_hash=row["content_hash"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            editable=bool(row["editable"]),
            refusal=row["refusal"],
            occurrence=row["occurrence"],
        ),
    )


def _finding_from_row(row: sqlite3.Row) -> Finding:
    return Finding(
        rule_id=row["rule_id"],
        kind=row["kind"],
        subject=row["subject"],
        verdict=row["verdict"],
        evidence_file=row["evidence_file"],
        claim_id=row["claim_id"],
        page_id=row["page_id"],
        observed=row["observed"],
        evidence_line=row["evidence_line"],
        confidence=row["confidence"],
        detail=row["detail"],
        proposed=row["proposed"],
        decision=row["decision"],
        decided_at=row["decided_at"],
        applied_at=row["applied_at"],
        tags=tuple(json.loads(row["tags"])),
    )


__all__ = ["Register", "utcnow"]
