"""Shared fixtures: an isolated study tree (temp dirs, no real API, no real
ledger) and fakes for the SuperDocs client used by pipeline/judge tests."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

DIMENSIONS = [
    "faithfulness",
    "fact_accuracy",
    "content_preservation",
    "structural_integrity",
    "formatting_fidelity",
    "language_quality",
]


def _minimal_rubric() -> dict:
    return {
        "version": "1.0",
        "dimensions": [
            {
                "id": did,
                "label": did.replace("_", " ").title(),
                "description": f"{did} description",
                "anchors": {str(s): f"{did} anchor {s}" for s in range(1, 5)},
            }
            for did in DIMENSIONS
        ],
    }


def _minimal_cases() -> dict:
    return {
        "cases": [
            {"case_id": "plan-01", "doc_id": "project_plan", "doc_file": "a.txt",
             "difficulty": "easy", "instruction": "Add a missing owner to the plan."},
            {"case_id": "meeting-01", "doc_id": "meeting_notes", "doc_file": "b.txt",
             "difficulty": "medium", "instruction": "Record the new attendee."},
        ]
    }


def _sheet(case_id: str, rater: str, scores: dict, evidence: dict = None, **extra) -> dict:
    sheet = {"case_id": case_id, "rater": rater, "scores": dict(scores),
             "evidence": {d: (evidence or {}).get(d, "") for d in DIMENSIONS}}
    sheet.update(extra)
    return sheet


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Isolated study tree with 1 fully-scored case, 1 unedited case.

    All config paths are redirected here; nothing touches the real data/,
    report/, or ledger files. Returns a dict of paths for assertions."""
    base = tmp_path / "tree"
    data = base / "data"
    corpus = data / "corpus"
    edits = data / "edits"
    human_dir = data / "judgments" / "human"
    auto_dir = data / "judgments" / "auto"
    report_dir = base / "report"
    for d in (corpus, edits, human_dir, auto_dir, report_dir):
        d.mkdir(parents=True, exist_ok=True)

    (corpus / "a.txt").write_text("PROJECT PLAN\nOwner: none\n", encoding="utf-8")
    (corpus / "b.txt").write_text("MEETING NOTES\nAttendees: A\n", encoding="utf-8")
    (data / "rubric.json").write_text(json.dumps(_minimal_rubric()), encoding="utf-8")
    (data / "instructions.json").write_text(json.dumps(_minimal_cases()), encoding="utf-8")

    e = edits / "plan-01"
    e.mkdir(parents=True, exist_ok=True)
    (e / "before.html").write_text("<p>Owner: none</p>", encoding="utf-8")
    (e / "after.html").write_text("<p>Owner: Dave</p>", encoding="utf-8")
    (e / "before.md").write_text("PROJECT PLAN\nOwner: none\n", encoding="utf-8")
    (e / "after.md").write_text("PROJECT PLAN\nOwner: Dave\n", encoding="utf-8")
    (e / "after.docx").write_bytes(b"fake-docx")
    (e / "upload.json").write_text(json.dumps({"html": "<p>Owner: none</p>"}), encoding="utf-8")
    (e / "chat_start.json").write_text(json.dumps({"job_id": "j1"}), encoding="utf-8")
    (e / "pending_changes.json").write_text(
        json.dumps([{"change_id": "c1", "summary": "add Dave"}]), encoding="utf-8")
    (e / "approve_1.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (e / "job_final.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (e / "chat_result.json").write_text(
        json.dumps({"response": "done", "document_changes": {"updated_html": "<p>Owner: Dave</p>"}}),
        encoding="utf-8")
    (e / "record.json").write_text(json.dumps({
        "case_id": "plan-01", "status": "completed", "session_id": "eqr_plan-01_1",
        "steps": {"approve": {"ok": True, "rounds": 1, "final_status": "completed"}},
    }), encoding="utf-8")

    (human_dir / "plan-01.json").write_text(json.dumps(_sheet(
        "plan-01", "human-1",
        {d: 4 for d in DIMENSIONS},
        {"faithfulness": "owner added"}, difficulty="easy")), encoding="utf-8")
    (auto_dir / "plan-01.json").write_text(json.dumps(_sheet(
        "plan-01", "auto", {d: 4 for d in DIMENSIONS},
        {"faithfulness": "owner added"}, provider="gemini", model="gemini-test",
        difficulty="easy")), encoding="utf-8")

    (data / "ledger.jsonl").write_text(
        json.dumps({"endpoint": "/v1/chat/async", "tag": "edit:plan-01",
                    "was_billable": True, "ops_charged": 1, "monthly_remaining": 499})
        + "\n", encoding="utf-8")

    paths = dict(base=base, data=data, corpus=corpus, edits=edits, human=human_dir,
                 auto=auto_dir, report=report_dir, rubric=data / "rubric.json",
                 instructions=data / "instructions.json", ledger=data / "ledger.jsonl",
                 gemini_ledger=data / "ledger_gemini.jsonl")

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "CORPUS_DIR", corpus)
    monkeypatch.setattr(config, "EDITS_DIR", edits)
    monkeypatch.setattr(config, "HUMAN_DIR", human_dir)
    monkeypatch.setattr(config, "AUTO_DIR", auto_dir)
    monkeypatch.setattr(config, "REPORT_DIR", report_dir)
    monkeypatch.setattr(config, "LEDGER_PATH", paths["ledger"])
    monkeypatch.setattr(config, "GEMINI_LEDGER_PATH", paths["gemini_ledger"])
    monkeypatch.setattr(config, "RUBRIC_PATH", paths["rubric"])
    monkeypatch.setattr(config, "INSTRUCTIONS_PATH", paths["instructions"])
    monkeypatch.setattr(config, "API_KEY", "test-api-key")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-gemini-key")
    return paths


class FakeSuperDocsClient:
    """Scripted stand-in for SuperDocsClient used by EditRunner tests.

    poll_job returns queued jobs in order, then repeats the last one — mirroring
    a real job that stays in its final state."""

    def __init__(self, jobs=None, ledger_path=None, cap_ops=60,
                 upload_error=None, export_bytes=None):
        from app.budget import BudgetGuard
        self.budget = BudgetGuard(cap_ops=cap_ops, ledger_path=ledger_path)
        self.jobs = list(jobs or [])
        self.last_job = None
        self.upload_error = upload_error
        self.export_bytes = export_bytes if export_bytes is not None else b"FAKE-DOCX"
        self.approved = []

    def upload_base64(self, filename, file_bytes, session_id, return_html=False):
        if self.upload_error:
            from app.superdocs_client import SuperDocsError
            raise SuperDocsError(self.upload_error, status_code=500)
        return {"html": "<p>source</p>", "document_html": "<p>source</p>"}

    def export(self, session_id=None, html=None, fmt="docx", filename=None):
        return self.export_bytes

    def chat_async(self, session_id, message, approval_mode="ask_every_time",
                   model_tier=None, thinking_depth=None):
        from app.budget import BudgetExceeded
        self.budget.guard(1)
        return {"job_id": "job-1"}

    def poll_job(self, job_id, timeout_s=600, interval_s=5.0):
        if self.jobs:
            self.last_job = self.jobs.pop(0)
        return self.last_job

    def approve(self, session_id, job_id, approved=True, changes=None, feedback=None):
        self.approved.append(changes)
        return {"ok": True}


def completed_job(updated_html="<p>edited</p>", usage=None, pending=None, response="ok"):
    return {
        "status": "awaiting_approval" if pending else "completed",
        "metadata": {"pending_changes": pending or []} if pending is not None else {},
        "result": None if pending else {
            "response": response,
            "document_changes": {"updated_html": updated_html},
            "usage": usage or {"was_billable": True, "ops_charged": 1, "monthly_remaining": 500},
        },
    }


def awaiting_job(pending):
    return {"status": "awaiting_approval", "metadata": {"pending_changes": pending}, "result": None}