"""Minimal SuperDocs API client for VoiceRedline (stdlib only).

Adapted from my Task 2a Writer-sidebar client (same proven tail:
async chat with human-in-the-loop approval -> poll -> pending changes ->
explicit per-change decisions -> export). Restructured so one uploaded
document (one session) can take several voice-driven edit rounds.

API key: SUPERDOCS_API_KEY env var, else ~/.superdocs/agent_credentials.json.
Never logged, never stored by this module, never sent to the browser.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.superdocs.app"
POLL_SECONDS = 4
POLL_LIMIT = 150  # x4s = 10 min

BLANK_HTML = "<html><body></body></html>"


class SuperDocsError(Exception):
    pass


def api_key():
    key = os.environ.get("SUPERDOCS_API_KEY")
    if key:
        return key
    cred = Path.home() / ".superdocs" / "agent_credentials.json"
    if cred.exists():
        return json.loads(cred.read_text(encoding="utf-8-sig"))["api_key"]
    raise SuperDocsError(
        "No API key: set SUPERDOCS_API_KEY or create ~/.superdocs/agent_credentials.json")


def _call(method, path, body=None, retries=1, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + api_key())
    if data:
        req.add_header("Content-Type", "application/json")
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if "json" in r.headers.get("Content-Type", ""):
                    return json.loads(raw)
                return raw
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                last = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
            else:
                last = str(exc)
            if attempt < retries:
                time.sleep(4)  # first call in a fresh session may flake while warming up
    raise SuperDocsError(f"{method} {path} failed: {last}")


def _poll(job_id, until_states, progress):
    for i in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        job = _call("GET", f"/v1/jobs/{job_id}")
        state = job.get("status")
        if i % 3 == 2:
            progress(f"Working... ({state}, {i * POLL_SECONDS}s)")
        if state in until_states or state in ("failed", "cancelled"):
            return state, job
    raise SuperDocsError("Timed out waiting for SuperDocs job")


def upload_doc(file_bytes, filename, progress=lambda m: None):
    """Upload a document once; every later edit reuses its session.
    Pass file_bytes=None to start a blank drafting session."""
    session = "voxrl-" + time.strftime("%Y%m%d-%H%M%S")
    if file_bytes is None:
        file_bytes, filename = BLANK_HTML.encode(), "draft.html"
    progress("Uploading document...")
    _call("POST", "/v1/documents/upload-base64", {
        "filename": filename,
        "file_base64": base64.b64encode(file_bytes).decode(),
        "session_id": session,
    })
    return session


def open_edit(session, instruction, progress=lambda m: None):
    """One voice instruction -> async chat -> pending changes for review.
    Returns dict: session, job_id, pending, state, summary, draft_html, response."""
    progress("Requesting edit...")
    job = _call("POST", "/v1/chat/async", {
        "session_id": session,
        "message": instruction + "\n\nApply targeted edits to this document; change "
                                 "only what the instruction requires; do not add "
                                 "commentary or metadata.",
        "approval_mode": "ask_every_time",
    })
    state, job_data = _poll(job["job_id"], ("awaiting_approval", "completed"), progress)
    if state == "failed":
        raise SuperDocsError("SuperDocs reported the edit failed")
    pending = (job_data.get("metadata") or {}).get("pending_changes") or []
    parts = [c["ai_explanation"] for c in pending if c.get("ai_explanation")]
    summary = " | ".join(parts) if parts else f"{len(pending)} proposed change(s)"
    # Drafting instructions ("create X") bypass the approval gate entirely: the
    # job completes with NO pending changes and the created content rides
    # result.document_changes (observed 2026-08-07, logged as BUGS B6). Expose
    # it so the UI can gate the draft locally instead of dropping it.
    result = job_data.get("result") or {}
    draft_html = ""
    response_text = ""
    if isinstance(result, dict):
        draft_html = (result.get("document_changes") or {}).get("updated_html") or ""
        response_text = result.get("response") or ""
    return {"session": session, "job_id": job["job_id"], "pending": pending,
            "state": state, "summary": summary,
            "draft_html": draft_html, "response": response_text}


def decide(edit, decisions, progress=lambda m: None):
    """Send per-change decisions: [{change_id, approved, feedback?}, ...].
    Mixed approve/reject batches are allowed; the per-change array is the
    truth. Returns the final job state ('completed' when anything applied)."""
    decisions = [dict(d) for d in decisions]
    for d in decisions:
        if not d.get("approved") and not d.get("feedback"):
            d["feedback"] = "Rejected by voice in VoiceRedline"
    approve_any = any(d.get("approved") for d in decisions)
    if decisions:
        progress("Sending decisions...")
        # A bare {job_id, approved} is a silent no-op in the API - the explicit
        # changes array is required for the job to proceed (BUGS B1).
        resp = _call("POST", f"/v1/chat/{edit['session']}/approve",
                     {"job_id": edit["job_id"], "approved": approve_any,
                      "changes": decisions})
        if approve_any and not resp.get("batch_complete"):
            raise SuperDocsError(f"Approval incomplete: {resp}")
    if not approve_any:
        return "rejected"
    state, _ = _poll(edit["job_id"], ("completed",), progress)
    if state != "completed":
        raise SuperDocsError(f"Job ended in state {state}")
    return state


def export_doc(session, fmt="docx", progress=lambda m: None):
    """Export the session's current document. Returns raw bytes."""
    progress(f"Exporting {fmt}...")
    blob = _call("POST", "/v1/documents/export",
                 {"session_id": session, "format": fmt})
    if isinstance(blob, dict):
        blob = base64.b64decode(blob.get("file_base64") or blob.get("content_base64"))
    return blob
