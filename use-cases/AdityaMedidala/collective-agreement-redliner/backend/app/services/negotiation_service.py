"""
Starts a negotiation: loads the CBA draft as the editable document, both
position papers as read-only attachments, all into one SuperDocs session.
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.models import Negotiation
from app.services.polling import poll_job
from app.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)

# attachment uploads are async; these are the only statuses that stop polling
TERMINAL_JOB_STATUSES = {"completed", "failed"}


def _is_attachment_job_terminal(job: dict) -> bool:
    return job.get("status") in TERMINAL_JOB_STATUSES


def _extract_attachment_id(job: dict) -> str | None:
    # API reference doesn't nail down the completed-attachment-job result
    # shape — assumption logged in PROGRESS.md: try result.attachment_id,
    # then result.id, then a top-level attachment_id.
    result = job.get("result") or {}
    return result.get("attachment_id") or result.get("id") or job.get("attachment_id")


def start_negotiation(
    db: Session,
    client: SuperDocsClient,
    name: str,
    cba_bytes: bytes,
    union_bytes: bytes,
    employer_bytes: bytes,
) -> Negotiation:
    session_id = str(uuid.uuid4())

    # filenames must match actual content: a .docx name on plain-text bytes
    # 400s live (confirmed 2026-08-12) — the seed corpus is genuinely .txt
    doc_response = client.upload_document(session_id, "cba-draft.txt", cba_bytes)
    cba_document_id = doc_response.get("document_id") or doc_response.get("id") or session_id

    union_upload = client.upload_attachment(session_id, "union-position.txt", union_bytes)
    union_job = poll_job(client, union_upload["job_id"], _is_attachment_job_terminal)
    if union_job.get("status") != "completed":
        logger.warning("union attachment job %s did not complete: %s", union_upload["job_id"], union_job)
    union_attachment_id = _extract_attachment_id(union_job)

    employer_upload = client.upload_attachment(session_id, "employer-position.txt", employer_bytes)
    employer_job = poll_job(client, employer_upload["job_id"], _is_attachment_job_terminal)
    if employer_job.get("status") != "completed":
        logger.warning("employer attachment job %s did not complete: %s", employer_upload["job_id"], employer_job)
    employer_attachment_id = _extract_attachment_id(employer_job)

    negotiation = Negotiation(
        name=name,
        superdocs_session_id=session_id,
        cba_document_id=cba_document_id,
        union_attachment_id=union_attachment_id,
        employer_attachment_id=employer_attachment_id,
    )
    db.add(negotiation)
    db.commit()
    db.refresh(negotiation)
    return negotiation
