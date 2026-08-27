from __future__ import annotations

import json
import sqlite3
from typing import Any

from .core import Patent


class ClaimStore:
    """SQLite persistence boundary: current patent state, its revision history,
    and the paired amendment proposals that gate every change.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS patents (patent_id TEXT PRIMARY KEY, current_json TEXT NOT NULL, current_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions (patent_id TEXT NOT NULL, revision INTEGER NOT NULL, patent_json TEXT NOT NULL, content_hash TEXT NOT NULL, PRIMARY KEY (patent_id, revision));
        CREATE TABLE IF NOT EXISTS proposals (proposal_id TEXT PRIMARY KEY, patent_id TEXT NOT NULL, base_revision INTEGER NOT NULL, plan_json TEXT NOT NULL, state TEXT NOT NULL, decision_json TEXT);
        """)
        self.connection.commit()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def save_patent(self, patent: Patent) -> None:
        data, content_hash = json.dumps(patent.to_dict(), sort_keys=True), patent.content_hash()
        self.connection.execute("INSERT OR REPLACE INTO patents VALUES (?, ?, ?)", (patent.patent_id, data, content_hash))
        self.connection.execute("INSERT OR REPLACE INTO revisions VALUES (?, ?, ?, ?)", (patent.patent_id, patent.revision, data, content_hash))
        self.connection.commit()

    def get_patent(self, patent_id: str) -> Patent | None:
        row = self.connection.execute("SELECT current_json FROM patents WHERE patent_id = ?", (patent_id,)).fetchone()
        return Patent.from_dict(json.loads(row["current_json"])) if row else None

    def get_revision(self, patent_id: str, revision: int) -> Patent | None:
        row = self.connection.execute(
            "SELECT patent_json FROM revisions WHERE patent_id = ? AND revision = ?", (patent_id, revision)
        ).fetchone()
        return Patent.from_dict(json.loads(row["patent_json"])) if row else None

    def save_proposal(self, proposal_id: str, patent_id: str, base_revision: int, plan: dict[str, Any], state: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO proposals VALUES (?, ?, ?, ?, ?, NULL)",
            (proposal_id, patent_id, base_revision, json.dumps(plan, sort_keys=True), state),
        )
        self.connection.commit()

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if not row:
            return None
        return {
            "proposal_id": row["proposal_id"], "patent_id": row["patent_id"], "base_revision": row["base_revision"],
            "plan": json.loads(row["plan_json"]), "state": row["state"],
            "decision": json.loads(row["decision_json"]) if row["decision_json"] else None,
        }

    def decide_proposal(self, proposal_id: str, state: str, decision: dict[str, Any]) -> None:
        self.connection.execute(
            "UPDATE proposals SET state = ?, decision_json = ? WHERE proposal_id = ?",
            (state, json.dumps(decision, sort_keys=True), proposal_id),
        )
        self.connection.commit()
