from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from superdocs import SuperDocs, SuperDocsError, parse_pending_changes


def start_job(
    *,
    html: str,
    message: str,
    template_name: str,
    template_bytes: bytes,
    prefix: str,
    extra: dict[str, Any],
    review_mode: bool,
    force_offline: bool,
    jobs: dict,
) -> dict:
    if force_offline or not SuperDocs().enabled():
        local_id = f"local-{uuid.uuid4()}"
        jobs[local_id] = {
            "mode": "offline",
            "status": "completed",
            "html": html,
            "session_id": local_id,
            **extra,
        }
        return out(jobs, local_id)
    sd = SuperDocs()
    session_id = f"{prefix}-{uuid.uuid4()}"
    try:
        try:
            sd.upload_template(template_name, template_bytes, "text/html")
        except SuperDocsError:
            pass
        job_id = sd.chat_async(
            session_id,
            message,
            document_html=html,
            approval_mode="ask_every_time" if review_mode else "approve_all",
        )
        polled = sd.poll_job(job_id)
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
    jobs[job_id] = {
        "mode": "live",
        "session_id": session_id,
        "job": polled,
        "baseline_html": html,
        "html": html if polled.get("status") == "awaiting_approval" else (_html(polled) or html),
        **extra,
    }
    return out(jobs, job_id)


def refresh(jobs: dict, job_id: str) -> dict:
    rec = jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    if rec["mode"] == "live":
        rec["job"] = SuperDocs().get_job(job_id)
        applied = _html(rec["job"]) or rec.get("baseline_html") or rec.get("html")
        if rec["job"].get("status") == "awaiting_approval":
            rec["html"] = rec.get("baseline_html") or rec.get("html")
        else:
            rec["html"] = applied
    return out(jobs, job_id)


def review(jobs: dict, job_id: str, decisions: dict[str, bool]) -> dict:
    rec = jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    if rec["mode"] != "live":
        return out(jobs, job_id)
    sd = SuperDocs()
    job = rec["job"]
    kind = (job.get("metadata") or {}).get("awaiting_kind")
    try:
        if kind == "continue_prompt":
            sd.continue_job(rec["session_id"], job_id, True)
        else:
            sd.approve(rec["session_id"], job_id, decisions)
        rec["job"] = sd.poll_job(job_id)
        applied = _html(rec["job"]) or rec.get("baseline_html") or rec.get("html")
        if rec["job"].get("status") == "awaiting_approval":
            rec["html"] = rec.get("baseline_html") or rec.get("html")
        else:
            rec["html"] = applied
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
    return out(jobs, job_id)


def export_job(jobs: dict, job_id: str, filename: str, dest, fmt: str = "docx"):
    rec = jobs.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    html = rec.get("html") or ""
    sd = SuperDocs()
    if rec["mode"] == "live" and sd.enabled():
        data = sd.export(session_id=rec["session_id"], html=html, fmt=fmt, filename=filename)
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={filename}.{fmt}"},
        )
    dest.mkdir(exist_ok=True)
    outp = dest / f"{filename}.html"
    outp.write_text(html, encoding="utf-8")
    return FileResponse(outp, filename=f"{filename}.html")


def out(jobs: dict, job_id: str) -> dict:
    rec = jobs[job_id]
    if rec["mode"] == "offline":
        return {"id": job_id, "status": rec.get("status", "completed"), "offline": True, "html": rec.get("html"), "changes": [], **{k: rec[k] for k in rec if k not in ("mode", "job", "session_id", "html", "status")}}
    job = rec["job"]
    extra = {k: rec[k] for k in rec if k not in ("mode", "job", "session_id", "html")}
    return {
        "id": job_id,
        "status": job.get("status"),
        "offline": False,
        "html": rec.get("html"),
        "changes": parse_pending_changes(job),
        "awaiting_kind": (job.get("metadata") or {}).get("awaiting_kind"),
        "error": job.get("error"),
        **extra,
    }


def _html(job: dict) -> str:
    result = job.get("result") or {}
    return (result.get("document_changes") or {}).get("updated_html") or ""
