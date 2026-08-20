"""Portable durable SQLite state machine with revision and idempotency guards."""
from __future__ import annotations
import hashlib, json, sqlite3, time
from typing import Any

TERMINAL = {"COMPLETED", "BLOCKED", "CANCELLED"}

class Store:
    def __init__(self, path: str = ":memory:"):
        self.db=sqlite3.connect(path); self.db.row_factory=sqlite3.Row; self.db.execute("PRAGMA journal_mode=WAL"); self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(job_id,kind,payload));
        CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, UNIQUE(job_id,stage));
        CREATE TABLE IF NOT EXISTS worker_lease(id INTEGER PRIMARY KEY CHECK(id=1), worker_id TEXT NOT NULL, acquired REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS effects(job_id TEXT NOT NULL, effect_key TEXT NOT NULL, result TEXT NOT NULL, UNIQUE(job_id,effect_key));
        """); self.db.commit()
    def create_job(self, job_id: str, payload: dict[str,Any], state: str = "QUEUED") -> None:
        self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)", (job_id,state,0,json.dumps(payload),time.time())); self.db.commit()
    def get_job(self, job_id: str) -> dict[str,Any] | None:
        row=self.db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone(); return dict(row) if row else None
    def transition(self, job_id: str, expected_revision: int, state: str, *, event: str | None = None, payload: dict[str,Any] | None = None) -> int:
        cur=self.db.execute("UPDATE jobs SET state=?,revision=revision+1,updated=? WHERE id=? AND revision=?",(state,time.time(),job_id,expected_revision))
        if cur.rowcount != 1: raise RuntimeError("stale revision")
        if event: self.db.execute("INSERT OR IGNORE INTO events(job_id,kind,payload) VALUES(?,?,?)",(job_id,event,json.dumps(payload or {},sort_keys=True)))
        self.db.commit(); return expected_revision+1
    def idempotent(self, key: str, request: dict[str,Any], result: dict[str,Any]) -> dict[str,Any]:
        digest=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest(); row=self.db.execute("SELECT * FROM idempotency WHERE key=?",(key,)).fetchone()
        if row:
            if row["request_hash"] != digest: raise ValueError("idempotency key reused with a different request")
            return json.loads(row["result"])
        self.db.execute("INSERT INTO idempotency VALUES(?,?,?)",(key,digest,json.dumps(result))); self.db.commit(); return result
    def events(self, job_id: str) -> list[dict[str,Any]]: return [dict(x) for x in self.db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id",(job_id,))]
    def enqueue(self, job_id: str, stage: str, payload: dict[str, Any]) -> None:
        self.db.execute("INSERT OR IGNORE INTO outbox(job_id,stage,payload) VALUES(?,?,?)", (job_id, stage, json.dumps(payload, sort_keys=True))); self.db.commit()
    def pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(x) for x in self.db.execute("SELECT * FROM outbox WHERE sent=0 ORDER BY id LIMIT ?", (limit,))]
    def mark_outbox_sent(self, outbox_id: int) -> None:
        self.db.execute("UPDATE outbox SET sent=1 WHERE id=?", (outbox_id,)); self.db.commit()
    def recoverable_jobs(self) -> list[dict[str, Any]]:
        return [dict(x) for x in self.db.execute("SELECT * FROM jobs WHERE state NOT IN ('COMPLETED','BLOCKED','CANCELLED') ORDER BY updated")]
    def claim_worker(self, worker_id: str) -> None:
        try: self.db.execute("INSERT INTO worker_lease VALUES(1,?,?)", (worker_id, time.time())); self.db.commit()
        except sqlite3.IntegrityError as exc: raise RuntimeError("single-worker lease already held") from exc
    def release_worker(self, worker_id: str) -> None:
        self.db.execute("DELETE FROM worker_lease WHERE id=1 AND worker_id=?", (worker_id,)); self.db.commit()
    def record_effect(self, job_id: str, effect_key: str, result: dict[str, Any]) -> dict[str, Any]:
        row=self.db.execute("SELECT result FROM effects WHERE job_id=? AND effect_key=?",(job_id,effect_key)).fetchone()
        if row: return json.loads(row[0])
        self.db.execute("INSERT INTO effects VALUES(?,?,?)",(job_id,effect_key,json.dumps(result,sort_keys=True))); self.db.commit(); return result
