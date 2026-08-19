from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DEFAULT_TAXONOMY = [
    "wrong_duplicate", "parent_context_ignored", "semantic_reference_miss",
    "body_text_confusion", "ordinal_reference_error", "relative_position_error",
    "historical_current_confusion", "appendix_confusion", "over_targeting",
    "under_targeting", "no_target_but_modified", "failed_to_clarify",
    "unnecessary_clarification", "correct_section_wrong_answer",
    "correct_section_wrong_edit_range", "lexical_normalization_failure",
    "instruction_scoping_failure", "cross_reference_confusion", "other",
]
TAXONOMY_DEFINITIONS = {
    "wrong_duplicate": "Selected a repeated heading under the wrong document section.",
    "parent_context_ignored": "Ignored the parent heading needed to identify the correct section.",
    "semantic_reference_miss": "Failed to resolve a section described by its meaning rather than its heading.",
    "body_text_confusion": "Mistook related body text for the requested section or evidence.",
    "ordinal_reference_error": "Selected the wrong occurrence when the instruction used first, second, or another ordinal.",
    "relative_position_error": "Misread a section identified by its position relative to another section.",
    "historical_current_confusion": "Used historical or superseded content instead of the current section.",
    "appendix_confusion": "Used appendix material instead of the authoritative main-document section.",
    "over_targeting": "Changed or cited more document content than the instruction required.",
    "under_targeting": "Changed or cited less document content than the instruction required.",
    "no_target_but_modified": "Modified unrelated content even though the requested target did not exist.",
    "failed_to_clarify": "Chose a target when the instruction was genuinely ambiguous and required clarification.",
    "unnecessary_clarification": "Asked for clarification even though the instruction identified one defensible target.",
    "correct_section_wrong_answer": "Found the correct section but returned the wrong answer.",
    "correct_section_wrong_edit_range": "Found the correct section but changed the wrong span or too much content.",
    "lexical_normalization_failure": "Failed to connect equivalent wording, aliases, or normalized terms.",
    "instruction_scoping_failure": "Misread which part of the instruction constrained the target or edit.",
    "cross_reference_confusion": "Followed a related reference instead of the section the instruction intended.",
    "other": "A failure that does not fit another published category.",
}
LEGACY_TAXONOMY = [
    "wrong repeated section", "wrong parent context", "semantic heading confusion",
    "body-text confusion", "over-targeting", "no target found",
    "should have clarified", "wrong answer despite correct target",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection: sqlite3.Connection | None = self._connect() if path == ":memory:" else None
        self.init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self._memory_connection is not None:
            yield self._memory_connection
            self._memory_connection.commit()
            return
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}

    @classmethod
    def _add_columns(cls, db: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
        existing = cls._columns(db, table)
        for name, definition in definitions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def init(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              filename TEXT NOT NULL, content_type TEXT NOT NULL,
              content BLOB NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
              id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
              case_type TEXT NOT NULL CHECK(case_type IN ('search','edit')),
              document_id INTEGER NOT NULL REFERENCES documents(id),
              instruction TEXT NOT NULL, expected_section TEXT NOT NULL,
              expected_answer TEXT, notes TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failure_categories (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
              active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS benchmark_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              selected INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id INTEGER NOT NULL REFERENCES cases(id), status TEXT NOT NULL,
              session_id TEXT, job_id TEXT, textual_response TEXT,
              evidence_json TEXT, raw_response_json TEXT, latency_ms REAL,
              operations_charged INTEGER DEFAULT 0, error TEXT,
              verdict TEXT CHECK(verdict IN ('pass','fail','ambiguous') OR verdict IS NULL),
              failure_category_id INTEGER REFERENCES failure_categories(id),
              adjudication_note TEXT, created_at TEXT NOT NULL, adjudicated_at TEXT
            );
            """)
            self._add_columns(db, "documents", {
                "external_document_id": "TEXT", "fixture_version": "TEXT",
                "expected_sha256": "TEXT", "actual_sha256": "TEXT", "source_path": "TEXT",
            })
            self._add_columns(db, "cases", {
                "external_case_id": "TEXT", "difficulty": "TEXT",
                "expected_behavior": "TEXT DEFAULT 'unique_target'",
                "expected_section_path": "TEXT", "acceptable_section_paths_json": "TEXT DEFAULT '[]'",
                "expected_edit_scope": "TEXT", "must_not_target_json": "TEXT DEFAULT '[]'",
                "capability_tested": "TEXT", "likely_failure_category": "TEXT",
                "rationale": "TEXT", "fixture_version": "TEXT", "expected_document_sha256": "TEXT",
            })
            removed_case_ids = ("D06-C02", "D08-C02")
            placeholders = ",".join("?" for _ in removed_case_ids)
            db.execute(
                f"DELETE FROM runs WHERE case_id IN (SELECT id FROM cases WHERE external_case_id IN ({placeholders}))",
                removed_case_ids,
            )
            db.execute(f"DELETE FROM cases WHERE external_case_id IN ({placeholders})", removed_case_ids)
            self._add_columns(db, "runs", {"benchmark_run_id": "INTEGER REFERENCES benchmark_runs(id)"})
            selected=db.execute("SELECT id FROM benchmark_runs WHERE selected=1 ORDER BY id DESC LIMIT 1").fetchone()
            if not selected:
                selected=db.execute("SELECT id FROM benchmark_runs ORDER BY id DESC LIMIT 1").fetchone()
                if selected:
                    db.execute("UPDATE benchmark_runs SET selected=1 WHERE id=?",(selected["id"],))
                else:
                    cur=db.execute("INSERT INTO benchmark_runs(name,selected,created_at) VALUES (?,?,?)",("Benchmark run 1",1,now()))
                    selected={"id":cur.lastrowid}
            db.execute("UPDATE runs SET benchmark_run_id=? WHERE benchmark_run_id IS NULL",(selected["id"],))
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_external_id ON documents(external_document_id) WHERE external_document_id IS NOT NULL")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cases_external_id ON cases(external_case_id) WHERE external_case_id IS NOT NULL")
            for category in DEFAULT_TAXONOMY:
                db.execute("INSERT INTO failure_categories(name,active) VALUES (?,1) ON CONFLICT(name) DO UPDATE SET active=1", (category,))
            for category in LEGACY_TAXONOMY:
                db.execute("UPDATE failure_categories SET active=0 WHERE name=?", (category,))

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.connect() as db:
            return self.row(db.execute(sql, params).fetchone())

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.connect() as db:
            cur=db.execute(sql,params); return int(cur.lastrowid)

    @staticmethod
    def decode_case(case: dict[str, Any]) -> dict[str, Any]:
        for source,target in (("acceptable_section_paths_json","acceptable_section_paths"),("must_not_target_json","must_not_target")):
            raw=case.pop(source,None); case[target]=json.loads(raw) if raw else []
        case["expected_section_path"] = case.get("expected_section_path") or case.get("expected_section") or None
        return case

    @staticmethod
    def decode_run(run: dict[str, Any]) -> dict[str, Any]:
        for key in ("evidence_json","raw_response_json"):
            raw=run.pop(key,None); run[key.removesuffix("_json")]=json.loads(raw) if raw else None
        return run
