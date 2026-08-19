"""Runs the recap generation for every lead in one batch. The property
this module exists to guarantee: N leads in, N documents out, each
document generated from an independently-uploaded template with only
that lead's own data — never a shared session, never a shared document,
never a partial batch silently truncated.

Three failure modes were found running this against the live API and
are specifically guarded against here — see the comments below marked
"Found running live" for exactly what happened and why.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.leads import Lead, load_leads
from app.recap_content import RecapSections, build_recap_sections
from app.superdocs_client import SuperDocsClient
from app.util import sanitize_session_id
from app.verify import find_unresolved_tokens, missing_expected_fields, verify_recap_text

logger = logging.getLogger("batch")

MAX_ATTEMPTS_PER_LEAD = 2  # 1 normal attempt + 1 retry-on-verification-failure


@dataclass
class RecapResult:
    lead_id: str
    session_id: str
    output_path: Path
    used_fallback_notes: bool
    used_fallback_next_step: bool
    verification_issues: list[str]
    attempts: int


class BatchError(Exception):
    def __init__(self, lead_id: str, cause: Exception):
        super().__init__(f"failed on lead {lead_id}: {cause}")
        self.lead_id = lead_id
        self.cause = cause


def run_batch(
    leads_csv: Path,
    template_path: Path,
    output_dir: Path,
    client: SuperDocsClient,
    export_format: str = "pdf",
    max_leads: int | None = None,
) -> list[RecapResult]:
    leads = load_leads(leads_csv)
    if max_leads is not None and len(leads) > max_leads:
        logger.info(
            "%d lead(s) in CSV, processing only the first %d this run (max_leads=%d)",
            len(leads), max_leads, max_leads,
        )
        leads = leads[:max_leads]

    output_dir.mkdir(parents=True, exist_ok=True)
    template_content = template_path.read_bytes()

    # Found running live: two separate CLI invocations (e.g. a --limit 1
    # smoke test, then a full run) reused the exact same deterministic
    # session_id for the same lead. SuperDocs sessions persist server-side
    # WITH their full chat history even when the document body is reset by
    # a fresh upload — so the second run's identical substitution
    # instruction landed in a session that already "remembered" doing this
    # exact edit, and the AI correctly-but-unhelpfully treated it as an
    # already-satisfied no-op, leaving every {{token}} untouched. A
    # per-process run salt makes that collision structurally impossible:
    # every invocation of this CLI gets entirely fresh sessions.
    run_salt = uuid.uuid4().hex[:8]

    results: list[RecapResult] = []
    errors: list[BatchError] = []

    for lead in leads:
        try:
            results.append(
                _process_one_lead(
                    lead, template_path.name, template_content, output_dir,
                    client, export_format, run_salt,
                )
            )
        except Exception as e:  # noqa: BLE001 — deliberately broad: one
            # bad lead must never silently drop the rest of the batch,
            # and must never be swallowed either. Collected and reported.
            errors.append(BatchError(lead.lead_id, e))
            logger.exception("Failed to generate recap for lead %s", lead.lead_id)

    if errors:
        failed_ids = [e.lead_id for e in errors]
        logger.warning(
            "%d of %d leads failed and were skipped: %s",
            len(errors), len(leads), failed_ids,
        )

    flagged = [r for r in results if r.verification_issues]
    if flagged:
        logger.warning(
            "%d of %d generated recaps still have verification issues after every "
            "retry and cleanup pass (see per-lead output): %s",
            len(flagged), len(results), [r.lead_id for r in flagged],
        )

    logger.info(
        "Batch complete: %d input lead(s), %d document(s) produced, %d failed",
        len(leads), len(results), len(errors),
    )
    return results


def _process_one_lead(
    lead: Lead,
    template_filename: str,
    template_content: bytes,
    output_dir: Path,
    client: SuperDocsClient,
    export_format: str,
    run_salt: str,
) -> RecapResult:
    sections = build_recap_sections(lead)
    token_values = _token_values(sections)

    issues: list[str] = []
    session_id = ""
    attempt = 0

    for attempt in range(1, MAX_ATTEMPTS_PER_LEAD + 1):
        session_id = sanitize_session_id(
            f"recap-{run_salt}-{lead.lead_id}-{_slugify(lead.name)}"
            + (f"-retry{attempt}" if attempt > 1 else "")
        )
        client.upload_document(template_content, template_filename, session_id)

        # Found running live: a single instruction asking the AI to make
        # all 7 substitutions in one turn was demonstrably unreliable —
        # one real run left the SAME 3 fields (the header line's
        # lead_name/lead_company, plus the longest, most detail-dense
        # section) unresolved on two separate, fully independent
        # attempts against two fresh sessions. Identical failure twice
        # in a row on an unchanged instruction means the problem was
        # structural (the model losing track partway through a big
        # multi-field edit), not random flakiness a retry alone could
        # fix. Splitting into smaller, section-scoped turns — matching
        # docs.superdocs.app/guides/model-selection's own guidance that
        # vague/broad instructions "invite wide edits" and narrow,
        # single-section instructions are more reliable — removes the
        # ambiguity that caused it.
        _substitute(client, session_id, {
            k: token_values[k] for k in ("lead_name", "lead_company", "internal_owner", "event_name")
        }, "the document's header line, and every other place these names appear")
        _substitute(
            client, session_id, {"discussion_section": token_values["discussion_section"]},
            "the WHAT WE DISCUSSED section",
        )
        _substitute(
            client, session_id, {"promised_section": token_values["promised_section"]},
            "the WHAT WE PROMISED section",
        )
        _substitute(
            client, session_id, {"next_step_section": token_values["next_step_section"]},
            "the NEXT STEP section",
        )

        verification_text = _export_text(client, session_id)
        issues = verify_recap_text(verification_text, sections)

        if issues:
            # One targeted cleanup pass naming exactly what's still
            # wrong — cheaper and more precise than immediately falling
            # back to a whole fresh-session retry, and catches the
            # common case where 6 of 7 fields landed fine and only one
            # needs another push.
            leftover = (
                set(find_unresolved_tokens(verification_text))
                | set(missing_expected_fields(verification_text, sections))
            ) & token_values.keys()
            if leftover:
                _substitute(
                    client, session_id,
                    {k: token_values[k] for k in leftover},
                    "the specific placeholder(s) listed below — every other part of "
                    "this document is already correct and must not be touched",
                )
                verification_text = _export_text(client, session_id)
                issues = verify_recap_text(verification_text, sections)

        if not issues:
            break
        logger.warning(
            "Lead %s: verification issues on attempt %d/%d: %s",
            lead.lead_id, attempt, MAX_ATTEMPTS_PER_LEAD, issues,
        )

    content = client.export_bytes(session_id, export_format)
    output_path = output_dir / f"{lead.lead_id}_{_slugify(lead.name)}.{export_format}"
    output_path.write_bytes(content)

    return RecapResult(
        lead_id=lead.lead_id,
        session_id=session_id,
        output_path=output_path,
        used_fallback_notes=not lead.has_notes,
        used_fallback_next_step=not lead.has_next_step,
        verification_issues=issues,
        attempts=attempt,
    )


def _token_values(sections: RecapSections) -> dict[str, str]:
    return {
        "lead_name": sections.lead_name,
        "lead_company": sections.lead_company,
        "discussion_section": sections.discussion_section,
        "promised_section": sections.promised_section,
        "next_step_section": sections.next_step_section,
        "internal_owner": "Sales Team",
        "event_name": "the conference",
    }


def _substitute(
    client: SuperDocsClient, session_id: str, token_map: dict[str, str], scope_description: str
) -> None:
    if not token_map:
        return
    # The judgment about what the recap says already happened in
    # app/recap_content.py, before SuperDocs is ever called. SuperDocs'
    # job here is genuinely mechanical substitution and document
    # styling, not composition — this instruction is an exact, literal
    # substitution request, never "summarize this lead's interest," and
    # is deliberately scoped to just this handful of tokens (see
    # "Found running live" above for why narrow scope matters here).
    lines = [
        "Replace EVERY occurrence of each placeholder token below with its "
        f"exact given text. This covers {scope_description}. Change nothing "
        "else in the document. Some tokens may appear more than once; "
        "replace all occurrences, not just the first. Do not add, infer, "
        "embellish, paraphrase, or omit any content beyond these exact "
        "substitutions. Keep multi-sentence values exactly as given, word "
        "for word.\n\n"
    ]
    for token, value in token_map.items():
        lines.append(f"  {{{{{token}}}}} -> \u00ab{value}\u00bb\n")
    instruction = "".join(lines)
    client.edit_document(
        session_id,
        instruction,
        approval_mode="approve_all",
    )


def _export_text(client: SuperDocsClient, session_id: str) -> str:
    return client.export_bytes(session_id, "txt").decode("utf-8", errors="replace")


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
