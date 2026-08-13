"""Publishes the already-verified, already-rendered memo (drafter/
synthesize.py's output) into SuperDocs as a real document -- the part of
Task 2 that actually calls SuperDocs's product API, per the task doc's own
"build ON SuperDocs" instruction.

THE TRUST BOUNDARY, STATED EXPLICITLY: by the time memo_html reaches this
module, every conclusion in it has already been independently verified
against the contract (drafter/analysis.py) and deterministically rendered
(drafter/synthesize.py). SuperDocs's own AI is used here ONLY for
formatting/polish, never to re-author or add content -- the memo_html is
passed as a document_html verbatim load (per llms-full.txt: "the AI never
re-types it... describing the content only in message makes the AI author
it, which can drift from your text"), and the instruction message
explicitly forbids altering conclusions, citations, or figures. This keeps
the actual accounting reasoning safely in OUR code, the same trust
boundary Task 1 uses for its own document (nothing the model claims is
trusted without a code-level check) -- SuperDocs is the authoring/delivery
product, not a second, unverified source of judgement.

HITL, NOT AUTO-APPLY: uses chat_async with approval_mode="ask_every_time"
(not the simpler synchronous chat()) because llms-full.txt calls this out
as "required for regulated workflows (legal, medical, compliance) where
every AI edit must be reviewed before it touches the document" -- a
revenue recognition memo is exactly that. Mirrors Task 1's human-gate
philosophy: nothing reaches a final, committed document without an
explicit human decision on every proposed change.

Shaped the same way as pipeline/runner.py's four operations (run/status/
approve/resume), for the same reason: separate, independently-callable
functions rather than one long blocking function, so a human reviewer (or
an MCP tool wrapping these, mirroring Task 1's stage 8) can inspect
pending changes and decide, out of band, instead of the caller being
forced to auto-approve just to get the call to return.

A REAL FINDING FROM AN ACTUAL MCP VALIDATION RUN (2026-08-11), stated
honestly because it changed this module's design: the authoring
instruction explicitly forbids altering wording, but SuperDocs's AI still
produced several proposed changes that DID alter real text -- e.g.
"a point-in-time recognition" became "a point-in-time Recognition timing"
mid-sentence, and "the extended warranty" became "the extended_warranty"
(substituting the internal obligation_id into prose) -- while every one of
those changes' own ai_explanation field still described itself as pure
formatting. A prompt instruction alone is not a control; it's a request
the model can fail to honor. So this module no longer trusts
ai_explanation, or blanket-approves a batch: `change_is_formatting_only()`
independently verifies each proposed change's actual before/after TEXT
(stripped of HTML markup) is identical before it can be auto-approved --
the exact same "never trust a claim, verify it in code" posture as
core/citations.py's quote_is_verifiable(), just applied to SuperDocs's own
output instead of the LLM's.
"""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from core.logging import get_logger
from core.superdocs_client import SuperDocsClient

logger = get_logger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_REPLACEMENTS = {
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&amp;": "&",
    "&nbsp;": " ",
}


def _strip_html_tags(html: str) -> str:
    """Strips markup and normalizes whitespace/entities so two HTML
    fragments can be compared on their actual TEXT content alone,
    regardless of tag differences (a <strong> added, a list restructured).
    This is what lets change_is_formatting_only() tell "formatting
    changed" apart from "content changed" -- not SuperDocs's own claim
    about what it did."""
    text = _TAG_RE.sub(" ", html)
    for entity, replacement in _ENTITY_REPLACEMENTS.items():
        text = text.replace(entity, replacement)
    return " ".join(text.split())


def change_is_formatting_only(old_html: str, new_html: str) -> bool:
    """THE core verification behind this module's trust boundary: a
    proposed change is safe to auto-approve ONLY if its underlying text
    content is identical before and after, regardless of what the
    change's own ai_explanation claims. See the module docstring for the
    real MCP validation run that made this necessary, not hypothetical."""
    return _strip_html_tags(old_html) == _strip_html_tags(new_html)

_MEMO_AUTHORING_INSTRUCTION = (
    "Load this revenue recognition memo as the working document. Apply "
    "clean, professional formatting suitable for an accounting memo "
    "(consistent heading styles, spacing, list formatting) if needed, but "
    "do NOT alter, add, remove, or reword any conclusion, citation, dollar "
    "figure, or judgement note -- every word of substantive content must "
    "be preserved exactly as provided. If the content is already well "
    "formatted, make no changes at all."
)

TerminalJobStatus = Literal["completed", "failed", "cancelled"]
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class MemoJobFailedError(Exception):
    """The SuperDocs job reached a terminal failed/cancelled state."""


def start_memo_authoring_job(
    client: SuperDocsClient, session_id: str, memo_html: str
) -> dict[str, Any]:
    """Starts the async, HITL-approved authoring job. Returns {"job_id": ...}
    immediately -- the caller polls get_memo_job() for status."""
    result = client.chat_async(
        message=_MEMO_AUTHORING_INSTRUCTION,
        session_id=session_id,
        document_html=memo_html,
        approval_mode="ask_every_time",
    )
    logger.info("memo_authoring_job_started", session_id=session_id, job_id=result.get("job_id"))
    return result


def get_memo_job(client: SuperDocsClient, job_id: str) -> dict[str, Any]:
    """Read-only status check -- see core/superdocs_client.py's get_job()
    for why this is never idempotency-cached."""
    return client.get_job(job_id)


def approve_pending_change(
    client: SuperDocsClient,
    session_id: str,
    job_id: str,
    change_id: str,
    approved: bool,
    feedback: str = "",
) -> dict[str, Any]:
    """Approves or denies exactly ONE proposed change. Kept single-change
    (rather than only supporting a batch call) so a caller reviewing
    changes one at a time -- the realistic shape for a human actually
    reading each proposed edit -- doesn't have to collect every decision
    before submitting any of them."""
    return client.approve(
        session_id=session_id,
        job_id=job_id,
        approved=approved,
        change_id=change_id,
        feedback=feedback or None,
    )


def resolve_pending_changes_by_content_verification(
    client: SuperDocsClient, session_id: str, job_id: str, pending_changes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Replaces a naive blanket-approve: verifies EACH proposed change's
    actual text content (not its ai_explanation) before deciding.
    Formatting-only changes are approved; any change that alters real text
    is DENIED and logged loudly -- surfaced as a real event, not hidden,
    since it means SuperDocs's AI didn't honor the authoring instruction
    for that specific edit.

    Calls approve_pending_change() once per change rather than one batch
    call with mixed per-item decisions -- llms-full.txt's own batch
    example only ever shows a batch where every decision agrees with the
    top-level `approved` flag; its exact semantics for a batch with genuinely
    MIXED true/false decisions aren't documented, and this is exactly the
    kind of ambiguity not worth risking silently doing the wrong thing over
    -- the single-change endpoint's behavior is unambiguous."""
    approved_count = 0
    denied_count = 0
    for change in pending_changes:
        change_id = change["change_id"]
        old_html = change.get("old_html", "")
        new_html = change.get("new_html", "")
        safe = change_is_formatting_only(old_html, new_html)

        if safe:
            approved_count += 1
        else:
            denied_count += 1
            logger.warning(
                "memo_authoring_change_altered_content_denied",
                job_id=job_id,
                change_id=change_id,
                old_text=_strip_html_tags(old_html)[:300],
                new_text=_strip_html_tags(new_html)[:300],
            )

        approve_pending_change(
            client,
            session_id,
            job_id,
            change_id,
            approved=safe,
            feedback="" if safe else "Denied: proposed change altered substantive text content, not formatting-only as instructed.",
        )

    logger.info(
        "memo_authoring_changes_resolved",
        job_id=job_id,
        approved_count=approved_count,
        denied_count=denied_count,
    )
    return {"approved_count": approved_count, "denied_count": denied_count}


def poll_until_resolved(
    client: SuperDocsClient,
    job_id: str,
    session_id: str,
    auto_approve: bool = False,
    poll_interval_seconds: float = 2.0,
    max_polls: int = 150,
) -> dict[str, Any]:
    """Polls get_job() until a terminal status. With auto_approve=True,
    resolves proposed changes along the way via
    resolve_pending_changes_by_content_verification() -- each change is
    independently verified as formatting-only before being approved; a
    change that alters real text is denied automatically, not blindly
    approved (see module docstring). Returns the final job dict on
    success; raises MemoJobFailedError on failed/cancelled.

    max_polls exists as the concrete mechanism behind TASK.md's "large-doc
    operations can take 30s-several minutes with no visible progress" +
    "build a stopping rule" gotchas -- a caller that's NOT auto-approving
    and never gets a human decision would otherwise poll forever."""
    for attempt in range(max_polls):
        job = get_memo_job(client, job_id)
        status = job.get("status")

        if status == "completed":
            logger.info("memo_authoring_job_completed", job_id=job_id, attempts=attempt + 1)
            return job
        if status in ("failed", "cancelled"):
            logger.warning("memo_authoring_job_failed", job_id=job_id, status=status)
            raise MemoJobFailedError(f"job {job_id} ended with status={status}: {job.get('error')}")

        if status == "awaiting_approval":
            pending = job.get("metadata", {}).get("pending_changes", [])
            if auto_approve and pending:
                logger.info(
                    "memo_authoring_resolving_pending_changes",
                    job_id=job_id,
                    change_count=len(pending),
                )
                resolve_pending_changes_by_content_verification(client, session_id, job_id, pending)
                continue  # re-poll immediately; job should now resume processing
            if not auto_approve:
                # Not auto-approving: return control to the caller with the
                # pending changes visible, rather than blocking forever
                # waiting for a decision nothing in this call can make.
                return job

        time.sleep(poll_interval_seconds)

    raise MemoJobFailedError(
        f"job {job_id} did not reach a terminal status after {max_polls} polls "
        f"({max_polls * poll_interval_seconds:.0f}s) -- stopping rather than "
        "polling indefinitely, per TASK.md's budget-operation gotcha"
    )


def export_memo(
    client: SuperDocsClient, session_id: str, format: str = "docx"
) -> dict[str, Any]:
    """The final step -- exports the (now human-approved, formatted)
    memo document. Only ever called after poll_until_resolved() returns a
    completed job; calling it earlier would export a not-yet-finished
    document."""
    result = client.export(session_id=session_id, format=format)
    logger.info("memo_exported", session_id=session_id, format=format)
    return result
