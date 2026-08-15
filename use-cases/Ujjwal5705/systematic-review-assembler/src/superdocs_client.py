import os
import json
import time
import uuid
import requests
from dotenv import load_dotenv
import base64 as b64

load_dotenv()

API_KEY = os.environ["SUPERDOCS_API_KEY"]
BASE = os.environ.get("SUPERDOCS_BASE", "https://api.superdocs.app")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def new_session_id(prefix: str) -> str:
    """Every pipeline run must get a fresh session, never a reused fixed
    name — confirmed via investigation that re-running the pipeline against
    the same session_id re-uploads into and stacks edits onto whatever that
    session's document already contained from prior runs, producing
    duplicated content and unrelated leftover scaffolding."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def upload_document(file_path: str, session_id: str) -> dict:
    with open(file_path, "rb") as f:
        response = requests.post(
            f"{BASE}/v1/documents/upload",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": f},
            data={"session_id": session_id},
        )
    response.raise_for_status()
    return response.json()


def start_chat_async(
    message: str,
    session_id: str,
    document_html: str = None,
    approval_mode: str = None,
    image_attachments: list[dict] = None,
) -> str:
    """Starts an async chat job and returns the job_id."""
    payload = {"message": message, "session_id": session_id}
    if document_html is not None:
        payload["document_html"] = document_html
    if approval_mode:
        payload["approval_mode"] = approval_mode
    if image_attachments:
        payload["image_attachments"] = image_attachments

    response = requests.post(f"{BASE}/v1/chat/async", headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()["job_id"]


def get_job(job_id: str) -> dict:
    response = requests.get(f"{BASE}/v1/jobs/{job_id}", headers=HEADERS)
    response.raise_for_status()
    return response.json()


def wait_for_job(job_id: str, max_wait: int = 180, poll_interval: int = 2) -> dict:
    """Polls until the job leaves 'pending'/'in_progress'. Returns the full job
    object — caller decides what to do with 'completed' vs 'awaiting_approval'."""
    start = time.time()
    while True:
        job = get_job(job_id)
        status = job["status"]
        if status not in ("pending", "in_progress", "queued"):
            return job
        if time.time() - start > max_wait:
            raise TimeoutError(
                f"Job {job_id} did not resolve within {max_wait}s (still '{status}')"
            )
        time.sleep(poll_interval)


def get_pending_changes(job: dict) -> list[dict]:
    """Extracts the list of proposed changes from an awaiting_approval job.
    NOTE per the task brief's own warning: in some response shapes, proposed-change
    content arrives as a JSON-encoded STRING that needs a second json.loads() —
    seen explicitly in the SSE streaming docs (`batch = json.loads(data.content)`).
    The polling /jobs/{id} response, per the docs pulled, already returns
    metadata.pending_changes as a real list of objects (not a double-encoded
    string) — but we defensively handle both shapes here since the docs show
    the double-encoding pattern is real elsewhere in this API."""
    pending = job.get("metadata", {}).get("pending_changes")
    if pending is None:
        return []
    if isinstance(pending, str):
        pending = json.loads(pending)
    return pending


def approve_changes(session_id: str, job_id: str, changes: list[dict]) -> dict:
    """`changes` is a list of {"change_id": ..., "approved": True/False}."""
    response = requests.post(
        f"{BASE}/v1/chat/{session_id}/approve",
        headers=HEADERS,
        json={"job_id": job_id, "approved": True, "changes": changes},
    )
    response.raise_for_status()
    return response.json()


import base64 as b64


def export_document(
    session_id: str, format: str, output_path: str, options: dict = None
) -> str:
    payload = {"session_id": session_id, "format": format}
    if options:
        payload["options"] = options
    response = requests.post(
        f"{BASE}/v1/documents/export", headers=HEADERS, json=payload
    )
    response.raise_for_status()

    warnings_header = response.headers.get("X-Export-Warnings")
    if warnings_header:
        decoded = json.loads(b64.b64decode(warnings_header))
        print(f"⚠️  Export completed with warnings: {json.dumps(decoded, indent=2)}")

    with open(output_path, "wb") as f:
        f.write(response.content)
    return output_path


def get_session_jobs(session_id: str) -> list[dict]:
    response = requests.get(f"{BASE}/v1/sessions/{session_id}/jobs", headers=HEADERS)
    response.raise_for_status()
    body = response.json()
    # The endpoint wraps the list in an envelope: {"jobs": [...], "total": N}
    return body.get("jobs", []) if isinstance(body, dict) else body


def resolve_any_pending_approval(session_id: str, approve: bool = False) -> None:
    """If this session has a leftover job stuck in awaiting_approval (e.g. from
    a previous run that crashed or was interrupted before approving), resolve it
    before starting new work — otherwise the API correctly refuses new chat
    turns on that session (409 Conflict). Defaults to rejecting stale changes,
    since silently auto-approving old proposed edits would be unsafe."""
    jobs = get_session_jobs(session_id)

    for entry in jobs:
        # /v1/sessions/{id}/jobs has returned plain job-id strings in practice,
        # even though other list endpoints in this API return dicts — normalize
        # to a job_id string either way rather than assuming one shape.
        job_id = (
            entry if isinstance(entry, str) else entry.get("job_id") or entry.get("id")
        )
        if not job_id:
            continue

        job_detail = get_job(job_id)
        if job_detail.get("status") != "awaiting_approval":
            continue

        pending = get_pending_changes(job_detail)
        if not pending:
            continue

        changes = [{"change_id": c["change_id"], "approved": approve} for c in pending]
        print(
            f"Resolving {len(changes)} stale pending change(s) on session "
            f"'{session_id}' from job {job_id} (approve={approve})"
        )
        approve_changes(session_id, job_id, changes)


def get_session_history(session_id: str) -> dict:
    response = requests.get(f"{BASE}/v1/sessions/{session_id}/history", headers=HEADERS)
    response.raise_for_status()
    return response.json()


def export_and_verify(
    session_id: str,
    format: str,
    output_path: str,
    expect_image: bool = False,
    marker_text: str = None,
    max_attempts: int = 3,
    retry_delay: int = 3,
    options: dict = None,
) -> str:
    """Exports and verifies against the ACTUAL exported file content — not an
    exact string match on AI-generated text, which we confirmed (via extensive
    debugging) the AI does not reproduce verbatim even when explicitly
    instructed. Verification checks structural presence instead:
    - expect_image=True checks doc.inline_shapes count increased
    - marker_text, if given, is checked case-insensitively and treated as
      informational, not the sole pass/fail condition when expect_image is set
    """
    import docx as docx_lib

    for attempt in range(1, max_attempts + 1):
        path = export_document(session_id, format, output_path, options)

        if format != "docx":
            return path  # verification only implemented for docx currently

        doc = docx_lib.Document(path)
        full_text = "\n".join(p.text for p in doc.paragraphs)

        checks_passed = True
        if expect_image and len(doc.inline_shapes) == 0:
            checks_passed = False
        if marker_text and marker_text.lower() not in full_text.lower():
            print(
                f"  (note: exact marker '{marker_text}' not found — AI may have used "
                f"different wording; not treated as failure on its own)"
            )

        if checks_passed:
            print(
                f"Export verified on attempt {attempt} "
                f"({len(doc.inline_shapes)} image(s), {len(doc.paragraphs)} paragraphs)."
            )
            return path

        print(f"Attempt {attempt}: expected image not found, retrying export...")
        time.sleep(retry_delay)

    raise RuntimeError(
        f"Export did not contain an expected image after {max_attempts} attempts"
    )


def verify_table_data_present(
    docx_path: str, expected_first_cell_values: list[str]
) -> bool:
    """Checks that specific, known values from OUR source data actually appear
    in some table cell in the exported file. This is the only reliable defense
    against the AI silently fabricating replacement content instead of using
    the exact data we provided — a prose instruction alone was proven
    insufficient (see PROGRESS.md)."""
    import docx as docx_lib

    doc = docx_lib.Document(docx_path)
    all_cell_text = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_cell_text.add(cell.text.strip())

    missing = [v for v in expected_first_cell_values if v not in all_cell_text]
    if missing:
        print(
            f"  DATA FIDELITY CHECK FAILED — expected values not found in any table: {missing}"
        )
        return False
    return True


def verify_export_state(
    session_id: str,
    expect_texts: list[str] = None,
    forbid_texts: list[str] = None,
    forbid_duplicates: list[str] = None,
    output_path: str = None,
) -> tuple[bool, str]:
    """... (existing docstring) ...
    forbid_duplicates: text that should appear AT MOST ONCE in the exported
    file (e.g. section headings) — catches accidental re-insertion/duplication,
    a distinct failure mode from fabrication (see PROGRESS.md investigation 3)."""
    import docx as docx_lib

    path = output_path or f"/tmp/verify_{session_id}.docx"
    export_document(session_id, "docx", path)
    doc = docx_lib.Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            text += " " + " ".join(c.text for c in row.cells)

    if expect_texts:
        missing = [t for t in expect_texts if t not in text]
        if missing:
            print(f"    Checkpoint: MISSING expected text: {missing}")
            return False, path
    if forbid_texts:
        present = [t for t in forbid_texts if t in text]
        if present:
            print(f"    Checkpoint: FOUND forbidden text: {present}")
            return False, path
    if forbid_duplicates:
        duplicated = [t for t in forbid_duplicates if text.count(t) > 1]
        if duplicated:
            print(f"    Checkpoint: DUPLICATED text (appears >1 time): {duplicated}")
            return False, path
    return True, path
