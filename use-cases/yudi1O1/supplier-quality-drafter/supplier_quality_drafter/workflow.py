"""End-to-end draft workflow: template -> chat -> human approval gate -> export.

This is the orchestration layer. It never talks numbers itself — by the time it
runs, `validate.py` has already refused to proceed if anything was missing, and
`render.py` has already turned the engineer's numbers into a literal HTML block.
This module's only job is the four-call contract: upload, chat, approve, export.

It is also where the two money-shaped concerns live: the idempotency check that
skips a draft already completed (`ledger.py`), and the usage report that says
what the run actually cost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .client import SuperDocsClient
from .ledger import RunLedger, fingerprint
from .models import DraftRequest
from .render import build_instruction
from .validate import validate_request
from .verify import VerificationResult, document_was_modified, verify_export


class DraftNotApplied(RuntimeError):
    """The turn completed but changed nothing. Raised instead of reporting success.

    Seen in a real run: SuperDocs returned a completed job whose response read
    "0 of 4 asked could be completed" and left the document untouched. Reporting
    that as a successful draft would be a lie, so it is an error."""


class DraftUnverified(RuntimeError):
    """The document changed and exported, but the exported file does not contain
    the engineer's facts. Also an error — 'exported' is not 'correct'."""

ApprovalCallback = Callable[[list[dict]], list[dict]]
"""Given the list of pending_changes (as dicts), return the list of
{"change_id": ..., "approved": bool} decisions. The CLI's default
implementation prints a diff and prompts on stdin; tests pass a stub that
approves everything so the flow can be exercised without a human."""


def approve_all(pending_changes: list[dict]) -> list[dict]:
    return [{"change_id": c["change_id"], "approved": True} for c in pending_changes]


@dataclass
class DraftResult:
    session_id: str
    job_id: str
    exported_path: str
    ai_response: str
    skipped: bool = False
    """True when an identical draft had already completed and was reused
    instead of re-billed. See ledger.py."""
    usage_summary: str = ""
    approvals: dict = field(default_factory=dict)
    """How many proposed changes the human approved vs rejected, counted from
    the decisions actually sent to /approve."""
    attempts: int = 1
    verification: Optional[VerificationResult] = None
    """Proof the exported file really contains the engineer's facts."""


def draft_document(
    client: SuperDocsClient,
    req: DraftRequest,
    template_path: str,
    session_id: str,
    export_path: str,
    export_format: str = "docx",
    approval_callback: ApprovalCallback = approve_all,
    model_tier: Optional[str] = None,
    ledger: Optional[RunLedger] = None,
    force: bool = False,
    max_attempts: int = 3,
) -> DraftResult:
    validation = validate_request(req)
    if not validation.ok_to_draft:
        lines = "\n".join(f"  - [{f.location}] {f.message}" for f in validation.blocking)
        raise ValueError(
            f"Refusing to draft: {len(validation.blocking)} blocking finding(s) — "
            f"ask the engineer for these before drafting, don't guess:\n{lines}"
        )

    instruction = build_instruction(req)

    # --- idempotency gate: never re-buy an operation for identical work ---
    # Only fingerprinted when a ledger is actually in play; hashing the template
    # is real I/O and shouldn't happen for callers who opted out.
    fp = fingerprint(session_id, instruction, template_path, export_format) if ledger is not None else None
    if ledger is not None and not force:
        previous = ledger.lookup(fp)
        if previous is not None:
            return DraftResult(
                session_id=previous.session_id,
                job_id=previous.job_id,
                exported_path=previous.export_path,
                ai_response="",
                skipped=True,
                usage_summary=(
                    f"0 billable request(s) issued — an identical draft completed at "
                    f"{previous.completed_at} and its output is still on disk. Use --force to redraft."
                ),
            )

    extra = {"approval_mode": "ask_every_time"}
    if model_tier:
        extra["model_tier"] = model_tier

    ai_response = ""
    approved_count = 0
    rejected_count = 0
    job_id = ""
    attempt = 0
    out = ""
    verification = None

    # The draft is attempted up to `max_attempts` times, and an attempt only
    # counts as successful once the exported file has been read back and shown
    # to contain the engineer's facts. Measured over repeated live runs, a
    # single attempt produced a fully-correct document only about a third of the
    # time on a four-section `combined` draft: sometimes the turn changed
    # nothing at all (the documented cold-session warm-up — "send it again and
    # it settles"), and sometimes it applied only some sections, landing the
    # FMEA table but silently dropping the PPAP and 8D narratives.
    #
    # Both failures are invisible to `status == "completed"` and both are fixed
    # by the same thing: reset the document to the pristine template and ask
    # again. So verification drives the retry rather than merely reporting a
    # failure after the fact. Uploads and exports are not billed, so the only
    # cost of an extra attempt is the chat turn itself.
    while attempt < max_attempts:
        attempt += 1

        # 1. Upload the customer's own template as the active document. Done per
        #    attempt so a retry starts from the clean template rather than
        #    layering a second draft onto a partially-drafted document.
        upload = client.upload_document(template_path, session_id=session_id)
        doc_html = upload["html"]

        # 2. Send the drafting instruction as an async HITL request.
        started = client.chat_async(instruction, session_id=session_id, document_html=doc_html, **extra)
        job_id = started["job_id"]
        job = client.poll_job(job_id)

        # 3. Human-in-the-loop gate — resolve every awaiting_approval round.
        while job.get("status") == "awaiting_approval":
            metadata = job.get("metadata", {})
            kind = metadata.get("awaiting_kind", "change_review")
            if kind == "continue_prompt":
                # A large edit paused to ask whether to keep going. This is NOT a
                # change review — calling /approve here is rejected with 409.
                client.continue_job(session_id, job_id, do_continue=True)
                job = client.poll_job(job_id)
                continue

            pending = metadata.get("pending_changes", [])
            decisions = approval_callback(pending)
            approved_count += sum(1 for d in decisions if d.get("approved"))
            rejected_count += sum(1 for d in decisions if not d.get("approved"))
            client.approve(session_id, job_id, approved=True, changes=decisions)
            job = client.poll_job(job_id)

        if job.get("status") != "completed":
            raise RuntimeError(
                f"Job ended in unexpected status: {job.get('status')}. "
                f"Fix: inspect the job with GET /v1/jobs/{job_id}; a 'cancelled' job was stopped "
                f"externally and can simply be re-run. Full payload: {job}"
            )

        result = job.get("result", {})
        ai_response = result.get("response", "")

        # 4a. Did the turn change anything at all?
        if not document_was_modified(result, doc_html):
            if attempt >= max_attempts:
                raise DraftNotApplied(
                    f"The draft turn completed but changed nothing across {attempt} attempt(s), so no "
                    f"document was produced. Reported as a failure rather than a successful draft, "
                    f"because the output is not in the state a success would claim.\n"
                    f"SuperDocs said: {ai_response.strip()[:600]}\n"
                    f"Fix: re-run; if it repeats, the instruction may not match the template's "
                    f"structure — check the template actually has the sections being populated."
                )
            continue

        # 4b. Export (not billed) and read the file back. "Exported" is not
        #     "correct"; only the bytes on disk can tell them apart.
        out = client.export_document(export_path, session_id=session_id, format=export_format)
        verification = verify_export(out, req)

        if verification.ok or not verification.readable:
            break

        if attempt >= max_attempts:
            raise DraftUnverified(
                f"Exported {out}, but after {attempt} attempt(s) {len(verification.missing)} of "
                f"{verification.checked} expected fact(s) are still missing from it: "
                f"{verification.missing[:10]}. Not reporting this as a successful draft.\n"
                f"Fix: this is usually a partial application — the edit landed some sections and "
                f"dropped others. Re-run, or split the draft by document_type (fmea / ppap / 8d) so "
                f"each turn edits fewer sections."
            )
        # Otherwise: partial application. Loop and redraft from the clean template.

    if ledger is not None and fp is not None:
        ledger.record(fp, session_id=session_id, export_path=out, job_id=job_id)

    return DraftResult(
        session_id=session_id,
        job_id=job_id,
        exported_path=out,
        ai_response=ai_response,
        skipped=False,
        usage_summary=client.usage.summary(),
        approvals={"approved": approved_count, "rejected": rejected_count},
        attempts=attempt,
        verification=verification,
    )
