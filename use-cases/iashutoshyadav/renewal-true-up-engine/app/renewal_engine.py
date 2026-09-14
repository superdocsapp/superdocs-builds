"""One customer, start to finish: extract terms -> compute true-up -> decide exception -> generate the
amendment through SuperDocs -> (human gate for exceptions only) -> export.

Clean vs. exception is where SuperDocs's two approval modes map directly onto the business rule
(app/true_up.py::determine_exception): a clean renewal's amendment auto-applies (approval_mode=approve_all,
verified in Phase 4 of the design), because there's nothing that needs a second pair of eyes - the entire
point of 'the cohort batch surfaces real exceptions instead of dumping everything into review.' An
exception's amendment pauses for a real human decision (approval_mode=ask_every_time, also verified live),
same mechanism SuperDocs itself uses for HITL.
"""

from __future__ import annotations

import base64
import uuid

from app.chart import render_usage_chart_svg
from app.clause_extraction import ClauseNotFoundError, extract_contract_terms
from app.models import (
    Customer,
    RenewalException,
    RenewalPackage,
    UsagePeriod,
)
from app.superdocs_client import SuperDocsClient
from app.true_up import compute_true_up, determine_exception


def _usage_report_text(customer: Customer, terms, usage: UsagePeriod) -> str:
    overage = max(0.0, usage.units_used - terms.entitlement_units)
    return (
        f"Usage Report - {customer.name} - {usage.period_label}\n\n"
        f"Contracted entitlement: {terms.entitlement_units:,.0f} compute units/month\n"
        f"Actual usage this period: {usage.units_used:,.0f} compute units\n"
        f"Overage: {overage:,.0f} compute units\n"
    )


class PendingHumanDecision(Exception):
    """Raised when an exception's amendment is awaiting approval and no decision has been supplied yet.
    The batch runner (app/batch.py) catches this, surfaces the pending change to a reviewer, and calls
    apply_human_decision() once a decision exists - this function never blocks waiting for a human."""

    def __init__(
        self,
        package: RenewalPackage,
        job_id: str,
        change_id: str,
        ai_explanation: str | None = None,
        old_html: str | None = None,
        new_html: str | None = None,
    ):
        super().__init__(f"renewal for {package.customer.customer_id} needs human approval")
        self.package = package
        self.job_id = job_id
        self.change_id = change_id
        self.ai_explanation = ai_explanation
        self.old_html = old_html
        self.new_html = new_html


def _renewal_quote_text(package: RenewalPackage) -> str:
    tu = package.true_up
    if tu is None or tu.true_up_amount == 0:
        return (
            f"{package.customer.name}: renewal at current terms, "
            f"{package.terms.entitlement_units:,.0f} units/month, no true-up owed this period."
        )
    return (
        f"{package.customer.name}: renewal quote includes a true-up of ${tu.true_up_amount:,.2f} "
        f"for {tu.overage_units:,.0f} units of overage at ${tu.overage_rate:.2f}/unit."
    )


def _talk_track(package: RenewalPackage) -> str:
    tu = package.true_up
    if tu is None or tu.true_up_amount == 0:
        return (
            f"{package.customer.name} is renewing cleanly at their current entitlement "
            f"({package.terms.entitlement_units:,.0f} units/month) - no overage, no true-up conversation needed."
        )
    return (
        f"{package.customer.name} exceeded their {tu.entitlement_units:,.0f}-unit entitlement by "
        f"{tu.overage_units:,.0f} units this period. Per the signed agreement (\"{tu.governing_clause_quote}\"), "
        f"that's a true-up of ${tu.true_up_amount:,.2f} at ${tu.overage_rate:.2f}/unit - walk them through the "
        f"exact math before presenting the renewal quote, the number should never surprise them."
    )


def start_renewal(
    client: SuperDocsClient,
    customer: Customer,
    contract_text: str,
    usage: UsagePeriod,
    new_entitlement_units: float,
    template_name: str | None = None,
) -> RenewalPackage:
    """Loads the contract into a SuperDocs session and proposes the entitlement amendment for the new
    period. For a clean renewal this returns a fully completed package. For an exception, this raises
    PendingHumanDecision - the amendment is proposed but not yet applied, exactly mirroring 'a person
    reviews what the system intends to do... before it commits' from the task brief's own Task 1 language,
    which the same discipline applies to here even though the document doesn't literally require it for
    Task 2."""
    # Real bug, found live on 2026-08-20: this used to be a bare f"renewal-{customer.customer_id}" - stable
    # across every run of the batch. Re-running the same sample cohort against the real API (exactly what
    # the "Run cohort batch" button invites) eventually left a prior run's async approval job still active
    # in that session, and the next run's chat_with_approval call failed with a real 409: error_code
    # 'session_busy' - "The AI is still working on a previous request in this conversation... use a
    # different session_id" (that suggestion is straight from SuperDocs's own error body). session_id only
    # needs to be consistent WITHIN one call - it flows through PendingHumanDecision.package.session_id to
    # the later approve step - not stable across separate runs, so a per-call suffix is safe.
    session_id = f"renewal-{customer.customer_id}-{uuid.uuid4()}"

    try:
        terms = extract_contract_terms(contract_text)
    except ClauseNotFoundError:
        package = RenewalPackage(
            customer=customer, terms=None, usage=usage, true_up=None,
            exception=RenewalException(customer.customer_id, reason="clause_not_found"),
            session_id=session_id,
        )
        return package

    true_up = compute_true_up(customer, terms, usage)
    exception = determine_exception(customer, true_up)

    contract_filename = f"{customer.customer_id}-contract.txt"
    usage_report_filename = f"{customer.customer_id}-usage-report.txt"

    # Second document in the same session (the "Multi-document" surface named on this build's card) - a
    # real usage report, not the contract re-uploaded. Two real bugs found live on 2026-09-14, in order:
    # (1) a soft "for context only, do not edit it" instruction was not enough disambiguation - SuperDocs
    # edited the usage report instead of the contract. (2) Naming both files explicitly in the chat
    # instruction did NOT fix it either - export_document(session_id) still returned the usage report.
    # export has no document/file parameter at all (just session_id + format), so it must be exporting
    # whichever document is the session's "active" one - and that turned out to be set by UPLOAD ORDER
    # (last uploaded = active), not by anything sent in a later chat message. Fixed by uploading the usage
    # report FIRST and the contract LAST, making the contract the active document for both chat edits and
    # export - re-verified live: correct document edited, correct document exported, usage report untouched.
    client.upload_document(
        usage_report_filename, _usage_report_text(customer, terms, usage).encode(), session_id=session_id,
    )
    client.upload_document(contract_filename, contract_text.encode(), session_id=session_id)

    chart_svg = render_usage_chart_svg(customer.name, terms.entitlement_units, usage.units_used)
    usage_chart_url = client.upload_image(base64.b64encode(chart_svg).decode("ascii"), "image/svg+xml")

    plain_amendment_message = (
        f"Edit ONLY the file named '{contract_filename}'. In that file, update the entitlement clause so "
        f"the Monthly Entitlement changes from {terms.entitlement_units:,.0f} to "
        f"{new_entitlement_units:,.0f} compute units. Leave everything else in '{contract_filename}' "
        f"unchanged. Do NOT modify the file named '{usage_report_filename}' under any circumstances - it "
        f"is reference-only context about this period's actual usage, not part of the contract."
    )

    package = RenewalPackage(
        customer=customer, terms=terms, usage=usage, true_up=true_up, exception=exception,
        session_id=session_id, amendment_session_id=session_id,
        usage_chart_url=usage_chart_url, usage_report_uploaded=True,
    )
    package.renewal_quote = _renewal_quote_text(package)
    package.talk_track = _talk_track(package)
    package.decisions.append({"true_up_amount": true_up.true_up_amount, "exception": exception is not None})

    if exception is None:
        # Clean: nothing for a human to weigh in on, apply immediately (approve_all). Deliberately never
        # references the template here - found live on 2026-08-20 that referencing it caused SuperDocs to
        # generate duplicated amendment sections and an unwanted "Please fill: Client Legal Name"
        # placeholder instead of the clean single-clause edit this path needs, and a clean renewal applies
        # with no human catching that before it lands. The plain instruction is what was already verified
        # to produce a correct, surgical edit.
        client.chat(plain_amendment_message, session_id=session_id, cross_session_search=True)
        package.exported_summary_markdown = client.export_document(session_id, format="markdown")
        return package

    # Exception: a human reviews the proposed amendment before it applies, so it's safe to try the
    # template-styled version here even though it's a less surgical edit - a bloated or oddly-placeholder'd
    # proposal gets caught at the review gate instead of landing silently.
    template_amendment_message = (
        f"{plain_amendment_message} Use the formatting and signature-block conventions from my uploaded "
        f"template '{template_name}' for this amendment's presentation only - do not add new sections, "
        f"do not repeat the entitlement update more than once, and do not treat the customer's name as "
        f"unknown when it is already present in the document you are editing."
        if template_name else plain_amendment_message
    )
    job = client.chat_with_approval(template_amendment_message, session_id=session_id, cross_session_search=True)
    resolved = client.wait_for_job(job.job_id) if hasattr(client, "wait_for_job") else client.get_job(job.job_id)
    if resolved.status != "awaiting_approval" or not resolved.pending_changes:
        # Nothing actually proposed (e.g. the AI declined) - still an exception, still needs a human,
        # just with nothing to approve yet. Surfaced as-is rather than silently treated as clean.
        return package
    change = resolved.pending_changes[0]
    raise PendingHumanDecision(
        package, job_id=job.job_id, change_id=change.change_id,
        ai_explanation=change.ai_explanation, old_html=change.old_html, new_html=change.new_html,
    )


def apply_human_decision(client: SuperDocsClient, package: RenewalPackage, job_id: str, change_id: str, approved: bool, reason: str | None = None) -> RenewalPackage:
    """Resumes a renewal that PendingHumanDecision paused. Rejecting an amendment doesn't discard the
    true-up record - the customer's true-up amount and governing clause stay in the package either way,
    only the document edit itself is applied or not (mirrors FR-18's 'rejecting one finding does not
    discard the rest', an engineering discipline carried over, not shared code).

    Real bug found and fixed during live verification: approve_change() returning success does not mean
    the edit has actually landed yet - the job needs to reach status='completed' before an export reflects
    it. The first version of this function exported immediately after approve_change and got back the
    UNCHANGED original document every time; this was verified working correctly by hand during design
    (Phase 4), but that manual polling step never made it into this function's code."""
    client.approve_change(package.session_id, job_id, change_id, approved=approved, feedback=reason)
    package.decisions.append({"approved": approved, "reason": reason})
    if approved:
        if hasattr(client, "wait_for_job"):
            client.wait_for_job(job_id)
        package.exported_summary_markdown = client.export_document(package.session_id, format="markdown")
    return package
