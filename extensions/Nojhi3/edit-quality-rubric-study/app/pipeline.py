"""Edit pipeline: for each case, upload -> chat(async, ask_every_time) -> approve -> export.

Artifacts per case are saved under data/edits/<case_id>/ so judging is fully
reproducible from local files and the four-call contract is visible in the
operation ledger.
"""

import json
import re
import time
from pathlib import Path

from . import config
from .budget import BudgetGuard, BudgetExceeded
from .superdocs_client import SuperDocsClient, SuperDocsError

CASE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def load_cases(limit: int = None) -> list[dict]:
    cases = json.loads(config.INSTRUCTIONS_PATH.read_text(encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]
    for case in cases:
        if not CASE_ID_RE.match(case["case_id"]):
            raise ValueError(f"bad case_id {case['case_id']!r} (must be safe for session ids)")
    return cases


class EditRunner:
    def __init__(self, client: SuperDocsClient = None, poll_timeout_s: int = 600):
        self.client = client or SuperDocsClient()
        self.poll_timeout_s = poll_timeout_s

    def run_case(self, case: dict) -> dict:
        case_id = case["case_id"]
        out_dir = config.EDITS_DIR / case_id
        out_dir.mkdir(parents=True, exist_ok=True)

        doc_bytes = (config.CORPUS_DIR / case["doc_file"]).read_bytes()
        session_id = f"eqr_{case_id}_{int(time.time())}"

        record = {
            "case_id": case_id,
            "doc_id": case["doc_id"],
            "difficulty": case["difficulty"],
            "instruction": case["instruction"],
            "session_id": session_id,
            "steps": {},
            "status": "running",
        }

        # 1) upload
        upload = self.client.upload_base64(case["doc_file"], doc_bytes, session_id, return_html=True)
        record["steps"]["upload"] = {"ok": True}
        (out_dir / "upload.json").write_text(json.dumps(upload, indent=2), encoding="utf-8")
        source_html = upload.get("html") or upload.get("document_html")
        if source_html:
            (out_dir / "before.html").write_text(source_html, encoding="utf-8")
        try:
            before_md = self.client.export(session_id=session_id, fmt="markdown")
            (out_dir / "before.md").write_bytes(before_md)
            record["steps"]["export_before_md"] = {"ok": True, "bytes": len(before_md)}
        except SuperDocsError:
            pass

        # 2) chat (async, ask_every_time -> pauses for approval)
        chat = self.client.chat_async(
            session_id, case["instruction"], approval_mode="ask_every_time"
        )
        job_id = chat.get("job_id")
        record["steps"]["chat"] = {"job_id": job_id, "usage": chat.get("usage")}
        (out_dir / "chat_start.json").write_text(json.dumps(chat, indent=2), encoding="utf-8")

        # 3) poll to awaiting_approval, then approve every proposed change.
        #    The AI may revise and pause again after an approval batch, so loop
        #    (bounded) until the job completes.
        job = self.client.poll_job(job_id, timeout_s=self.poll_timeout_s)
        record["steps"]["pre_approval_status"] = job.get("status")
        pending = (job.get("metadata") or {}).get("pending_changes") or []
        record["pending_change_count"] = len(pending)
        (out_dir / "pending_changes.json").write_text(
            json.dumps(pending, indent=2), encoding="utf-8"
        )

        approve_rounds = 0
        while job.get("status") == "awaiting_approval" and pending and approve_rounds < 5:
            decisions = [{"change_id": c["change_id"], "approved": True} for c in pending]
            approve_resp = self.client.approve(
                session_id, job_id, approved=True, changes=decisions
            )
            approve_rounds += 1
            (out_dir / f"approve_{approve_rounds}.json").write_text(
                json.dumps(approve_resp, indent=2), encoding="utf-8"
            )
            job = self.client.poll_job(job_id, timeout_s=self.poll_timeout_s)
            pending = (job.get("metadata") or {}).get("pending_changes") or []

        record["steps"]["approve"] = {
            "ok": job.get("status") == "completed",
            "rounds": approve_rounds,
            "final_status": job.get("status"),
        }
        if job.get("status") == "completed" and approve_rounds == 0:
            record["steps"]["approve"]["note"] = "no pending changes; job completed directly"

        if job.get("status") != "completed":
            record["status"] = "failed"
            record["error"] = job.get("error")
            record["final_job"] = job
            (out_dir / "job_final.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
            return record

        # 4) poll to completion
        job = self.client.poll_job(job_id, timeout_s=self.poll_timeout_s)
        record["final_status"] = job.get("status")
        (out_dir / "job_final.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        if job.get("status") != "completed":
            record["status"] = "failed"
            record["error"] = job.get("error")
            return record

        result = job.get("result") or {}
        (out_dir / "chat_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        self.client.budget.record(
            {"usage": result.get("usage")},
            endpoint="/v1/chat/async (job result)",
            tag=f"edit:{case_id}",
        )
        updated_html = (result.get("document_changes") or {}).get("updated_html")
        if updated_html:
            (out_dir / "after.html").write_text(updated_html, encoding="utf-8")
        record["steps"]["chat_result"] = {
            "response": (result.get("response") or "")[:2000],
            "has_updated_html": bool(updated_html),
        }

        # 5) export the finished file (docx deliverable + markdown for judging)
        try:
            docx_bytes = self.client.export(session_id=session_id, fmt="docx")
            (out_dir / "after.docx").write_bytes(docx_bytes)
            record["steps"]["export_docx"] = {"ok": True, "bytes": len(docx_bytes)}
        except SuperDocsError as exc:
            record["steps"]["export_docx"] = {"ok": False, "error": str(exc)}

        try:
            md_bytes = self.client.export(session_id=session_id, fmt="markdown")
            (out_dir / "after.md").write_bytes(md_bytes)
            record["steps"]["export_md"] = {"ok": True, "bytes": len(md_bytes)}
        except SuperDocsError as exc:
            record["steps"]["export_md"] = {"ok": False, "error": str(exc)}

        record["status"] = "completed"
        (out_dir / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def run_all(self, case_ids: list[str]) -> dict:
        summary = {"results": [], "failed": []}
        for case in load_cases():
            if case_ids and case["case_id"] not in case_ids:
                continue
            try:
                rec = self.run_case(case)
            except BudgetExceeded:
                summary["failed"].append({"case_id": case["case_id"], "error": "budget cap exceeded"})
                break
            except SuperDocsError as exc:
                rec = {
                    "case_id": case["case_id"],
                    "status": "failed",
                    "error": f"{exc}",
                }
                (config.EDITS_DIR / case["case_id"] / "error.json").write_text(
                    json.dumps(rec, indent=2), encoding="utf-8"
                )
            summary["results"].append(rec)
            if rec["status"] != "completed":
                summary["failed"].append(rec)
        return summary