"""True-up arithmetic and the exception rule. Both are deliberately simple and fully deterministic -
transparent and reproducible by the customer is the literal bar the task card sets ('true-up arithmetic
is transparent and reproducible by the customer'), and a formula a human can re-derive by hand beats a
black box every time for that specific requirement.
"""

from __future__ import annotations

from app.models import ContractTerms, Customer, RenewalException, TrueUpResult, UsagePeriod


def compute_true_up(customer: Customer, terms: ContractTerms, usage: UsagePeriod) -> TrueUpResult:
    """overage = max(0, usage - entitlement); true_up = overage * rate. That's the whole formula - no
    proration, no tiering, no minimums. Matches the worked example this build was designed against:
    entitlement 100, usage 125, overage 25, rate $20/unit -> true_up $500."""
    overage_units = max(0.0, usage.units_used - terms.entitlement_units)
    true_up_amount = overage_units * terms.overage_rate
    return TrueUpResult(
        customer_id=customer.customer_id,
        entitlement_units=terms.entitlement_units,
        units_used=usage.units_used,
        overage_units=overage_units,
        overage_rate=terms.overage_rate,
        true_up_amount=true_up_amount,
        governing_clause_quote=terms.overage_rate_quote,
    )


def determine_exception(customer: Customer, true_up: TrueUpResult) -> RenewalException | None:
    """The exception rule this build committed to (Phase 6 of the design - the task card leaves 'genuine
    exception' undefined, so this is an engineering decision, not a document requirement): a renewal needs
    a human whenever real money changes hands (true_up_amount > 0). A clean renewal (no overage) never
    needed the reviewer's attention in the first place - that's the entire point of 'surfaces real
    exceptions instead of dumping everything into review.'"""
    if true_up.true_up_amount > 0:
        return RenewalException(customer_id=customer.customer_id, reason="overage_true_up_required")
    return None
