from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from typing import Any, Iterator


class DurableStore:
    """SQLite fixture store; production can replace this boundary with PostgreSQL."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._keeper = sqlite3.connect(path) if path == ":memory:" else None
        self._initialize(self._keeper or sqlite3.connect(path))

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._keeper or sqlite3.connect(self.path)
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
                tenant_id TEXT NOT NULL,
                build_id TEXT NOT NULL,
                run_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                source_hash TEXT NOT NULL,
                source_record TEXT NOT NULL,
                document TEXT NOT NULL,
                reconciliation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                finding TEXT NOT NULL,
                decision TEXT NOT NULL,
                approver TEXT,
                decided_at TEXT,
                PRIMARY KEY (run_id, item_id)
            );
            CREATE TABLE IF NOT EXISTS operations (
                tenant_id TEXT NOT NULL,
                operation_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, operation_key)
            );
            CREATE TABLE IF NOT EXISTS exports (
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                certificate TEXT NOT NULL,
                artifact TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id)
            );
            """
        )
        connection.commit()

    def create_run(self, run: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run["tenant_id"], run["build_id"], run["run_id"], run["state"], run["version"],
                 run["source_hash"], json.dumps(run["source_record"], sort_keys=True),
                 json.dumps(run["document"], sort_keys=True), json.dumps(run["reconciliation"], sort_keys=True),
                 run["created_at"], run["updated_at"]),
            )
            for item_id, finding in run["items"].items():
                connection.execute(
                    "INSERT INTO decisions VALUES (?, ?, ?, ?, 'pending', NULL, NULL)",
                    (run["tenant_id"], run["run_id"], item_id, json.dumps(finding, sort_keys=True)),
                )

    def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE tenant_id = ? AND run_id = ?", (tenant_id, run_id)).fetchone()
            if row is None:
                return None
            decisions = connection.execute("SELECT * FROM decisions WHERE run_id = ? ORDER BY item_id", (run_id,)).fetchall()
        return {
            "tenant_id": row["tenant_id"], "build_id": row["build_id"], "run_id": row["run_id"],
            "state": row["state"], "version": row["version"], "source_hash": row["source_hash"],
            "source_record": json.loads(row["source_record"]), "document": json.loads(row["document"]),
            "reconciliation": json.loads(row["reconciliation"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "items": {
                decision["item_id"]: {"item_id": decision["item_id"], "finding": json.loads(decision["finding"]),
                                      "decision": decision["decision"], "approver": decision["approver"]}
                for decision in decisions
            },
        }

    def update_run(self, tenant_id: str, run_id: str, expected_version: int, state: str, document: dict[str, Any], reconciliation: dict[str, Any], updated_at: str) -> bool:
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE runs SET state = ?, version = version + 1, document = ?, reconciliation = ?, updated_at = ? WHERE tenant_id = ? AND run_id = ? AND version = ?",
                (state, json.dumps(document, sort_keys=True), json.dumps(reconciliation, sort_keys=True), updated_at, tenant_id, run_id, expected_version),
            )
            if result.rowcount == 1:
                connection.execute("DELETE FROM decisions WHERE tenant_id = ? AND run_id = ?", (tenant_id, run_id))
                for index, finding in enumerate(reconciliation["findings"]):
                    connection.execute(
                        "INSERT INTO decisions VALUES (?, ?, ?, ?, 'pending', NULL, NULL)",
                        (tenant_id, run_id, f"finding-{index}", json.dumps(finding, sort_keys=True)),
                    )
            return result.rowcount == 1

    def decide(self, tenant_id: str, run_id: str, item_id: str, decision: str, approver: str, decided_at: str, expected_version: int, state: str, updated_at: str) -> bool:
        with self.connection() as connection:
            updated = connection.execute(
                "UPDATE runs SET state = ?, version = version + 1, updated_at = ? WHERE tenant_id = ? AND run_id = ? AND version = ?",
                (state, updated_at, tenant_id, run_id, expected_version),
            )
            if updated.rowcount != 1:
                return False
            result = connection.execute(
                "UPDATE decisions SET decision = ?, approver = ?, decided_at = ? WHERE tenant_id = ? AND run_id = ? AND item_id = ? AND decision = 'pending'",
                (decision, approver, decided_at, tenant_id, run_id, item_id),
            )
            if result.rowcount != 1:
                raise ValueError("review item is already decided or unknown")
            return True

    def operation_result(self, tenant_id: str, operation_key: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT result FROM operations WHERE tenant_id = ? AND operation_key = ?", (tenant_id, operation_key)).fetchone()
        return json.loads(row["result"]) if row else None

    def save_operation(self, tenant_id: str, operation_key: str, operation: str, result: dict[str, Any], created_at: str) -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO operations VALUES (?, ?, ?, ?, ?)", (tenant_id, operation_key, operation, json.dumps(result, sort_keys=True), created_at))

    def save_export(self, tenant_id: str, run_id: str, artifact_hash: str, certificate: dict[str, Any], artifact: dict[str, Any], created_at: str) -> None:
        with self.connection() as connection:
            connection.execute("INSERT OR REPLACE INTO exports VALUES (?, ?, ?, ?, ?, ?)", (tenant_id, run_id, artifact_hash, json.dumps(certificate, sort_keys=True), json.dumps(artifact, sort_keys=True), created_at))

    def get_export(self, tenant_id: str, run_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM exports WHERE tenant_id = ? AND run_id = ?", (tenant_id, run_id)).fetchone()
        if row is None:
            return None
        return {"artifact_hash": row["artifact_hash"], "certificate": json.loads(row["certificate"]), "artifact": json.loads(row["artifact"]), "created_at": row["created_at"]}
