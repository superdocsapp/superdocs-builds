"""Kill a review worker after one decision, then reconcile and finish exactly once."""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

RUN_ID = "synthetic-promotion-review"
SESSION_ID = "promotion_crash_resume_session"
JOB_ID = "job_crash_resume"
BASE_DOCUMENT = "Promotion packet\nApproved evidence:\n"
PROPOSALS = [
    {
        "id": "proposal-impact",
        "before": "",
        "after": "Reduced incidents by 42 percent (source: incident-review.txt).",
        "source_artifact": "incident-review.txt",
    },
    {
        "id": "proposal-recovery",
        "before": "",
        "after": "Improved recovery time by 31 percent (source: unsupported-note.txt).",
        "source_artifact": "unsupported-note.txt",
    },
]


def connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS workflow (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            document_text TEXT NOT NULL,
            pending_json TEXT NOT NULL,
            decisions_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_job (
            job_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            status TEXT NOT NULL,
            document_text TEXT NOT NULL,
            pending_json TEXT NOT NULL,
            update_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS effect_outbox (
            idempotency_key TEXT PRIMARY KEY,
            effect_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """
    )
    return connection


def _audit(connection: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO audit_log(event_type,payload_json) VALUES (?,?)",
        (event_type, json.dumps(payload, sort_keys=True)),
    )


def worker(database: Path, ready: Path) -> int:
    """Create the provider/local checkpoint and remain alive at the review gate."""

    with closing(connect(database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT OR IGNORE INTO workflow
            (run_id,status,version,session_id,job_id,document_text,pending_json,decisions_json)
            VALUES (?,'AWAITING_REVIEW',1,?,?,?,?, '[]')""",
            (
                RUN_ID,
                SESSION_ID,
                JOB_ID,
                BASE_DOCUMENT,
                json.dumps(PROPOSALS, sort_keys=True),
            ),
        )
        connection.execute(
            """INSERT OR IGNORE INTO provider_job
            (job_id,session_id,status,document_text,pending_json)
            VALUES (?,?,'awaiting_approval',?,?)""",
            (JOB_ID, SESSION_ID, BASE_DOCUMENT, json.dumps(PROPOSALS, sort_keys=True)),
        )
        _audit(
            connection,
            "REVIEW_CHECKPOINT_COMMITTED",
            {"run_id": RUN_ID, "job_id": JOB_ID, "pending": 2},
        )
        connection.commit()
    ready.write_text("awaiting-review", encoding="utf-8")
    time.sleep(300)
    return 0


def record_first_decision(database: Path) -> None:
    """Persist one approval while its sibling deliberately remains pending."""

    decision = {"change_id": "proposal-impact", "approved": True}
    with closing(connect(database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        updated = connection.execute(
            """UPDATE workflow SET status='PARTIALLY_DECIDED', version=version+1,
            decisions_json=? WHERE run_id=? AND status='AWAITING_REVIEW'""",
            (json.dumps([decision], sort_keys=True), RUN_ID),
        )
        if updated.rowcount != 1:
            raise RuntimeError("first decision could not be recorded")
        _audit(connection, "PRE_CRASH_DECISION_RECORDED", decision)
        connection.commit()


class FakeSuperDocsTransport:
    """Deterministic durable provider used by CI; methods mirror GET/approve/export."""

    def __init__(self, database: Path) -> None:
        self.database = database

    def get_job(self, job_id: str) -> dict[str, Any]:
        with closing(connect(self.database)) as connection:
            row = connection.execute(
                "SELECT * FROM provider_job WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            return {"job_id": job_id, "status": "expired"}
        return {
            "job_id": str(row["job_id"]),
            "session_id": str(row["session_id"]),
            "status": str(row["status"]),
            "pending_changes": json.loads(row["pending_json"]),
            "document_text": str(row["document_text"]),
            "update_count": int(row["update_count"]),
        }

    def approve_change(
        self,
        *,
        job_id: str,
        decisions: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        with closing(connect(self.database)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT completed FROM effect_outbox WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing and int(existing["completed"]) == 1:
                connection.rollback()
                return self.get_job(job_id)
            connection.execute(
                """INSERT OR IGNORE INTO effect_outbox
                (idempotency_key,effect_type,payload_json) VALUES (?,'APPROVE_CHANGE',?)""",
                (idempotency_key, json.dumps(decisions, sort_keys=True)),
            )
            row = connection.execute(
                "SELECT document_text,pending_json FROM provider_job WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("provider job disappeared during recovery")
            proposals = {item["id"]: item for item in json.loads(row["pending_json"])}
            approved_lines = [
                proposals[item["change_id"]]["after"]
                for item in decisions
                if item["approved"] and item["change_id"] in proposals
            ]
            document = str(row["document_text"])
            for line in approved_lines:
                if line not in document:
                    document += line + "\n"
            connection.execute(
                """UPDATE provider_job SET status='completed',document_text=?,
                update_count=update_count+1 WHERE job_id=?""",
                (document, job_id),
            )
            connection.execute(
                "UPDATE effect_outbox SET completed=1 WHERE idempotency_key=?",
                (idempotency_key,),
            )
            connection.commit()
        return self.get_job(job_id)

    def export_document(self, job_id: str) -> bytes:
        job = self.get_job(job_id)
        if job["status"] != "completed":
            raise RuntimeError("only a completed provider job can be exported")
        return _minimal_docx(str(job["document_text"]))


def _minimal_docx(text: str) -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in text.splitlines()
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}<w:sectPr/></w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def _validate_export(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            document = archive.read("word/document.xml").decode("utf-8")
    except (KeyError, OSError, zipfile.BadZipFile, UnicodeDecodeError):
        return False
    return (
        {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names
        and "incident-review.txt" in document
        and "unsupported-note.txt" not in document
    )


def resume(database: Path) -> dict[str, Any]:
    provider = FakeSuperDocsTransport(database)
    with closing(connect(database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM workflow WHERE run_id=?", (RUN_ID,)).fetchone()
        if row is None:
            raise RuntimeError("local checkpoint missing")
        decisions = json.loads(row["decisions_json"])
        job = provider.get_job(str(row["job_id"]))
        if job.get("status") == "expired":
            raise RuntimeError("provider job expired; manual recovery required")
        if job["session_id"] != row["session_id"]:
            raise RuntimeError("provider session changed across restart")
        pending_ids = {
            item["id"] for item in job["pending_changes"]
        } - {item["change_id"] for item in decisions}
        if str(row["status"]) != "COMPLETE":
            _audit(
                connection,
                "POST_RESTART_JOB_RECONCILED",
                {"job_id": job["job_id"], "pending_change_ids": sorted(pending_ids)},
            )
            decisions.append(
                {
                    "change_id": "proposal-recovery",
                    "approved": False,
                    "feedback": "The supplied source does not independently support this claim.",
                }
            )
            connection.execute(
                "UPDATE workflow SET decisions_json=? WHERE run_id=?",
                (json.dumps(decisions, sort_keys=True), RUN_ID),
            )
            connection.commit()
            provider_job = provider.approve_change(
                job_id=JOB_ID,
                decisions=decisions,
                idempotency_key=f"{RUN_ID}:review-v2",
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE workflow SET status='COMPLETE',version=version+1,document_text=?
                WHERE run_id=?""",
                (provider_job["document_text"], RUN_ID),
            )
            _audit(
                connection,
                "RECOVERY_COMPLETED",
                {"provider_update_count": provider_job["update_count"]},
            )
            connection.commit()
        final = connection.execute("SELECT * FROM workflow WHERE run_id=?", (RUN_ID,)).fetchone()
        audit = [
            str(item["event_type"])
            for item in connection.execute("SELECT event_type FROM audit_log ORDER BY sequence")
        ]
    provider_job = provider.get_job(JOB_ID)
    exported = provider.export_document(JOB_ID)
    return {
        "recovery_pid": os.getpid(),
        "status": str(final["status"]),
        "session_id": str(final["session_id"]),
        "job_id": str(final["job_id"]),
        "decisions": json.loads(final["decisions_json"]),
        "document_text": str(final["document_text"]),
        "provider_update_count": provider_job["update_count"],
        "audit_events": audit,
        "export_bytes": len(exported),
        "export_valid": _validate_export(exported),
    }


def run_demo() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="superdocs-crash-resume-") as temporary:
        root = Path(temporary)
        database = root / "workflow.sqlite3"
        ready = root / "ready"
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(database), str(ready)]
        )
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("worker exited before the review checkpoint")
            time.sleep(0.05)
        if not ready.exists():
            child.kill()
            raise TimeoutError("worker never committed the review checkpoint")
        record_first_decision(database)
        child.kill()
        child.wait(timeout=10)

        def recover_in_fresh_process(output: Path) -> dict[str, Any]:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--resume",
                    str(database),
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if completed.stderr:
                raise RuntimeError(completed.stderr)
            return json.loads(output.read_text(encoding="utf-8"))

        started = time.perf_counter()
        first = recover_in_fresh_process(root / "first-recovery.json")
        second = recover_in_fresh_process(root / "replay-recovery.json")
        elapsed = round((time.perf_counter() - started) * 1_000, 3)
        decision_map = {item["change_id"]: item["approved"] for item in first["decisions"]}
        proof = {
            "process_was_killed": child.returncode is not None,
            "fresh_recovery_process": (
                first["recovery_pid"] != os.getpid()
                and first["recovery_pid"] != second["recovery_pid"]
            ),
            "provider_session_restored": first["session_id"] == SESSION_ID,
            "provider_job_restored": first["job_id"] == JOB_ID,
            "first_decision_preserved": decision_map.get("proposal-impact") is True,
            "second_was_pending_after_restart": "POST_RESTART_JOB_RECONCILED"
            in first["audit_events"],
            "mixed_decisions_preserved": first["decisions"] == second["decisions"],
            "document_state_preserved": first["document_text"].startswith(BASE_DOCUMENT),
            "approved_change_applied": "incident-review.txt" in first["document_text"],
            "rejected_change_not_applied": "unsupported-note.txt" not in first["document_text"],
            "provider_document_updates": second["provider_update_count"],
            "duplicate_logical_effects": second["provider_update_count"] - 1,
            "pre_and_post_crash_audit_present": {
                "PRE_CRASH_DECISION_RECORDED",
                "POST_RESTART_JOB_RECONCILED",
                "RECOVERY_COMPLETED",
            }.issubset(first["audit_events"]),
            "export_valid": first["export_valid"],
            "export_bytes": first["export_bytes"],
            "resumed_status": second["status"],
            "resume_and_replay_latency_ms": elapsed,
        }
        return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("database", type=Path, nargs="?")
    parser.add_argument("marker", type=Path, nargs="?")
    args = parser.parse_args()
    if args.worker:
        if args.database is None or args.marker is None:
            parser.error("worker mode requires database and ready paths")
        return worker(args.database, args.marker)
    if args.resume:
        if args.database is None or args.marker is None:
            parser.error("resume mode requires database and output paths")
        args.marker.write_text(
            json.dumps(resume(args.database), sort_keys=True), encoding="utf-8"
        )
        return 0
    proof = run_demo()
    print(json.dumps(proof, indent=2, sort_keys=True))
    required = all(
        value is True
        for key, value in proof.items()
        if key
        in {
            "process_was_killed",
            "fresh_recovery_process",
            "provider_session_restored",
            "provider_job_restored",
            "first_decision_preserved",
            "second_was_pending_after_restart",
            "mixed_decisions_preserved",
            "document_state_preserved",
            "approved_change_applied",
            "rejected_change_not_applied",
            "pre_and_post_crash_audit_present",
            "export_valid",
        }
    )
    return 0 if required and proof["duplicate_logical_effects"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
