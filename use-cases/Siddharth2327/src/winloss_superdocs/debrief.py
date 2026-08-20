"""create_debrief(): one transcript -> one Win/Loss Debrief document.

Orchestrates: attach transcript -> HARD STOP unless attachment processing genuinely
completed -> reviewed chat draft -> schema check -> evidence verification (label,
don't silently drop) -> export -> local index upsert.
See architecture.md §9 for the full data-flow diagram this implements.

Root-cause fix (see progress.md): a prior version of this function waited for
attachment processing but discarded the result without checking it, so a debrief
could be (and, in a real run, WAS) generated from a chat call that had no real
transcript content behind it -- the model fabricated a plausible-looking debrief
instead. This is now a hard stop: chat_async is never called unless
wait_for_attachment reports status == "completed" explicitly.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from .client import SuperDocsClient
from .index import DebriefRecord, Index, parse_debrief_html
from .review import ApprovalCallback, auto_approve_all, run_reviewed_chat
from .schema import check_debrief_schema
from .templates import DebriefInput, build_debrief_instruction
from .verification import verify_evidence_quotes

logger = logging.getLogger(__name__)


class SkippedAlreadyIndexed(RuntimeError):
    """Raised (informationally) when a deal_code + unchanged transcript is
    re-submitted without --force -- the idempotency guard from architecture.md §12."""


class AttachmentProcessingFailed(RuntimeError):
    """Raised when transcript attachment processing did not reach status=='completed'.

    This is the hard stop: create_debrief() must NEVER call chat_async unless the
    attachment genuinely finished processing, because a debrief generated without
    real source material is worse than no debrief -- it looks legitimate (correct
    schema, plausible prose, well-formed evidence quotes) while being entirely
    fabricated. See progress.md for the real run that surfaced this.
    """

    def __init__(self, deal_code: str, session_id: str, job_id: str, status: str, job: dict):
        self.deal_code = deal_code
        self.session_id = session_id
        self.job_id = job_id
        self.status = status
        self.job = job
        super().__init__(
            f"Refusing to draft debrief {deal_code}: transcript attachment "
            f"(session={session_id}, job={job_id}) ended in status={status!r}, not "
            f"'completed'. No chat call was made -- generating a debrief without "
            f"confirmed source material would risk fabricated content passing as "
            f"real. Full job payload: {job}"
        )


@dataclass
class DebriefResult:
    record: DebriefRecord
    exported_path: Path
    unverified_evidence: list[str]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _append_verification_notes(html: str, unverified: list[str]) -> str:
    if not unverified:
        return html
    items = "".join(f"<li>{q}</li>" for q in unverified)
    notes = (
        '<h2>Verification Notes</h2>'
        '<p>The following evidence quote(s) could not be automatically confirmed '
        "against the source transcript and should be reviewed manually before this "
        "debrief is relied on:</p>"
        f"<ul>{items}</ul>"
    )
    return html + notes


def preview_debrief_call(inp: DebriefInput, transcript_path: Path) -> dict:
    """Everything create_debrief() would do, with zero network calls. Used by
    `--dry-run`."""
    return {
        "session_id": f"debrief-{inp.deal_code}",
        "transcript_path": str(transcript_path),
        "instruction": build_debrief_instruction(inp),
        "export_target": f"outputs/debriefs/{inp.deal_code}.docx",
    }


def create_debrief(
    client: SuperDocsClient,
    index: Index,
    *,
    transcript_path: Path,
    deal_code: str,
    quarter: str,
    segment: str,
    outcome: str,
    customer_name: str,
    customer_aliases: list[str] | None = None,
    output_dir: Path,
    approval_callback: ApprovalCallback = auto_approve_all,
    force: bool = False,
) -> DebriefResult:
    if outcome not in ("win", "loss"):
        raise ValueError(f"outcome must be 'win' or 'loss', got {outcome!r}")

    transcript_hash = _sha256_file(transcript_path)
    existing = index.get(deal_code)
    if existing and existing.transcript_sha256 == transcript_hash and not force:
        raise SkippedAlreadyIndexed(
            f"{deal_code} already indexed from an identical transcript. Pass "
            "force=True / --force to regenerate (this will spend operations again)."
        )

    inp = DebriefInput(deal_code=deal_code, quarter=quarter, segment=segment, outcome=outcome)
    session_id = f"debrief-{deal_code}"

    upload = client.upload_attachment(session_id, str(transcript_path))
    attachment_job = client.wait_for_attachment(session_id, upload["job_id"])
    attachment_status = attachment_job.get("status")
    logger.info(
        "attachment processing finished: deal_code=%s session=%s job=%s status=%s",
        deal_code, session_id, upload["job_id"], attachment_status,
    )

    # HARD STOP -- the primary safety mechanism. Everything below this point
    # (including the very first chat call) must never run unless the attachment
    # explicitly reports status=="completed". No other status is treated as good
    # enough to proceed on, including anything we don't recognize.
    if attachment_status != "completed":
        logger.error(
            "attachment processing did NOT complete cleanly; refusing to draft "
            "debrief without confirmed source material: deal_code=%s status=%s job=%s",
            deal_code, attachment_status, attachment_job,
        )
        raise AttachmentProcessingFailed(
            deal_code=deal_code,
            session_id=session_id,
            job_id=upload["job_id"],
            status=str(attachment_status),
            job=attachment_job,
        )

    instruction = build_debrief_instruction(inp)
    job = run_reviewed_chat(client, session_id, instruction, approval_callback)

    result = job.get("result", {})
    document_changes = result.get("document_changes") or {}
    html = document_changes.get("updated_html") or result.get("response", "")
    if not html:
        raise RuntimeError(f"No document HTML returned for {deal_code}; job result: {result}")

    check_debrief_schema(html).raise_if_failed(f"Debrief {deal_code}")

    transcript_text = transcript_path.read_text(errors="ignore")
    evidence_check = verify_evidence_quotes(html, transcript_text)
    logger.info(
        "evidence verification: deal_code=%s total_quotes=%d grounded=%d unverified=%d",
        deal_code, evidence_check.total_quotes, len(evidence_check.grounded_quotes),
        len(evidence_check.unverified_quotes),
    )
    if evidence_check.unverified_quotes:
        for q in evidence_check.unverified_quotes:
            logger.warning("unverified evidence quote: deal_code=%s quote=%r", deal_code, q[:200])

    final_html = _append_verification_notes(html, evidence_check.unverified_quotes)

    # Logging to pin down, on the next real run, whether Verification Notes that
    # SHOULD be present (unverified_quotes non-empty) actually make it into the
    # HTML we send to export -- this was observed missing from a real exported
    # docx once, and we don't yet know if the append failed, was stripped on
    # export, or the unverified list was genuinely empty for that run. This log
    # line answers that definitively on the next occurrence.
    notes_present = "Verification Notes" in final_html
    logger.info(
        "pre-export html check: deal_code=%s unverified_count=%d "
        "verification_notes_appended=%s final_html_length=%d",
        deal_code, len(evidence_check.unverified_quotes), notes_present, len(final_html),
    )
    if evidence_check.unverified_quotes and not notes_present:
        logger.error(
            "BUG: unverified_quotes is non-empty but 'Verification Notes' is not "
            "present in final_html before export -- _append_verification_notes "
            "did not run as expected. deal_code=%s", deal_code,
        )

    docx_bytes = client.export(html=final_html, format="docx", options={"filename": deal_code})
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_path = output_dir / f"{deal_code}.docx"
    exported_path.write_bytes(docx_bytes)
    logger.info(
        "exported debrief: deal_code=%s path=%s docx_bytes=%d", deal_code, exported_path, len(docx_bytes)
    )

    parsed = parse_debrief_html(final_html)
    record = DebriefRecord(
        deal_code=deal_code,
        quarter=quarter,
        segment=segment,
        outcome=outcome,
        competitors=parsed["competitors"],
        evidence_snippets=parsed["evidence_snippets"],
        customer_name=customer_name,
        customer_aliases=customer_aliases or [],
        transcript_path=str(transcript_path),
        transcript_sha256=transcript_hash,
        exported_path=str(exported_path),
        superdocs_document_id=result.get("document_id"),
        unverified_evidence_count=len(evidence_check.unverified_quotes),
    )
    index.upsert(record)

    return DebriefResult(record=record, exported_path=exported_path, unverified_evidence=evidence_check.unverified_quotes)
