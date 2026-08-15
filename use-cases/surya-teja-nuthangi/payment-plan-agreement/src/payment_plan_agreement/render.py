from __future__ import annotations

from html import escape

from .engine import PaymentPlanService
from .models import LateFeeKind, PaymentPlan


def render_seed_html(plan: PaymentPlan) -> str:
    projection = PaymentPlanService().project(plan)
    terms = plan.terms
    rows = "".join(
        f'<tr data-installment="{row["number"]}"><td>{row["number"]}</td><td>{row["due_date"]}</td><td>{row["amount"]}</td><td>{row["balance_after"]}</td></tr>'
        for row in projection.schedule_rows
    )
    upfront = projection.term_bindings["upfront_payment"]
    if terms.late_fee.kind == LateFeeKind.NONE:
        fee = "No late fee applies."
    elif terms.late_fee.kind == LateFeeKind.FIXED:
        symbol = projection.schedule_rows[0]["amount"][0]
        fee = f"A fixed late fee of {symbol}{terms.late_fee.amount:.2f} applies after a grace period of {terms.late_fee.grace_days} days."
    else:
        fee = f"A late fee of {terms.late_fee.percent}% applies after a grace period of {terms.late_fee.grace_days} days."
    reference = f'<p data-field="reference-id">Reference: {escape(terms.reference_id)}</p>' if terms.reference_id else ""
    additional = f'<p data-field="additional-terms">{escape(terms.additional_terms)}</p>' if terms.additional_terms else ""
    return (
        '<article data-agreement="payment-plan-v1">'
        '<h1 data-chunk-id="title">Payment Plan Agreement</h1>'
        f'<section data-agreement-section="parties" data-chunk-id="parties"><h2>Parties</h2><p>This agreement is between <strong>{escape(plan.creditor.legal_name)}</strong> (Creditor) and <strong>{escape(plan.debtor.legal_name)}</strong> (Debtor).</p></section>'
        f'<section data-agreement-section="amounts" data-chunk-id="amounts"><h2>Amount Owed</h2><p data-field="original-balance">Original balance: {projection.term_bindings["original_balance"]}.</p><p data-field="upfront-payment">Upfront payment: {upfront}.</p><p data-field="financed-balance">Financed balance: {projection.term_bindings["financed_balance"]}.</p>{reference}</section>'
        f'<section data-agreement-section="payment-schedule" data-chunk-id="schedule"><h2>Payment Schedule</h2><table data-payment-schedule="v1"><thead><tr><th>Payment</th><th>Due date</th><th>Amount</th><th>Balance after</th></tr></thead><tbody>{rows}</tbody></table></section>'
        f'<section data-agreement-section="payment-terms" data-chunk-id="payment-terms"><h2>Payment Terms</h2><p>{escape(projection.prose_payment_terms)}</p></section>'
        f'<section data-agreement-section="late-fee" data-chunk-id="late-fee"><h2>Late Payment</h2><p>{escape(fee)}</p></section>'
        f'<section data-agreement-section="general" data-chunk-id="general"><h2>General Terms</h2><p>Early payment is allowed without penalty. Contact the Creditor promptly if a payment may be missed.</p>{additional}</section>'
        f'<section data-agreement-section="signatures" data-chunk-id="signatures"><h2>Signatures</h2><p>Creditor: {escape(plan.creditor.legal_name)} ____________________</p><p>Debtor: {escape(plan.debtor.legal_name)} ____________________</p><p>Agreement date: {terms.agreement_date.isoformat()}</p></section>'
        '</article>'
    )


def protected_instruction(plan: PaymentPlan) -> str:
    facts = PaymentPlanService().canonical_facts(plan)
    protected = "; ".join(f"{key}={value}" for key, value in sorted(facts.items()))
    return "Edit this agreement only for clarity, plain language, organization, and signature readiness. Preserve the schedule table and every protected fact exactly. Do not calculate, add fees, dates, methods, addresses, jurisdiction, or legal requirements. Propose each change for human review. Protected facts: " + protected
