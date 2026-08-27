"""Draft a three-document pack through SuperDocs: upload, chat, approve, export.

Orchestration only. By the time anything here runs, `validate.py` has refused to
proceed if a disclosure's applicability was unanswerable or a rule was stale, and
`assemble.py` has produced three finished, cross-referenced documents. This
module's job is to lay each one onto the customer's template and prove it landed.

Two behaviours are inherited from the sibling supplier-quality build because
both were earned from live API failures rather than reasoned about:

* **A `completed` job that changed nothing is a failure, not a success.** It is
  retried, and if it never applies, it raises rather than reporting a draft.
* **Verification drives the retry.** An export is only accepted once the file on
  disk is read back and shown to contain the pack's facts. A partial application
  — some sections landed, others silently dropped — is invisible to job status
  and only the bytes can tell them apart.

What is new here is that a pack is three documents, so the ledger is consulted
**per document**. Answering one more disclosure question changes the compliance
index and usually not the lease; re-billing the lease for that would be paying
twice for the same output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .assemble import DOCUMENT_ORDER, DocumentSet, check_consistency
from .client import SuperDocsClient
from .ledger import RunLedger, fingerprint
from .models import safe_slug
from .rules import Jurisdiction
from .verify import VerificationResult, document_was_modified, verify_export


class DraftNotApplied(RuntimeError):
    """The turn completed but changed nothing. Raised instead of reporting success."""


class DraftUnverified(RuntimeError):
    """The document changed and exported, but the exported file does not contain
    the pack's facts. 'Exported' is not 'correct'."""


class PackInconsistent(RuntimeError):
    """The three assembled documents disagree with each other. Raised before any
    billable call — shipping an internally inconsistent pack is the failure this
    whole build exists to prevent, so it is never merely warned about."""


ApprovalCallback = Callable[[list[dict]], list[dict]]


def approve_all(pending_changes: list[dict]) -> list[dict]:
    return [{"change_id": c["change_id"], "approved": True} for c in pending_changes]


@dataclass
class DocumentResult:
    kind: str
    exported_path: str
    job_id: str = ""
    skipped: bool = False
    attempts: int = 1
    ai_response: str = ""
    verification: Optional[VerificationResult] = None


@dataclass
class PackResult:
    pack_id: str
    session_id: str
    documents: list[DocumentResult] = field(default_factory=list)
    usage_summary: str = ""
    approvals: dict = field(default_factory=lambda: {"approved": 0, "rejected": 0})

    @property
    def billable_documents(self) -> int:
        return sum(1 for d in self.documents if not d.skipped)


def _export_path(out_dir: str, pack_id: str, kind: str, export_format: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # pack_id is user-supplied. Slugged so it cannot escape out_dir.
    return str(Path(out_dir) / f"{safe_slug(pack_id)}-{kind}.{safe_slug(export_format, 'out')}")


def draft_pack(
    client: SuperDocsClient,
    doc_set: DocumentSet,
    template_path: str,
    session_id: str,
    out_dir: str,
    export_format: str = "docx",
    approval_callback: ApprovalCallback = approve_all,
    kinds: Optional[list[str]] = None,
    ledger: Optional[RunLedger] = None,
    force: bool = False,
    max_attempts: int = 3,
    model_tier: Optional[str] = None,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> PackResult:
    """Draft each document in the pack onto the same customer template.

    The consistency check runs first and raises on failure. It costs nothing and
    catches the class of bug that would otherwise be discovered by a landlord.
    """
    problems = check_consistency(doc_set)
    if problems:
        raise PackInconsistent(
            "The assembled pack is internally inconsistent, so nothing was drafted and nothing was "
            "billed:\n" + "\n".join(f"  - {p}" for p in problems)
        )

    kinds = kinds or list(DOCUMENT_ORDER)
    result = PackResult(pack_id=doc_set.pack_id, session_id=session_id)
    req = doc_set.request
    jurisdiction: Jurisdiction = doc_set.jurisdiction

    for kind in kinds:
        document = doc_set.get(kind)
        instruction = document.instruction(req, jurisdiction)
        export_path = _export_path(out_dir, doc_set.pack_id, kind, export_format)
        # Each document gets its own session so a retry that re-uploads the
        # pristine template cannot inherit the previous document's edits.
        doc_session = f"{session_id}-{kind}"

        fp = fingerprint(doc_session, instruction, template_path, export_format) if ledger is not None else None
        if ledger is not None and not force:
            previous = ledger.lookup(fp)
            if previous is not None:
                if on_progress:
                    on_progress(kind, f"skipped — identical draft completed at {previous.completed_at}")
                result.documents.append(
                    DocumentResult(kind=kind, exported_path=previous.export_path, job_id=previous.job_id, skipped=True)
                )
                continue

        if on_progress:
            on_progress(kind, "drafting")

        doc_result = _draft_one(
            client=client,
            kind=kind,
            instruction=instruction,
            template_path=template_path,
            session_id=doc_session,
            export_path=export_path,
            export_format=export_format,
            approval_callback=approval_callback,
            doc_set=doc_set,
            max_attempts=max_attempts,
            model_tier=model_tier,
            approvals=result.approvals,
        )
        result.documents.append(doc_result)

        if ledger is not None and fp is not None:
            ledger.record(fp, session_id=doc_session, export_path=doc_result.exported_path, job_id=doc_result.job_id)

    result.usage_summary = client.usage.summary()
    return result


def _draft_one(
    client: SuperDocsClient,
    kind: str,
    instruction: str,
    template_path: str,
    session_id: str,
    export_path: str,
    export_format: str,
    approval_callback: ApprovalCallback,
    doc_set: DocumentSet,
    max_attempts: int,
    model_tier: Optional[str],
    approvals: dict,
) -> DocumentResult:
    extra: dict = {"approval_mode": "ask_every_time"}
    if model_tier:
        extra["model_tier"] = model_tier

    attempt = 0
    ai_response = ""
    job_id = ""
    out = ""
    verification: Optional[VerificationResult] = None

    while attempt < max_attempts:
        attempt += 1

        # 1. Upload the customer's template as the active document. Per attempt,
        #    so a retry starts clean rather than layering onto a partial draft.
        upload = client.upload_document(template_path, session_id=session_id)
        doc_html = upload["html"]

        # 2. One async HITL chat turn carrying the finished content.
        started = client.chat_async(instruction, session_id=session_id, document_html=doc_html, **extra)
        job_id = started["job_id"]
        job = client.poll_job(job_id)

        # 3. Resolve every approval round.
        while job.get("status") == "awaiting_approval":
            metadata = job.get("metadata", {})
            if metadata.get("awaiting_kind", "change_review") == "continue_prompt":
                # A large edit pausing to ask whether to continue. Calling
                # /approve here is rejected with 409 — it needs /continue.
                client.continue_job(session_id, job_id, do_continue=True)
                job = client.poll_job(job_id)
                continue
            decisions = approval_callback(metadata.get("pending_changes", []))
            approvals["approved"] += sum(1 for d in decisions if d.get("approved"))
            approvals["rejected"] += sum(1 for d in decisions if not d.get("approved"))
            client.approve(session_id, job_id, approved=True, changes=decisions)
            job = client.poll_job(job_id)

        if job.get("status") != "completed":
            raise RuntimeError(
                f"[{kind}] Job ended in unexpected status: {job.get('status')}. "
                f"Fix: inspect it with GET /v1/jobs/{job_id}; a 'cancelled' job was stopped externally "
                f"and can simply be re-run."
            )

        result_payload = job.get("result", {})
        ai_response = result_payload.get("response", "")

        # 4a. Did the turn change anything at all?
        if not document_was_modified(result_payload, doc_html):
            if attempt >= max_attempts:
                raise DraftNotApplied(
                    f"[{kind}] The draft turn completed but changed nothing across {attempt} attempt(s), "
                    f"so no document was produced. Reported as a failure rather than a successful draft.\n"
                    f"SuperDocs said: {ai_response.strip()[:600]}\n"
                    f"Fix: re-run; if it repeats, check the template actually has somewhere for this "
                    f"content to land."
                )
            continue

        # 4b. Export (not billed) and read the bytes back.
        out = client.export_document(export_path, session_id=session_id, format=export_format)
        verification = verify_export(out, doc_set, kind)

        if verification.ok or not verification.readable:
            break

        if attempt >= max_attempts:
            raise DraftUnverified(
                f"[{kind}] Exported {out}, but after {attempt} attempt(s) {len(verification.missing)} of "
                f"{verification.checked} expected fact(s) are still missing: {verification.missing[:10]}. "
                f"Not reporting this as a successful draft.\n"
                f"Fix: this is usually a partial application — the edit landed some sections and dropped "
                f"others. Re-run, or draft one document at a time with --only."
            )

    return DocumentResult(
        kind=kind,
        exported_path=out,
        job_id=job_id,
        skipped=False,
        attempts=attempt,
        ai_response=ai_response,
        verification=verification,
    )
