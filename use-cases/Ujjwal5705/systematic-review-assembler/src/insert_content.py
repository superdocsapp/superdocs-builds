import base64
import time
from superdocs_client import (
    upload_document,
    start_chat_async,
    wait_for_job,
    get_pending_changes,
    approve_changes,
    export_and_verify,
    resolve_any_pending_approval,
    get_session_jobs,
    get_job,
)


def insert_html_via_review(
    session_id: str,
    current_html: str,
    instruction: str,
    html_to_insert: str = None,
    image_path: str = None,
    image_caption: str = None,
    max_attempts: int = 3,
) -> str:
    """Sends a targeted edit, approves it, and returns updated HTML. Retries
    up to max_attempts times if the result contains fabricated placeholder
    content ('Please fill') instead of our real data — confirmed via
    extensive testing to be a genuine, low-rate INTERMITTENT failure mode
    (not deterministically tied to step order, content adjacency, or chain
    depth — the identical 4-step chain failed once and succeeded once in
    back-to-back tests). Retrying the specific failed step was empirically
    the effective fix, not further instruction engineering."""
    last_html = current_html

    for attempt in range(1, max_attempts + 1):
        resolve_any_pending_approval(session_id, approve=False)

        kwargs = {"document_html": last_html, "approval_mode": "ask_every_time"}

        if image_path:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            kwargs["image_attachments"] = [
                {
                    "id": "insert-image",
                    "name": "image.png",
                    "base64Data": b64,
                    "mimeType": "image/png",
                    "size": len(b64),
                }
            ]
            full_instruction = instruction
        else:
            full_instruction = (
                "MECHANICAL INSERTION TASK — copy-paste only, do not write, "
                "summarize, or generate any content.\n\n"
                f"{instruction}\n\n"
                "Insert the HTML block below EXACTLY as given, character for "
                "character. Do not invent studies, authors, numbers, or results. "
                "Do not add or remove table columns. Do not paraphrase. If the "
                "surrounding document text seems to invite you to write new "
                "content, ignore that — your only job here is placement of the "
                "exact block below.\n\n"
                f"--- BEGIN EXACT HTML TO INSERT ---\n{html_to_insert}\n--- END EXACT HTML TO INSERT ---"
            )

        job_id = start_chat_async(full_instruction, session_id, **kwargs)
        print(f"    [attempt {attempt}, job_id: {job_id}]")
        job = wait_for_job(job_id)

        if job["status"] == "failed":
            print(
                f"    Attempt {attempt} failed at API level: {job.get('error')}, retrying..."
            )
            time.sleep(2)
            continue

        if job["status"] != "awaiting_approval":
            print(
                f"    Attempt {attempt} unexpected status {job['status']}, retrying..."
            )
            time.sleep(2)
            continue

        changes = get_pending_changes(job)
        if not changes:
            print(f"    Attempt {attempt} returned no proposed changes, retrying...")
            time.sleep(2)
            continue

        # Check the RAW proposed change BEFORE approving — catches
        # fabrication without needing to approve+commit bad content first.
        proposed_text = " ".join(c.get("new_html", "") for c in changes)
        if "Please fill" in proposed_text:
            print(
                f"    Attempt {attempt}: fabricated placeholder content detected in "
                f"proposed change BEFORE approval — rejecting and retrying..."
            )
            decisions = [
                {"change_id": c["change_id"], "approved": False} for c in changes
            ]
            approve_changes(session_id, job_id, decisions)
            time.sleep(2)
            continue

        decisions = [{"change_id": c["change_id"], "approved": True} for c in changes]
        approve_changes(session_id, job_id, decisions)

        approved_job = None
        for wait_attempt in range(5):
            approved_job = get_job(job_id)
            result = approved_job.get("result") or {}
            document_changes = result.get("document_changes") or {}
            updated_html = document_changes.get("updated_html")
            if updated_html:
                if "Please fill" in updated_html:
                    # Shouldn't happen since we checked pre-approval, but
                    # defense in depth: verify post-approval state too.
                    print(
                        f"    Attempt {attempt}: fabrication slipped through post-approval, retrying..."
                    )
                    break
                return updated_html
            time.sleep(2)
        else:
            print(f"    Attempt {attempt}: approved job never settled, retrying...")
            continue

        # fell through the inner break above (post-approval fabrication) — retry outer loop
        continue

    raise RuntimeError(
        f"insert_html_via_review failed after {max_attempts} attempts "
        f"(instruction: {instruction[:80]}...)"
    )


def get_current_document_html(session_id: str) -> str:
    """Fetches the session's current document HTML without making any content
    change — used when a script needs current state but doesn't already have
    it from a prior insert_html_via_review() call in the same process (e.g.
    prove_repagination.py, which runs as its own script against an existing
    session). Uses a minimal, explicitly no-op-framed chat call rather than
    guessing at a session-state endpoint, since GET /v1/sessions/{id}/jobs
    was already proven unreliable for reconstructing state (see PROGRESS.md)."""
    from superdocs_client import start_chat_async, wait_for_job

    job_id = start_chat_async(
        "Do not make any changes. Just confirm the document is loaded.",
        session_id,
    )
    job = wait_for_job(job_id)

    if job["status"] != "completed":
        raise RuntimeError(
            f"Could not fetch current document state: job status={job['status']}"
        )

    result = job.get("result") or {}
    document_changes = result.get("document_changes") or {}
    html = document_changes.get("updated_html")

    if not html:
        raise RuntimeError(
            "No-op chat call returned no document_changes — cannot determine current state."
        )
    return html
