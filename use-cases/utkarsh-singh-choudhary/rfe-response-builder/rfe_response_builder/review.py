"""
Review-gated drafting flow.

`build_response_packet` in generate.py answers every RFE item in one shot
(useful for the CLI / batch use) and only checks the reply text after the
fact. This module splits that into two phases so a human can approve,
edit, or reject each drafted section BEFORE it's treated as an answer or
reaches the exported document -- the `approve_change` /
`chat_async(approval_mode=...)` surface on SuperDocsClient already existed
for exactly this but was dead code until now.

Phase 1: `start_review()` opens the document and, for every RFE item,
starts an async chat turn with `approval_mode="ask_every_time"` so
SuperDocs holds the change pending rather than auto-applying it. Returns a
`ReviewSession` describing what's waiting on a human decision.

Phase 2: `finalize_review()` takes the human's per-item decisions
(approve / reject, optional feedback), calls `approve_change` for each
pending item, builds the coverage checklist from what was ACTUALLY
approved (never from "the API call succeeded"), appends the checklist +
exhibit list, and exports.

The pending-change JSON shape returned by SuperDocs for an
"awaiting_approval" job is inferred from the documented chat_async /
approve_change contract in superdocs_client.py, not confirmed against a
live response (this sandbox can't reach api.superdocs.app -- see the
generate.py Round 4 note in project history). `_interpret_job` is
deliberately defensive: it tries several plausible field names and falls
back to showing the reviewer the raw job JSON rather than crashing or
silently treating an unrecognized shape as approved. If the real shape
turns out to differ, this is the one function to adjust.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .classify import RFECategory, classify, extract_response_deadline
from .consistency import check_cross_item_consistency
from .embeddings import get_default_provider
from .firm_templates import FirmTemplate, apply_firm_customization
from .grounding import check_grounding
from .injection_guard import scan_all_inputs_for_injection_risk
from .judge import QualityVerdict, grade_draft
from .validation import CheckStatus, build_validation_summary
from .rfe import (
    CoverageRow,
    Exhibit,
    NewEvidenceCatalog,
    NewEvidenceEntry,
    PetitionArgument,
    PriorPetition,
    RFERequest,
    build_coverage_checklist,
    build_exhibit_list,
    build_response_instruction,
    is_substantive_reply,
    new_evidence_note_from_entries,
    parse_rfe_notice,
    response_section_heading,
    sanitize_case_id,
)
from .superdocs_client import SuperDocsClient, SuperDocsError

logger = logging.getLogger("rfe_response_builder.review")

STATUS_PENDING_REVIEW = "pending_review"
STATUS_NO_PENDING_CHANGE = "no_pending_change"
STATUS_FAILED = "failed"


@dataclass
class DraftItem:
    request_id: str
    request_text: str
    response_section: str
    instruction: str
    job_id: str | None
    reply_text: str
    status: str  # one of the STATUS_* constants above
    prior_source_refs: list[str] = field(default_factory=list)
    new_evidence: list[str] = field(default_factory=list)
    exhibit_numbers: list[int] = field(default_factory=list)
    fuzzy_suggestions: list[tuple[str, float]] = field(default_factory=list)  # (source_ref, confidence)
    suggestion_tier: str = "none"  # "fuzzy", "semantic", or "none" -- see PriorPetition.unverified_suggestions
    ungrounded_facts: list[str] = field(default_factory=list)  # see grounding.check_grounding
    quality_verdict: str = "unknown"  # QualityVerdict value -- see judge.py; "unknown" unless the gate ran
    quality_reasoning: str = ""


@dataclass
class ReviewSession:
    session_id: str
    case_id: str
    safe_case_id: str
    client_name: str
    requests: list[RFERequest]
    petition_matches: dict[str, list[PetitionArgument]]
    evidence_matches: dict[str, list[NewEvidenceEntry]]
    exhibits: list[Exhibit]
    items: list[DraftItem]
    classification_category: str = RFECategory.UNKNOWN.value
    classification_display_name: str = ""
    classification_note: str = ""
    deadline_days: int | None = None
    deadline_matched_sentence: str | None = None
    firm_name: str | None = None
    consistency_flags: list = field(default_factory=list)  # list[ConsistencyFlag], see consistency.py
    injection_flags: list = field(default_factory=list)  # list[(source, InjectionRiskResult)], see injection_guard.py


def _interpret_job(job: dict) -> tuple[str, str, str | None]:
    """Returns (reply_text, status, chunk_id_for_approval)."""
    status = job.get("status")
    if status == "awaiting_approval":
        pending = job.get("pending_changes") or job.get("changes") or []
        chunk_id = job.get("chunk_id") or job.get("job_id")
        if isinstance(pending, list) and pending:
            first = pending[0]
            chunk_id = first.get("chunk_id", chunk_id)
            text = first.get("proposed_text") or first.get("text") or first.get("diff")
            if not text:
                text = json.dumps(first)
        else:
            text = job.get("response") or job.get("message") or json.dumps(job)
        return text, STATUS_PENDING_REVIEW, chunk_id
    if status == "completed":
        text = job.get("response") or job.get("message") or ""
        return text, STATUS_NO_PENDING_CHANGE, None
    return (job.get("error") or job.get("response") or json.dumps(job)), STATUS_FAILED, None


def start_review(client: SuperDocsClient, session_id: str, case_id: str, client_name: str,
                  notice_text: str, petition: PriorPetition,
                  evidence_catalog: NewEvidenceCatalog | None = None,
                  firm_template: FirmTemplate | None = None,
                  progress_callback: "Callable[[int, int, str], None] | None" = None) -> ReviewSession:
    """`progress_callback`, if given, is invoked as
    `progress_callback(completed, total, current_item_label)` after EACH
    RFE item's drafting turn completes (whether it succeeded, failed, or
    was rejected as non-substantive -- "completed" here means "this item's
    turn is done," not "this item was answered"). Purely advisory: this
    function's actual behavior and return value are identical whether or
    not a callback is given. Exists so a caller with a long-running
    background job (see webapp/jobs.py's JobStore.update_progress) can
    surface real per-item progress instead of a static "in progress"
    spinner for what can be a minute-plus real drafting run."""
    evidence_catalog = evidence_catalog or NewEvidenceCatalog()
    safe_case_id = sanitize_case_id(case_id)

    requests_list = parse_rfe_notice(notice_text)
    if not requests_list:
        raise ValueError(
            "No RFE requests could be parsed from the notice -- aborting rather than "
            "starting a review with nothing in it."
        )

    petition_matches = {r.request_id: petition.best_matches(r) for r in requests_list}
    evidence_matches = {r.request_id: evidence_catalog.best_matches(r) for r in requests_list}
    embedding_provider = get_default_provider()  # shared across all items -- see generate.py's plan_response
    exhibits = build_exhibit_list(requests_list, evidence_matches)
    exhibit_by_request: dict[str, list[int]] = {}
    for ex in exhibits:
        for rid in ex.request_ids:
            exhibit_by_request.setdefault(rid, []).append(ex.number)

    classification = classify(notice_text)
    profile = classification.profile
    framework_note = profile.legal_framework_note if classification.category != RFECategory.UNKNOWN else None
    deadline = extract_response_deadline(notice_text)
    if classification.category != RFECategory.UNKNOWN:
        logger.info("session %s: detected filing type %s (score=%d, signals=%s)",
                    session_id, classification.category.value, classification.score, classification.matched_signals)

    # Prompt-injection risk scan (heuristic -- see injection_guard.py):
    # runs once, BEFORE any SuperDocs call is made, across every uploaded
    # document that will end up embedded in a drafting instruction.
    injection_flags = scan_all_inputs_for_injection_risk(
        notice_text=notice_text, petition=petition, evidence_catalog=evidence_catalog, firm_template=firm_template,
    )
    for source, result in injection_flags:
        logger.warning("session %s: possible prompt-injection phrasing detected in %s: %s",
                        session_id, source, ", ".join(result.matched_labels))

    # Header turn is system bookkeeping, not an officer-facing legal
    # argument -- no review needed for a title/intro paragraph.
    client.chat(
        session_id=session_id,
        message=(
            f"Start a new document titled 'RFE Response — {client_name} ({case_id})'. "
            f"Add a one-paragraph introduction stating this responds to the agency's "
            f"Request for Evidence, addressing each numbered item below in turn. "
            f"Do not draft the responses yet -- just the title and introduction."
        ),
    )

    items: list[DraftItem] = []
    for r in requests_list:
        prior_matches = petition_matches[r.request_id]
        prior_arg = prior_matches[0] if prior_matches else None
        note = new_evidence_note_from_entries(evidence_matches[r.request_id])
        instruction = build_response_instruction(r, prior_arg, note, legal_framework_note=framework_note)
        instruction = apply_firm_customization(instruction, firm_template, classification.category.value)
        suggestion_tier, suggestion_matches = (
            petition.unverified_suggestions(r, provider=embedding_provider) if not prior_matches else ("none", [])
        )
        try:
            job_id = client.chat_async(
                session_id=session_id, message=instruction, approval_mode="ask_every_time",
                idempotency_key=f"{session_id}:{r.request_id}",
            )
            job = client.wait_for_job(job_id)
            reply_text, status, chunk_id = _interpret_job(job)
        except SuperDocsError as e:
            logger.error("request %s: drafting turn failed -- %s", r.request_id, e)
            reply_text, status, chunk_id = str(e), STATUS_FAILED, None

        # Fact-grounding check (heuristic -- see grounding.py): only run
        # for a status where reply_text is an actual drafted section, not
        # a failure message. Source material = exactly what the drafting
        # model was actually given for this item.
        ungrounded: list[str] = []
        if status in (STATUS_PENDING_REVIEW, STATUS_NO_PENDING_CHANGE):
            source_texts = [r.text]
            if prior_arg:
                source_texts.append(prior_arg.text)
            source_texts.extend(e.description for e in evidence_matches[r.request_id])
            grounding = check_grounding(reply_text, source_texts)
            ungrounded = grounding.ungrounded_facts
            if ungrounded:
                logger.warning("request %s: %d possibly-unsupported detail(s) in draft -- %s",
                                r.request_id, len(ungrounded), ungrounded)

        # LLM-as-judge quality gate (see judge.py) -- OPT-IN via
        # QUALITY_GATE_ENABLED, since it's a second model call per
        # substantively-drafted item (real cost/latency, a firm should
        # choose this deliberately). Uses a SEPARATE grading session so
        # grading turns never pollute the drafting document's conversation.
        quality_verdict = QualityVerdict.UNKNOWN.value
        quality_reasoning = ""
        if status in (STATUS_PENDING_REVIEW, STATUS_NO_PENDING_CHANGE) and \
                os.environ.get("QUALITY_GATE_ENABLED", "").lower() in {"1", "true", "yes"}:
            grading = grade_draft(client, f"{session_id}-grading-{r.request_id}", r.text, reply_text)
            quality_verdict = grading.verdict.value
            quality_reasoning = grading.reasoning
            if grading.verdict == QualityVerdict.WEAK:
                logger.warning("request %s: quality gate flagged draft as WEAK -- %s",
                                r.request_id, grading.reasoning)

        items.append(
            DraftItem(
                request_id=r.request_id,
                request_text=r.text,
                response_section=response_section_heading(r.request_id),
                instruction=instruction,
                job_id=chunk_id,
                reply_text=reply_text,
                status=status,
                prior_source_refs=[m.source_ref for m in prior_matches],
                new_evidence=[e.description for e in evidence_matches[r.request_id]],
                exhibit_numbers=sorted(exhibit_by_request.get(r.request_id, [])),
                fuzzy_suggestions=[(arg.source_ref, conf) for arg, conf in suggestion_matches],
                suggestion_tier=suggestion_tier,
                ungrounded_facts=ungrounded,
                quality_verdict=quality_verdict,
                quality_reasoning=quality_reasoning,
            )
        )

        if progress_callback is not None:
            try:
                progress_callback(len(items), len(requests_list), response_section_heading(r.request_id))
            except Exception:  # noqa: BLE001 - a broken progress callback must never
                # abort or corrupt an actual drafting run; progress
                # reporting is purely advisory.
                logger.warning("progress_callback raised for request %s -- ignoring", r.request_id, exc_info=True)

    # Cross-item consistency check (heuristic -- see consistency.py): runs
    # once across ALL drafted items after the per-item loop above, since
    # it needs every item's text to compare against every other item's.
    consistency_flags = check_cross_item_consistency(
        [(item.request_id, item.reply_text) for item in items if item.reply_text]
    )
    if consistency_flags:
        logger.warning("session %s: %d cross-item consistency flag(s) -- %s",
                        session_id, len(consistency_flags), consistency_flags)

    return ReviewSession(
        session_id=session_id, case_id=case_id, safe_case_id=safe_case_id, client_name=client_name,
        requests=requests_list, petition_matches=petition_matches, evidence_matches=evidence_matches,
        exhibits=exhibits, items=items,
        classification_category=classification.category.value,
        classification_display_name=profile.display_name,
        classification_note=profile.legal_framework_note,
        deadline_days=deadline.days,
        deadline_matched_sentence=deadline.matched_sentence,
        firm_name=firm_template.firm_name if firm_template else None,
        consistency_flags=consistency_flags,
        injection_flags=injection_flags,
    )


def finalize_review(client: SuperDocsClient, session: ReviewSession,
                     decisions: dict[str, dict], out_dir: Path) -> tuple[Path, list[CoverageRow]]:
    """`decisions` maps request_id -> {"approve": bool, "feedback": str | None}.
    A request_id missing from `decisions` is treated as rejected -- silence
    is never approval. Only items that are BOTH approved by the human AND
    (for items with no pending change) substantively answered end up in
    `answered_ids`; everything else is NOT ANSWERED in the checklist,
    exactly like the non-review flow."""
    answered_ids: set[str] = set()

    for item in session.items:
        decision = decisions.get(item.request_id, {})
        wants_approval = bool(decision.get("approve"))

        if item.status == STATUS_PENDING_REVIEW and item.job_id:
            try:
                client.approve_change(
                    session_id=session.session_id, chunk_id=item.job_id,
                    approved=wants_approval, feedback=decision.get("feedback"),
                )
            except SuperDocsError as e:
                logger.error("request %s: approve_change call failed -- %s", item.request_id, e)
                wants_approval = False
            if wants_approval:
                answered_ids.add(item.request_id)
        elif item.status == STATUS_NO_PENDING_CHANGE:
            # No approval gate was actually offered by SuperDocs for this
            # turn (e.g. it answered synchronously) -- still require both
            # the human's yes AND that the text is substantive, same bar
            # as the non-review path.
            if wants_approval and is_substantive_reply(item.reply_text):
                answered_ids.add(item.request_id)
        # STATUS_FAILED items can never be answered regardless of decision.

    coverage = build_coverage_checklist(
        session.requests, session.petition_matches, answered_ids,
        evidence_matches=session.evidence_matches, exhibits=session.exhibits,
    )

    # Final pre-export validation summary (see validation.py) -- combines
    # coverage, cross-item consistency, and injection-risk flags into one
    # explicit go/no-go readout, logged loudly if it FAILs (an item
    # reaching export unanswered -- the one non-negotiable check this
    # package enforces). This is a summary of checks already run
    # elsewhere, not a new gate -- export still proceeds either way,
    # consistent with every other heuristic signal in this package: a
    # human decision (the approve/reject choices already made above),
    # not an automated block.
    validation_summary = build_validation_summary(
        coverage, consistency_flags=session.consistency_flags, injection_flags=session.injection_flags,
        exhibits=session.exhibits,
    )
    if validation_summary.has_failures:
        logger.error("session %s: pre-export validation FAILED -- %s", session.session_id,
                     [c.detail for c in validation_summary.checks if c.status == CheckStatus.FAIL])
    elif validation_summary.has_warnings:
        logger.warning("session %s: pre-export validation has warning(s) -- %s", session.session_id,
                        [c.detail for c in validation_summary.checks if c.status == CheckStatus.WARN])

    def _checklist_line(row: CoverageRow) -> str:
        status = "ANSWERED" if row.answered else "NOT ANSWERED"
        line = f"- Item {row.request_id}: {status} (section: {row.response_section})"
        if row.matched_prior_arguments:
            line += f" (prior petition: {'; '.join(row.matched_prior_arguments)})"
        else:
            line += " (new argument, no prior petition match)"
        if row.exhibit_numbers:
            exhibits_str = ", ".join("Exh. " + str(n) for n in row.exhibit_numbers)
            line += f" (exhibits: {exhibits_str})"
        line += f" [evidence status: {row.evidence_status}]"
        return line

    checklist_lines = "\n".join(_checklist_line(row) for row in coverage)
    client.chat(
        session_id=session.session_id,
        message=(
            f"Append a final section titled 'Coverage Checklist' listing, verbatim, "
            f"exactly this mapping of every RFE item to whether it was answered "
            f"(do not alter the ANSWERED/NOT ANSWERED status for any item):\n{checklist_lines}"
        ),
    )

    if session.exhibits:
        exhibit_lines = "\n".join(
            f"- Exhibit {ex.number} ({ex.label}): {ex.description} "
            f"[supports item(s): {', '.join(ex.request_ids)}]"
            for ex in session.exhibits
        )
        client.chat(
            session_id=session.session_id,
            message=(
                f"Append a final section titled 'Exhibit List' listing, verbatim, "
                f"exactly this list of new exhibits accompanying the response:\n{exhibit_lines}"
            ),
        )

    validation_lines = "\n".join(
        f"- {c.label}: {c.status.value.upper()}" + (f" -- {c.detail}" if c.detail else "")
        for c in validation_summary.checks
    )
    client.chat(
        session_id=session.session_id,
        message=(
            f"Append a final section titled 'Pre-Export Validation Summary' listing, "
            f"verbatim, exactly this list of checks (do not alter any status):\n{validation_lines}"
        ),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session.safe_case_id}-rfe-response.docx"
    file_bytes = client.export(session_id=session.session_id, fmt="docx", filename=session.safe_case_id + "-rfe-response")
    out_path.write_bytes(file_bytes)

    manifest_path = out_dir / f"{session.safe_case_id}-exhibit-manifest.json"
    manifest = [
        {"number": ex.number, "label": ex.label, "description": ex.description, "supports_request_ids": ex.request_ids}
        for ex in session.exhibits
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return out_path, coverage
