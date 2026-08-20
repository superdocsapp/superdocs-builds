"""
Production drafting service: draft -> (require human approval) -> export,
with every step written to the audit trail (GeneratedLetter rows).

Unlike the CLI, letters are NOT auto-exported. A letter must be marked
approved by a staff member before it can be exported/sent. This matters
because these letters carry client-facing status language for immigration
cases -- a human should confirm the checklist and stage summary look
right before anything goes out.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from .cases import case_from_db_record, build_letter_instruction
from .db import CaseRecord, GeneratedLetter
from .letter_validation import validate_letter
from .superdocs_client import SuperDocsClient, SuperDocsError

logger = logging.getLogger("case_status_desk.service")

EXPORT_DIR = Path("out")


class NotFoundError(Exception):
    pass


class ApprovalRequiredError(Exception):
    pass


class SelfApprovalError(Exception):
    """Raised when the same staff member who drafted a letter tries to
    approve it -- separation of duties is enforced here, not just at
    the role level, so an approver can't rubber-stamp their own draft."""
    pass


class ValidationFailedError(Exception):
    """Raised when a drafted letter fails automated validation (a hard
    error, e.g. a dropped checklist item or altered stage language) and
    validation is set to block rather than just warn."""
    pass


def _letter_body_text(result) -> str:
    """Extract the plain-text letter body to validate. Prefer the
    updated document HTML (the actual letter content SuperDocs
    produced) over reply_text (which is just the AI's chat commentary
    about what it did)."""
    html = result.updated_html or ""
    if html:
        return re.sub(r"<[^>]+>", " ", html)
    return result.reply_text or ""


def draft_letter(db: Session, client: SuperDocsClient, case_id: str, requested_by: str,
                  block_on_validation_error: bool = False) -> GeneratedLetter:
    """Draft (but do not export) a status letter. Always recomputed from
    the current DB state of the case -- never reuses a stale checklist.

    After drafting, the letter text is run through automated validation
    (letter_validation.py): every currently-outstanding document and its
    exact form_type must appear, the approved stage language must be
    present verbatim, and language matching legal-advice/outcome-
    prediction patterns is flagged. Validation results are stored on the
    letter (visible to the approver) regardless of outcome. If
    block_on_validation_error is True, a hard validation error raises
    ValidationFailedError instead of creating an awaiting_approval
    letter -- use this when you want bad drafts caught before a human
    ever sees them, rather than surfaced as a warning during review.
    """
    record = db.get(CaseRecord, case_id)
    if record is None:
        raise NotFoundError(f"No case with id {case_id!r}")

    case = case_from_db_record(record)
    instruction = build_letter_instruction(case)
    session_id = f"case-status-{case.case_id}"

    result = client.chat(session_id=session_id, message=instruction)
    logger.info("Drafted letter for case %s (requested_by=%s)", case_id, requested_by)

    validation = validate_letter(case, _letter_body_text(result))
    if validation.errors:
        logger.warning("Letter for case %s failed validation: %s", case_id,
                        [i.code for i in validation.errors])
    if validation.errors and block_on_validation_error:
        raise ValidationFailedError(
            f"Draft for case {case_id} failed validation: "
            + "; ".join(i.message for i in validation.errors)
        )

    outstanding = [
        {"name": d.name, "form_type": d.form_type,
         "due_date": d.due_date.isoformat() if d.due_date else None}
        for d in case.outstanding_documents()
    ]

    letter = GeneratedLetter(
        case_id=case_id,
        session_id=session_id,
        stage_snapshot=case.stage,
        outstanding_snapshot=json.dumps(outstanding),
        status="awaiting_approval",
        requested_by=requested_by,
        validation_passed=validation.passed,
        validation_issues=json.dumps([
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in validation.issues
        ]),
    )
    db.add(letter)
    db.commit()
    db.refresh(letter)
    return letter


def approve_letter(db: Session, letter_id: int, approved_by: str, override_validation: bool = False) -> GeneratedLetter:
    letter = db.get(GeneratedLetter, letter_id)
    if letter is None:
        raise NotFoundError(f"No letter with id {letter_id}")
    if letter.requested_by == approved_by:
        raise SelfApprovalError(
            f"Letter {letter_id} was drafted by {approved_by!r}; a different "
            "staff member must approve it."
        )
    if letter.validation_passed is False and not override_validation:
        raise ValidationFailedError(
            f"Letter {letter_id} failed automated validation "
            "(see validation_issues) and has not been overridden. "
            "Pass override_validation=True after reviewing the issues to approve anyway."
        )
    from datetime import datetime, timezone
    letter.status = "approved"
    letter.approved_by = approved_by
    letter.approved_at = datetime.now(timezone.utc)
    if override_validation and letter.validation_passed is False:
        letter.validation_overridden_by = approved_by
    db.commit()
    db.refresh(letter)
    logger.info("Letter %s for case %s approved by %s", letter_id, letter.case_id, approved_by)
    return letter


def export_letter(db: Session, client: SuperDocsClient, letter_id: int) -> Path:
    """Export the approved letter to .docx. Refuses if not yet approved --
    this is the enforcement point for the human-in-the-loop gate.

    Also links the drafting session's SuperDocs durable File (Files API)
    so the letter has version history and can be reopened/reused in
    SuperDocs directly, not just as a local .docx snapshot.
    """
    letter = db.get(GeneratedLetter, letter_id)
    if letter is None:
        raise NotFoundError(f"No letter with id {letter_id}")
    if letter.status != "approved":
        raise ApprovalRequiredError(
            f"Letter {letter_id} is {letter.status!r}, not 'approved'. "
            "Call approve_letter() first."
        )

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORT_DIR / f"{letter.case_id}-{letter_id}-status-letter.docx"
    file_bytes = client.export(session_id=letter.session_id, fmt="docx",
                                filename=f"{letter.case_id}-status-letter")
    out_path.write_bytes(file_bytes)

    letter.status = "exported"
    letter.export_path = str(out_path)
    _link_superdocs_document(client, letter)
    db.commit()
    logger.info("Exported letter %s for case %s to %s", letter_id, letter.case_id, out_path)
    return out_path


def _link_superdocs_document(client: SuperDocsClient, letter: GeneratedLetter) -> None:
    """Best-effort: find the SuperDocs durable File that this letter's
    drafting session produced, give it a readable title, and record its
    id so the letter can be reopened/reused directly in SuperDocs later.

    LIMITATION, stated plainly: chat()/export() responses in this build
    don't directly return a durable document_id (SuperDocs docs describe
    Files as auto-created from sessions, but the id isn't surfaced on the
    chat response itself in the version of the API this client targets).
    So this matches by recency against list_documents() -- the most
    recently updated File right after this session's chat/export call.
    That's a reasonable heuristic for a single-writer session but is NOT
    a guaranteed-correct id lookup under concurrent activity on the same
    account. If SuperDocs' API is confirmed to return the id directly on
    a future check, replace this heuristic with that direct value.
    """
    try:
        candidates = client.list_documents(limit=5)
    except Exception as exc:
        logger.warning("Could not list SuperDocs documents to link letter %s: %s", letter.id, exc)
        return
    if not candidates:
        return
    most_recent = candidates[0]
    document_id = most_recent.get("id") or most_recent.get("document_id")
    if not document_id:
        return
    title = f"{letter.case_id} - status letter ({letter.session_id})"
    try:
        client.rename_document(document_id, title)
    except SuperDocsError as exc:
        logger.warning("Could not rename SuperDocs document for letter %s: %s", letter.id, exc)
    letter.superdocs_document_id = document_id
    letter.superdocs_document_title = title


def archive_letter_document(db: Session, client: SuperDocsClient, letter_id: int, force: bool = False) -> None:
    """Archive (soft-delete, ~30-day recoverable) the SuperDocs durable
    File linked to this letter, if one was linked. No-op if none linked."""
    letter = db.get(GeneratedLetter, letter_id)
    if letter is None:
        raise NotFoundError(f"No letter with id {letter_id}")
    if not letter.superdocs_document_id:
        return
    client.archive_document(letter.superdocs_document_id, force=force)
    db.commit()
    logger.info("Archived SuperDocs document for letter %s", letter_id)
