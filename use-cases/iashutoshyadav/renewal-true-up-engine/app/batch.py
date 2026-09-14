"""Runs a renewal cohort - the task card's own language: 'Batches run for the whole renewal cohort with
genuine exceptions flagged for a human.'

Design commitments, each a direct answer to a question the task brief raises explicitly for batch work:

- Failures are isolated per customer: one customer's crash never stops the batch (try/except inside the
  loop, not around it).
- Operations are bounded: `max_customers` is a hard stopping rule, not a suggestion - a runaway loop
  against a metered API (500 ops/month, verified in Phase 4) is exactly the mistake the task brief warns
  about ("budget your operations... give it a small-sample mode and a stopping rule").
- No automatic retry: a failed customer is reported, not silently retried - retrying against a
  metered, per-operation API multiplies the cost of a real failure instead of surfacing it.
- Progress is reported via a callback, not buried in logs only - a batch UI needs to show it live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.models import Customer, RenewalPackage, UsagePeriod
from app.renewal_engine import PendingHumanDecision, start_renewal
from app.superdocs_client import SuperDocsClient, SuperDocsError


@dataclass
class CohortItem:
    customer: Customer
    contract_text: str
    usage: UsagePeriod
    new_entitlement_units: float


@dataclass
class PendingReviewItem:
    package: RenewalPackage
    # None for the "no amendment could even be proposed" case (e.g. clause_not_found) - there's nothing
    # to approve/reject yet, just something a human needs to go fix at the source (the contract itself).
    job_id: str | None = None
    change_id: str | None = None
    # The actual proposed edit, not just its id - a human approving/rejecting must see what they're
    # deciding on. Real gap found auditing against the task brief: these were fetched from the API and
    # then never shown anywhere.
    ai_explanation: str | None = None
    old_html: str | None = None
    new_html: str | None = None


@dataclass
class FailedItem:
    customer_id: str
    error: str


@dataclass
class BatchResult:
    clean: list[RenewalPackage] = field(default_factory=list)
    pending_review: list[PendingReviewItem] = field(default_factory=list)
    failed: list[FailedItem] = field(default_factory=list)
    skipped_over_limit: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return len(self.clean) + len(self.pending_review) + len(self.failed)


ProgressCallback = Callable[[int, int, str, str], None]  # (index, total, customer_id, status)


def run_cohort_batch(
    client: SuperDocsClient,
    items: list[CohortItem],
    max_customers: int = 50,
    on_progress: ProgressCallback | None = None,
    template_name: str | None = None,
) -> BatchResult:
    """Clean renewals apply automatically inside start_renewal (approve_all) - only genuine exceptions
    make it into pending_review, matching 'surfaces real exceptions instead of dumping everything into
    review' (the task card's own bar for what strong looks like)."""
    result = BatchResult()

    to_process = items[:max_customers]
    result.skipped_over_limit = [i.customer.customer_id for i in items[max_customers:]]

    for index, item in enumerate(to_process, start=1):
        try:
            package = start_renewal(
                client, item.customer, item.contract_text, item.usage, item.new_entitlement_units,
                template_name=template_name,
            )
            # start_renewal returns normally (doesn't raise) for BOTH a truly clean renewal AND a
            # clause_not_found exception - the two are only distinguishable by package.exception. The
            # first version of this loop treated "didn't raise" as "clean", which silently routed a
            # clause-not-found package into the clean bucket - a real bug, caught by actually running the
            # app end to end against a cohort with a broken contract in it, not by unit tests (none of
            # which exercised both exception types together through the batch runner).
            if package.exception is not None:
                result.pending_review.append(PendingReviewItem(package=package))
                if on_progress:
                    on_progress(index, len(to_process), item.customer.customer_id, "pending_review")
                continue
            result.clean.append(package)
            if on_progress:
                on_progress(index, len(to_process), item.customer.customer_id, "clean")
        except PendingHumanDecision as pending:
            result.pending_review.append(
                PendingReviewItem(
                    package=pending.package, job_id=pending.job_id, change_id=pending.change_id,
                    ai_explanation=pending.ai_explanation, old_html=pending.old_html, new_html=pending.new_html,
                )
            )
            if on_progress:
                on_progress(index, len(to_process), item.customer.customer_id, "pending_review")
        except Exception as exc:  # noqa: BLE001 - deliberately broad: one bad customer must never abort the batch
            # SuperDocsError.detail carries the real API's own error body (error_code, message,
            # suggested_action) - str(exc) alone only says e.g. "SuperDocs API 409", which isn't enough
            # for an operator to act on. Found the hard way: diagnosing a real 409 here required writing
            # a throwaway script to inspect .detail directly, because the UI only ever showed the bare
            # status code. Surface the real detail so that's not necessary next time.
            message = str(exc)
            if isinstance(exc, SuperDocsError) and exc.detail:
                message = f"{message}: {exc.detail}"
            result.failed.append(FailedItem(customer_id=item.customer.customer_id, error=message))
            if on_progress:
                on_progress(index, len(to_process), item.customer.customer_id, "failed")

    return result
