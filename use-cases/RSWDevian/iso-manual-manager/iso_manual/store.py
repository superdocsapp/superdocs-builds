from __future__ import annotations

import json
import sqlite3
from typing import Any

from .model import Manual


class ManualStore:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS manuals (manual_id TEXT PRIMARY KEY, current_json TEXT NOT NULL, current_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions (manual_id TEXT NOT NULL, revision INTEGER NOT NULL, manual_json TEXT NOT NULL, artifact_hash TEXT NOT NULL, PRIMARY KEY (manual_id, revision));
        CREATE TABLE IF NOT EXISTS proposals (proposal_id TEXT PRIMARY KEY, manual_id TEXT NOT NULL, base_revision INTEGER NOT NULL, plan_json TEXT NOT NULL, state TEXT NOT NULL, decision_json TEXT);
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

    def save_manual(self, manual: Manual) -> None:
        data, content_hash = json.dumps(manual.to_dict(), sort_keys=True), manual.content_hash()
        self.connection.execute("INSERT OR REPLACE INTO manuals VALUES (?, ?, ?)", (manual.manual_id, data, content_hash))
        self.connection.execute("INSERT OR REPLACE INTO revisions VALUES (?, ?, ?, ?)", (manual.manual_id, manual.revision, data, content_hash))
        self.connection.commit()

    def get_manual(self, manual_id: str) -> Manual | None:
        row = self.connection.execute("SELECT current_json FROM manuals WHERE manual_id = ?", (manual_id,)).fetchone()
        return Manual.from_dict(json.loads(row["current_json"])) if row else None

    def get_revision(self, manual_id: str, revision: int) -> tuple[Manual, str] | None:
        row = self.connection.execute("SELECT manual_json, artifact_hash FROM revisions WHERE manual_id = ? AND revision = ?", (manual_id, revision)).fetchone()
        return (Manual.from_dict(json.loads(row["manual_json"])), row["artifact_hash"]) if row else None

    def save_proposal(self, proposal_id: str, manual_id: str, base_revision: int, plan: dict[str, Any], state: str) -> None:
        self.connection.execute("INSERT OR REPLACE INTO proposals VALUES (?, ?, ?, ?, ?, NULL)", (proposal_id, manual_id, base_revision, json.dumps(plan, sort_keys=True), state))
        self.connection.commit()

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if not row:
            return None
        return {"proposal_id": row["proposal_id"], "manual_id": row["manual_id"], "base_revision": row["base_revision"], "plan": json.loads(row["plan_json"]), "state": row["state"], "decision": json.loads(row["decision_json"]) if row["decision_json"] else None}

    def decide_proposal(self, proposal_id: str, state: str, decision: dict[str, Any]) -> None:
        self.connection.execute("UPDATE proposals SET state = ?, decision_json = ? WHERE proposal_id = ?", (state, json.dumps(decision, sort_keys=True), proposal_id))
        self.connection.commit()
