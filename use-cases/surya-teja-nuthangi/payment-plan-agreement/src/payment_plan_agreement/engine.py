from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .models import AgreementProjection, CreatePlanRequest, Frequency, Installment, LateFeeKind, PaymentPlan

CURRENCIES = {"USD": ("$", 2), "EUR": ("€", 2), "INR": ("₹", 2), "GBP": ("£", 2)}


def _money(value: Decimal, currency: str) -> Decimal:
    if currency not in CURRENCIES:
        raise ValueError(f"unsupported currency: {currency}")
    units = CURRENCIES[currency][1]
    return value.quantize(Decimal(1).scaleb(-units), rounding=ROUND_HALF_UP)


def _monthly(first: date, offset: int) -> date:
    index = first.year * 12 + first.month - 1 + offset
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(first.day, calendar.monthrange(year, month)[1]))


def _due_date(first: date, frequency: Frequency, offset: int) -> date:
    if frequency == Frequency.WEEKLY:
        return first + timedelta(days=7 * offset)
    if frequency == Frequency.BIWEEKLY:
        return first + timedelta(days=14 * offset)
    return _monthly(first, offset)


def _format_money(value: Decimal, currency: str) -> str:
    symbol, units = CURRENCIES[currency]
    return f"{symbol}{value:,.{units}f}"


def _canonical_payload(plan: PaymentPlan) -> dict[str, object]:
    fee = plan.terms.late_fee
    return {
        "creditor": plan.creditor.legal_name,
        "debtor": plan.debtor.legal_name,
        "currency": plan.terms.currency,
        "original_balance": str(plan.terms.original_balance),
        "upfront_payment": str(plan.terms.upfront_payment),
        "frequency": plan.terms.frequency.value,
        "installments": [{"date": i.due_date.isoformat(), "amount": str(i.amount)} for i in plan.installments],
        "late_fee": {"kind": fee.kind.value, "amount": str(fee.amount) if fee.amount is not None else None, "percent": str(fee.percent) if fee.percent is not None else None, "grace_days": fee.grace_days},
        "agreement_date": plan.terms.agreement_date.isoformat(),
        "reference_id": plan.terms.reference_id,
    }


class PaymentPlanService:
    def calculate(self, request: CreatePlanRequest) -> PaymentPlan:
        terms = request.terms
        currency = terms.currency
        original = _money(terms.original_balance, currency)
        upfront = _money(terms.upfront_payment, currency)
        if original <= 0:
            raise ValueError("original balance must be positive")
        if upfront < 0 or upfront >= original:
            raise ValueError("upfront payment must be non-negative and below original balance")
        if terms.first_due_date < terms.agreement_date:
            raise ValueError("first due date cannot precede agreement date")
        if terms.late_fee.kind == LateFeeKind.FIXED:
            _money(terms.late_fee.amount or Decimal(0), currency)
        financed = original - upfront
        factor = 10 ** CURRENCIES[currency][1]
        total_minor = int(financed * factor)
        base, remainder = divmod(total_minor, terms.installment_count)
        if base == 0:
            raise ValueError("installment count exceeds available minor units")
        balance_minor = total_minor
        installments: list[Installment] = []
        for index in range(terms.installment_count):
            amount_minor = base + (1 if index < remainder else 0)
            balance_minor -= amount_minor
            installments.append(Installment(number=index + 1, due_date=_due_date(terms.first_due_date, terms.frequency, index), amount=Decimal(amount_minor) / factor, balance_after=Decimal(balance_minor) / factor))
        warnings: list[str] = []
        extra = terms.additional_terms or ""
        if re.search(r"(?:[$€₹£]\s*\d|\b\d+\s+(?:installments?|payments?)|\b(?:weekly|biweekly|monthly)\b)", extra, re.I):
            warnings.append("Additional terms contain structured money, count, or cadence language; review for collisions.")
        provisional = PaymentPlan(creditor=request.creditor, debtor=request.debtor, terms=terms.model_copy(update={"original_balance": original, "upfront_payment": upfront}), financed_balance=financed, installments=installments, total_scheduled=sum((x.amount for x in installments), Decimal(0)), final_due_date=installments[-1].due_date, semantic_fingerprint="", warnings=warnings)
        fingerprint = hashlib.sha256(json.dumps(_canonical_payload(provisional), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return provisional.model_copy(update={"semantic_fingerprint": fingerprint})

    def canonical_facts(self, plan: PaymentPlan) -> dict[str, str | int]:
        facts: dict[str, str | int] = {
            "agreement.date": plan.terms.agreement_date.isoformat(), "creditor.name": plan.creditor.legal_name, "debtor.name": plan.debtor.legal_name,
            "balance.original": str(plan.terms.original_balance), "balance.upfront": str(plan.terms.upfront_payment), "balance.financed": str(plan.financed_balance),
            "installments.count": len(plan.installments), "installments.frequency": plan.terms.frequency.value, "installments.first_due": plan.installments[0].due_date.isoformat(),
            "installments.final_due": plan.final_due_date.isoformat(), "installments.total": str(plan.total_scheduled), "late_fee.kind": plan.terms.late_fee.kind.value,
            "late_fee.grace_days": plan.terms.late_fee.grace_days,
        }
        if plan.terms.reference_id: facts["reference.id"] = plan.terms.reference_id
        if plan.terms.late_fee.amount is not None: facts["late_fee.amount"] = str(plan.terms.late_fee.amount)
        if plan.terms.late_fee.percent is not None: facts["late_fee.percent"] = str(plan.terms.late_fee.percent)
        for item in plan.installments:
            facts[f"installment.{item.number}.amount"] = str(item.amount)
            facts[f"installment.{item.number}.due_date"] = item.due_date.isoformat()
            facts[f"installment.{item.number}.balance_after"] = str(item.balance_after)
        return facts

    def project(self, plan: PaymentPlan) -> AgreementProjection:
        c = plan.terms.currency
        amounts = [i.amount for i in plan.installments]
        if len(set(amounts)) == 1:
            prose = f"The financed balance of {_format_money(plan.financed_balance, c)} will be paid in {len(amounts)} {plan.terms.frequency.value} installments of {_format_money(amounts[0], c)}, beginning {plan.installments[0].due_date:%B %d, %Y} and ending {plan.final_due_date:%B %d, %Y}."
        else:
            prose = f"The financed balance of {_format_money(plan.financed_balance, c)} will be paid in {len(amounts)} {plan.terms.frequency.value} installments totaling {_format_money(plan.total_scheduled, c)}, in the exact amounts and on the dates shown in the schedule, beginning {plan.installments[0].due_date:%B %d, %Y} and ending {plan.final_due_date:%B %d, %Y}."
        rows = [{"number": str(i.number), "due_date": i.due_date.isoformat(), "amount": _format_money(i.amount, c), "balance_after": _format_money(i.balance_after, c)} for i in plan.installments]
        return AgreementProjection(title="Payment Plan Agreement", intro_fields={"creditor": plan.creditor.legal_name, "debtor": plan.debtor.legal_name, "agreement_date": plan.terms.agreement_date.isoformat(), "reference_id": plan.terms.reference_id or ""}, schedule_columns=["Payment", "Due date", "Amount", "Balance after"], schedule_rows=rows, term_bindings={"original_balance": _format_money(plan.terms.original_balance, c), "upfront_payment": _format_money(plan.terms.upfront_payment, c), "financed_balance": _format_money(plan.financed_balance, c), "frequency": plan.terms.frequency.value}, signature_fields={"creditor": plan.creditor.legal_name, "debtor": plan.debtor.legal_name}, prose_payment_terms=prose)
