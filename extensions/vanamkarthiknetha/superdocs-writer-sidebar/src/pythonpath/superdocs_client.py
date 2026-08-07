"""Minimal SuperDocs API client for the Writer sidebar (stdlib only).

Flow: upload the selected passage as a small HTML doc -> async chat with
human-in-the-loop approval -> caller shows the proposal -> approve/reject ->
on approval, poll to completion and export as plain text for write-back.

API key: SUPERDOCS_API_KEY env var, else ~/.superdocs/agent_credentials.json.
Never logged, never stored by this module.
"""
import base64
import html
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.superdocs.app"
POLL_SECONDS = 4
POLL_LIMIT = 150  # x4s = 10 min


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


def _passage_to_html(text):
    paragraphs = [f"<p>{html.escape(p)}</p>" for p in text.split("\n") if p.strip()]
    return "<html><body>" + "".join(paragraphs or ["<p></p>"]) + "</body></html>"


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


def _open_edit(session, message, progress):
    """Shared tail: async chat -> poll -> pending changes. Returns edit dict."""
    progress("Requesting edit...")
    job = _call("POST", "/v1/chat/async", {
        "session_id": session,
        "message": message,
        "approval_mode": "ask_every_time",
    })
    state, job_data = _poll(job["job_id"], ("awaiting_approval", "completed"), progress)
    if state == "failed":
        raise SuperDocsError("SuperDocs reported the edit failed")
    pending = (job_data.get("metadata") or {}).get("pending_changes") or []
    parts = [c["ai_explanation"] for c in pending if c.get("ai_explanation")]
    summary = " | ".join(parts) if parts else f"{len(pending)} proposed change(s)"
    return {"session": session, "job_id": job["job_id"], "pending": pending,
            "state": state, "summary": summary}


def request_edit(passage_text, instruction, progress=lambda m: None):
    """Selection mode. Returns dict: session, job_id, pending, state, summary."""
    session = "sdext-" + time.strftime("%Y%m%d-%H%M%S")
    progress("Uploading passage...")
    _call("POST", "/v1/documents/upload-base64", {
        "filename": "passage.html",
        "file_base64": base64.b64encode(_passage_to_html(passage_text).encode()).decode(),
        "session_id": session,
    })
    return _open_edit(
        session,
        instruction + "\n\nEdit only this passage; do not add commentary or metadata.",
        progress)


def request_doc_edit(docx_bytes, instruction, progress=lambda m: None):
    """Whole-document mode: upload the exported .docx, then one chat request.
    Same return shape as request_edit; pending[].old_html anchors write-back."""
    session = "sdext-doc-" + time.strftime("%Y%m%d-%H%M%S")
    progress("Uploading document...")
    _call("POST", "/v1/documents/upload-base64", {
        "filename": "document.docx",
        "file_base64": base64.b64encode(docx_bytes).decode(),
        "session_id": session,
    })
    return _open_edit(
        session,
        instruction + "\n\nApply targeted edits to this document; change only what "
                      "the instruction requires; do not add commentary or metadata.",
        progress)


def finalize(edit, approve, progress=lambda m: None, want_text=True):
    """Approve or reject all pending changes. On approve, returns the final
    passage text (plain-text export), or None when want_text=False (whole-doc
    mode writes back from the changes themselves); on reject, returns None."""
    decisions = [{"change_id": c["change_id"], "approved": bool(approve)}
                 for c in edit["pending"]]
    if not approve:
        for d in decisions:
            d["feedback"] = "Rejected by user in the sidebar"
    if decisions:
        progress("Sending decision...")
        # A bare {job_id, approved} is a silent no-op in the API - the explicit
        # changes array is required for the job to proceed.
        resp = _call("POST", f"/v1/chat/{edit['session']}/approve",
                     {"job_id": edit["job_id"], "approved": bool(approve),
                      "changes": decisions})
        if approve and not resp.get("batch_complete"):
            raise SuperDocsError(f"Approval incomplete: {resp}")
    if not approve:
        return None
    state, _ = _poll(edit["job_id"], ("completed",), progress)
    if state != "completed":
        raise SuperDocsError(f"Job ended in state {state}")
    if not want_text:
        return None
    progress("Fetching result...")
    blob = _call("POST", "/v1/documents/export",
                 {"session_id": edit["session"], "format": "txt"})
    if isinstance(blob, dict):
        blob = base64.b64decode(blob.get("file_base64") or blob.get("content_base64"))
    return blob.decode("utf-8-sig", errors="replace").strip("\n")
