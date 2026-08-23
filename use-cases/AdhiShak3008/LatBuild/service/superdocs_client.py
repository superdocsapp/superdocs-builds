"""
superdocs_client.py
Thin wrapper around the SuperDocs REST API.

Handles:
- Document upload (multipart)
- Async chat job submission with approval_mode='ask_every_time'
- Job polling
- Proposed-change retrieval (including the required double-parse of content)
- Per-change approval/denial
- Continue-prompt handling
- DOCX export

The API key is read from the SUPERDOCS_API_KEY environment variable and
never exposed to the browser or committed to the repository.
"""

import json
import os
import time
import requests

BASE_URL = "https://api.superdocs.app"
POLL_INTERVAL_SECONDS = 3
MAX_POLL_ATTEMPTS = 600  # 30 minutes at 3s intervals


class SuperDocsError(Exception):
    """Raised for non-retryable SuperDocs API errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SuperDocsRateLimitError(SuperDocsError):
    """Raised when the monthly quota is exhausted (429)."""
    pass


class SuperDocsTimeoutError(SuperDocsError):
    """Raised when a job exceeds the polling budget."""
    pass


def _get_api_key():
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if not key:
        raise SuperDocsError("SUPERDOCS_API_KEY environment variable is not set.")
    return key


def _auth_headers():
    return {
        "Authorization": f"Bearer {_get_api_key()}",
    }


def _json_headers():
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }


def _raise_for_status(response):
    """Raise a typed error for non-2xx responses."""
    if response.status_code == 429:
        raise SuperDocsRateLimitError(
            "Monthly operation quota exhausted or rate limit hit.",
            status_code=429,
        )
    if response.status_code == 401:
        raise SuperDocsError("Invalid or missing API key.", status_code=401)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise SuperDocsError(
            f"SuperDocs API error {response.status_code}: {detail}",
            status_code=response.status_code,
        )


def upload_document(file_bytes, filename, session_id):
    """
    Upload a DOCX (or other supported format) and load it as the active
    editable document in the given session.

    Returns:
        dict with keys: html, chunks_count, version_id, filename
    """
    url = f"{BASE_URL}/v1/documents/upload"
    files = {"file": (filename, file_bytes, "application/octet-stream")}
    data = {"session_id": session_id}
    for attempt in range(3):
        try:
            response = requests.post(url, headers=_auth_headers(), files=files, data=data, timeout=60)
            _raise_for_status(response)
            return response.json()
        except requests.exceptions.ConnectionError as e:
            if attempt == 2:
                raise SuperDocsError(f"Upload failed after 3 attempts: {e}")
            time.sleep(2 ** attempt)
            files = {"file": (filename, file_bytes, "application/octet-stream")}  # reset file


def start_transformation(session_id, document_html, instruction):
    """
    Start an async transformation job with approval_mode='ask_every_time'.

    The document_html passed here is always the original manuscript HTML —
    never a previously transformed version.

    Returns:
        job_id (str)
    """
    url = f"{BASE_URL}/v1/chat/async"
    payload = {
        "message": instruction,
        "session_id": session_id,
        "document_html": document_html,
        "approval_mode": "ask_every_time",
        "model_tier": "pro",
    }
    for attempt in range(3):
        try:
            response = requests.post(url, headers=_json_headers(), json=payload, timeout=60)
            _raise_for_status(response)
            return response.json()["job_id"]
        except requests.exceptions.ConnectionError as e:
            if attempt == 2:
                raise SuperDocsError(f"Transform failed after 3 attempts: {e}")
            time.sleep(2 ** attempt)


def poll_job(job_id):
    """
    Poll a job once and return its current state.

    Returns a dict with at minimum:
        status: "pending" | "in_progress" | "awaiting_approval" |
                "completed" | "failed" | "cancelled"
        pending_changes: list (when status == "awaiting_approval")
        result: dict (when status == "completed")
        error: str (when status == "failed")
    """
    url = f"{BASE_URL}/v1/jobs/{job_id}"
    response = requests.get(url, headers=_auth_headers())
    _raise_for_status(response)
    data = response.json()

    pending_changes = []
    if data.get("status") == "awaiting_approval":
        raw = (data.get("metadata") or {}).get("pending_changes", [])
        pending_changes = _parse_pending_changes(raw)

    return {
        "status": data.get("status"),
        "pending_changes": pending_changes,
        "result": data.get("result"),
        "error": data.get("error"),
        "intermediate_responses": (data.get("metadata") or {}).get(
            "intermediate_responses", []
        ),
    }


def _parse_pending_changes(raw_changes):
    """
    SuperDocs may JSON-encode the content field of each proposed change as a
    string. This function handles both the double-encoded and already-decoded
    shapes so callers always receive a consistent list of change dicts.

    Each returned change dict contains at minimum:
        change_id, chunk_id, operation, old_html, new_html, ai_explanation
    """
    parsed = []
    for item in raw_changes:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except (json.JSONDecodeError, TypeError):
                pass
        # The content field itself may be a JSON-encoded string
        content = item.get("content", item)
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                content = item
        # Normalise: if content is a batch wrapper, unwrap it
        if isinstance(content, dict) and "changes" in content:
            for change in content["changes"]:
                parsed.append(_normalise_change(change))
        else:
            parsed.append(_normalise_change(content if isinstance(content, dict) else item))
    return parsed


def _normalise_change(change):
    """Return a change dict with consistent keys regardless of API shape."""
    return {
        "change_id": change.get("change_id", change.get("id", "")),
        "chunk_id": change.get("chunk_id", ""),
        "operation": change.get("operation", "update"),
        "old_html": change.get("old_html", change.get("before", "")),
        "new_html": change.get("new_html", change.get("after", "")),
        "ai_explanation": change.get("ai_explanation", change.get("explanation", "")),
    }


def approve_changes(session_id, job_id, decisions):
    """
    Submit per-change approval decisions.

    decisions: list of dicts with keys:
        change_id (str), approved (bool), feedback (str, optional)

    Returns the API response dict.
    """
    url = f"{BASE_URL}/v1/chat/{session_id}/approve"
    payload = {
        "job_id": job_id,
        "approved": all(d["approved"] for d in decisions),
        "changes": [
            {
                "change_id": d["change_id"],
                "approved": d["approved"],
                **({"feedback": d["feedback"]} if d.get("feedback") else {}),
            }
            for d in decisions
        ],
    }
    response = requests.post(url, headers=_json_headers(), json=payload)
    _raise_for_status(response)
    return response.json()


def continue_job(session_id, job_id, do_continue=True):
    """
    Resume or stop a job that paused with a continue_prompt.
    """
    url = f"{BASE_URL}/v1/chat/{session_id}/continue"
    payload = {"job_id": job_id, "continue": do_continue}
    response = requests.post(url, headers=_json_headers(), json=payload)
    _raise_for_status(response)
    return response.json()


def wait_for_completion(job_id, on_progress=None):
    """
    Poll until the job reaches a terminal state (completed/failed/cancelled).
    Handles awaiting_approval by returning early so the caller can surface
    the proposed changes to the user.

    on_progress: optional callable(status_str) for progress updates

    Returns the poll_job() dict at the point of return.
    """
    for _ in range(MAX_POLL_ATTEMPTS):
        state = poll_job(job_id)
        status = state["status"]

        if on_progress:
            on_progress(status)

        if status in ("completed", "failed", "cancelled"):
            return state
        if status == "awaiting_approval":
            return state  # caller must handle approval then re-poll

        time.sleep(POLL_INTERVAL_SECONDS)

    raise SuperDocsTimeoutError(
        f"Job {job_id} did not complete within the polling budget."
    )


def export_document(session_id, filename="manuscript"):
    """
    Export the session's current document as DOCX.

    Returns raw bytes of the .docx file.
    """
    url = f"{BASE_URL}/v1/documents/export"
    payload = {
        "session_id": session_id,
        "format": "docx",
        "options": {"filename": filename},
    }
    response = requests.post(url, headers=_json_headers(), json=payload)
    _raise_for_status(response)
    return response.content


def get_final_html(job_result):
    """
    Extract the final updated HTML from a completed job result dict.
    Returns None if the job did not produce document changes.
    """
    if not job_result:
        return None
    doc_changes = job_result.get("document_changes") or {}
    return doc_changes.get("updated_html")
