from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from typing import Any, Iterator


class DurableStore:
    """Small SQLite persistence boundary for the offline fixture."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._keeper = sqlite3.connect(path, check_same_thread=False) if path == ":memory:" else None
        self._initialize(self._keeper or sqlite3.connect(path))

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._keeper or sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            if self._keeper is None:
                connection.commit()
        finally:
            if self._keeper is None:
                connection.close()

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                tenant_id TEXT NOT NULL, run_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                version INTEGER NOT NULL, input_hash TEXT NOT NULL, snapshots TEXT NOT NULL,
                findings TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                tenant_id TEXT NOT NULL, run_id TEXT NOT NULL, item_id TEXT NOT NULL,
                finding TEXT NOT NULL, decision TEXT NOT NULL, reviewer TEXT,
                rationale TEXT, decided_at TEXT, PRIMARY KEY (run_id, item_id)
            );
            CREATE TABLE IF NOT EXISTS operations (
                tenant_id TEXT NOT NULL, operation_key TEXT NOT NULL, operation TEXT NOT NULL,
                result TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, operation_key)
            );
            CREATE TABLE IF NOT EXISTS exports (
                tenant_id TEXT NOT NULL, run_id TEXT PRIMARY KEY, artifact_hash TEXT NOT NULL,
                artifact TEXT NOT NULL, certificate TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        connection.commit()

    def create_run(self, run: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run["tenant_id"], run["run_id"], run["state"], run["version"], run["input_hash"],
                 json.dumps(run["snapshots"], sort_keys=True), json.dumps(run["findings"], sort_keys=True),
                 run["created_at"], run["updated_at"]),
            )
            for item_id, finding in run["items"].items():
                connection.execute(
                    "INSERT INTO decisions VALUES (?, ?, ?, ?, 'pending', NULL, NULL, NULL)",
                    (run["tenant_id"], run["run_id"], item_id, json.dumps(finding, sort_keys=True)),
                )

    def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE tenant_id = ? AND run_id = ?", (tenant_id, run_id)).fetchone()
            if row is None:
                return None
            decisions = connection.execute("SELECT * FROM decisions WHERE run_id = ? ORDER BY item_id", (run_id,)).fetchall()
        return {
            "tenant_id": row["tenant_id"], "run_id": row["run_id"], "state": row["state"],
            "version": row["version"], "input_hash": row["input_hash"],
            "snapshots": json.loads(row["snapshots"]), "findings": json.loads(row["findings"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "items": {
                decision["item_id"]: {
                    "item_id": decision["item_id"], "finding": json.loads(decision["finding"]),
                    "decision": decision["decision"], "reviewer": decision["reviewer"],
                    "rationale": decision["rationale"], "decided_at": decision["decided_at"],
                }
                for decision in decisions
            },
        }

    def decide(
        self, tenant_id: str, run_id: str, item_id: str, decision: str, reviewer: str,
        rationale: str, decided_at: str, expected_version: int, state: str, updated_at: str,
    ) -> bool:
        with self.connection() as connection:
            updated = connection.execute(
                "UPDATE runs SET state = ?, version = version + 1, updated_at = ? WHERE tenant_id = ? AND run_id = ? AND version = ?",
                (state, updated_at, tenant_id, run_id, expected_version),
            )
            if updated.rowcount != 1:
                return False
            changed = connection.execute(
                "UPDATE decisions SET decision = ?, reviewer = ?, rationale = ?, decided_at = ? WHERE tenant_id = ? AND run_id = ? AND item_id = ? AND decision = 'pending'",
                (decision, reviewer, rationale, decided_at, tenant_id, run_id, item_id),
            )
            if changed.rowcount != 1:
                raise ValueError("review item is already decided or unknown")
            return True

    def operation_result(self, tenant_id: str, operation_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT result FROM operations WHERE tenant_id = ? AND operation_key = ?",
                (tenant_id, operation_key),
            ).fetchone()
        return json.loads(row["result"]) if row else None

    def save_operation(self, tenant_id: str, operation_key: str, operation: str, result: dict[str, Any], created_at: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?)",
                (tenant_id, operation_key, operation, json.dumps(result, sort_keys=True), created_at),
            )

    def save_export(self, tenant_id: str, run_id: str, artifact_hash: str, artifact: dict[str, Any], certificate: dict[str, Any], created_at: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO exports VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, run_id, artifact_hash, json.dumps(artifact, sort_keys=True), json.dumps(certificate, sort_keys=True), created_at),
            )

    def get_export(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM exports WHERE tenant_id = ? AND run_id = ?", (tenant_id, run_id)).fetchone()
        if row is None:
            return None
        return {
            "run_id": run_id, "artifact_hash": row["artifact_hash"],
            "artifact": json.loads(row["artifact"]), "certificate": json.loads(row["certificate"]),
            "created_at": row["created_at"],
        }
