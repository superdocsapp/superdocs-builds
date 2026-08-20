"""Arithmetic validation engine (Project 2 core).

Design
------
Each check is a small, independently testable function registered in
``CHECKS``. Adding "validate operating margin" is one function plus one
registry entry — no change to the engine.

Every finding explains *why* the inconsistency exists (which operands were
combined, what relationship is expected to hold, what the drift looks like),
not merely that the numbers differ.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.core.config import get_settings
from app.engines.normalization import close_enough, format_money, parse_money, parse_percentage
from app.schemas.domain import (
    Citation,
    Fact,
    FactType,
    Finding,
    FindingCategory,
    Severity,
    Table,
)

settings = get_settings()


@dataclass(slots=True)
class LineItem:
    label: str
    amount: float
    currency: str
    citation: Citation
    fact_id=None


def _severity_for(relative_error: float) -> Severity:
    """Severity is a function of materiality, not of check type."""
    if relative_error >= 0.10:
        return Severity.CRITICAL
    if relative_error >= 0.02:
        return Severity.HIGH
    if relative_error >= 0.001:
        return Severity.MEDIUM
    return Severity.LOW


def _relative(expected: float, actual: float) -> float:
    denom = max(abs(expected), 1e-9)
    return abs(expected - actual) / denom


def _finding(
    *,
    finding_type: str,
    title: str,
    explanation: str,
    expected: float,
    actual: float,
    currency: str | None,
    citations: list[Citation],
    evidence: list[str],
    fact_ids: Iterable = (),
    confidence: float = 0.95,
    category: FindingCategory = FindingCategory.NUMERIC,
) -> Finding:
    delta = actual - expected
    return Finding(
        category=category,
        finding_type=finding_type,
        severity=_severity_for(_relative(expected, actual)),
        confidence=confidence,
        title=title,
        explanation=explanation,
        expected_value=format_money(expected, currency),
        actual_value=format_money(actual, currency),
        difference=f"{'+' if delta >= 0 else ''}{format_money(delta, currency)} "
        f"({_relative(expected, actual) * 100:.2f}% of expected)",
        suggested_correction=(
            f"Restate the stated figure as {format_money(expected, currency)}, or correct the "
            f"contributing line items so they sum to {format_money(actual, currency)}."
        ),
        evidence=evidence,
        citations=citations,
        related_fact_ids=list(fact_ids),
    )


# --------------------------------------------------------------------------
# Table-level checks
# --------------------------------------------------------------------------

_TOTAL_LABELS = re.compile(r"\b(total|grand\s*total|amount\s*due|balance\s*due)\b", re.I)
_SUBTOTAL_LABELS = re.compile(r"\b(sub\s*-?\s*total)\b", re.I)
_TAX_LABELS = re.compile(r"\b(tax|gst|vat|cgst|sgst|igst)\b", re.I)
_DISCOUNT_LABELS = re.compile(r"\b(discount|rebate|concession)\b", re.I)


def _table_line_items(table: Table, document_id=None) -> list[LineItem]:
    items: list[LineItem] = []
    for row in table.rows:
        if not row:
            continue
        label = str(row[0]).strip()
        money = None
        for cell in reversed(row[1:]):
            money = parse_money(str(cell))
            if money:
                break
        if not money or not label:
            continue
        items.append(
            LineItem(
                label=label,
                amount=money["amount"],
                currency=money["currency"],
                citation=Citation(
                    document_id=document_id,
                    page=table.page,
                    section=table.section or table.caption,
                    quote=f"{label}: {money['raw']}",
                ),
            )
        )
    return items


def check_table_totals(tables: list[Table], document_id=None) -> list[Finding]:
    """Validate that subtotal/tax/discount/total form a coherent arithmetic
    chain inside each table."""
    findings: list[Finding] = []
    tol = settings.arithmetic_tolerance

    for table in tables:
        items = _table_line_items(table, document_id)
        if len(items) < 2:
            continue

        totals = [i for i in items if _TOTAL_LABELS.search(i.label) and not _SUBTOTAL_LABELS.search(i.label)]
        subtotals = [i for i in items if _SUBTOTAL_LABELS.search(i.label)]
        taxes = [i for i in items if _TAX_LABELS.search(i.label)]
        discounts = [i for i in items if _DISCOUNT_LABELS.search(i.label)]
        special = {id(i) for i in totals + subtotals + taxes + discounts}
        plain = [i for i in items if id(i) not in special]

        currency = next((i.currency for i in items if i.currency != "UNKNOWN"), None)

        # 1. Line items must sum to the stated subtotal.
        if subtotals and plain:
            expected = sum(i.amount for i in plain)
            stated = subtotals[0].amount
            if not close_enough(expected, stated, tol):
                findings.append(
                    _finding(
                        finding_type="subtotal_mismatch",
                        title=f"Subtotal does not equal the sum of its line items ({table.caption or f'table on page {table.page}'})",
                        explanation=(
                            "The subtotal line is defined as the sum of the individual line items above it. "
                            f"Summing the {len(plain)} line items "
                            f"({', '.join(f'{i.label}={format_money(i.amount, i.currency)}' for i in plain[:6])}"
                            f"{'…' if len(plain) > 6 else ''}) yields {format_money(expected, currency)}, "
                            f"but the document states {format_money(stated, currency)}. The gap of "
                            f"{format_money(stated - expected, currency)} means either a line item is missing "
                            "from the table, a line item was double-counted, or the subtotal was edited "
                            "without recomputing the column."
                        ),
                        expected=expected,
                        actual=stated,
                        currency=currency,
                        citations=[i.citation for i in plain] + [subtotals[0].citation],
                        evidence=[f"{i.label} = {format_money(i.amount, i.currency)}" for i in plain]
                        + [f"Stated subtotal = {format_money(stated, currency)}"],
                    )
                )

        # 2. Subtotal - discount + tax must equal the stated total.
        base = subtotals[0].amount if subtotals else (sum(i.amount for i in plain) if plain else None)
        if totals and base is not None:
            expected = base - sum(d.amount for d in discounts) + sum(t.amount for t in taxes)
            stated = totals[0].amount
            if not close_enough(expected, stated, tol):
                composition = " ".join(
                    [format_money(base, currency)]
                    + [f"- {format_money(d.amount, currency)} ({d.label})" for d in discounts]
                    + [f"+ {format_money(t.amount, currency)} ({t.label})" for t in taxes]
                )
                findings.append(
                    _finding(
                        finding_type="total_mismatch",
                        title=f"Stated total is inconsistent with subtotal, tax and discount lines ({table.caption or f'table on page {table.page}'})",
                        explanation=(
                            "A document total must equal subtotal minus discounts plus taxes. "
                            f"Composing the stated components — {composition} — gives "
                            f"{format_money(expected, currency)}, while the document reports "
                            f"{format_money(stated, currency)}. A difference of this shape usually means a "
                            "tax or discount line was applied to a different base than the printed subtotal "
                            "(for example tax computed before a discount), or a component line was revised "
                            "without recomputing the total."
                        ),
                        expected=expected,
                        actual=stated,
                        currency=currency,
                        citations=[i.citation for i in subtotals + discounts + taxes] + [totals[0].citation],
                        evidence=[f"{i.label} = {format_money(i.amount, i.currency)}" for i in subtotals + discounts + taxes]
                        + [f"Stated total = {format_money(stated, currency)}"],
                    )
                )

        # 3. Tax lines must be consistent with any stated tax rate.
        for tax in taxes:
            percent = parse_percentage(tax.label)
            if not percent or base is None:
                continue
            expected = base * percent["fraction"]
            if not close_enough(expected, tax.amount, max(tol, abs(expected) * 0.005)):
                findings.append(
                    _finding(
                        finding_type="tax_rate_mismatch",
                        title=f"{tax.label} amount does not match the stated rate",
                        explanation=(
                            f"The line is labelled at {percent['value']}%, so applying it to the taxable base "
                            f"of {format_money(base, currency)} should produce "
                            f"{format_money(expected, currency)}. The document shows "
                            f"{format_money(tax.amount, currency)}. This typically indicates the rate was "
                            "applied to a pre-discount or post-freight base different from the printed "
                            "subtotal, or the rate label was updated without recalculating the amount."
                        ),
                        expected=expected,
                        actual=tax.amount,
                        currency=currency,
                        citations=[tax.citation],
                        evidence=[
                            f"Taxable base = {format_money(base, currency)}",
                            f"Rate = {percent['value']}%",
                            f"Stated tax = {format_money(tax.amount, currency)}",
                        ],
                    )
                )
    return findings


# --------------------------------------------------------------------------
# Fact-level (narrative) checks
# --------------------------------------------------------------------------

def _by_label(facts: list[Fact], *keywords: str) -> list[Fact]:
    return [
        f
        for f in facts
        if f.numeric_value is not None
        and any(k in f.label.lower() for k in keywords)
    ]


def check_profit_identity(facts: list[Fact]) -> list[Finding]:
    """revenue - expenses == profit / net income."""
    revenue = _by_label(facts, "revenue", "turnover", "sales")
    expenses = _by_label(facts, "expense", "cost", "opex")
    profit = _by_label(facts, "profit", "net income", "earnings")
    if not (revenue and expenses and profit):
        return []

    rev, exp, prof = revenue[0], expenses[0], profit[0]
    expected = rev.numeric_value - exp.numeric_value
    actual = prof.numeric_value
    if close_enough(expected, actual, max(settings.arithmetic_tolerance, abs(expected) * 0.001)):
        return []

    currency = rev.normalized_value.get("currency")
    return [
        _finding(
            finding_type="profit_identity_violation",
            title="Reported profit is not consistent with reported revenue and expenses",
            explanation=(
                "Profit is an identity, not an independent figure: it must equal revenue minus total "
                f"expenses. The document reports revenue of {format_money(rev.numeric_value, currency)} "
                f"and expenses of {format_money(exp.numeric_value, currency)}, which implies profit of "
                f"{format_money(expected, currency)}, yet it states {format_money(actual, currency)}. "
                "The most common causes are an expense category omitted from the narrative (for example "
                "tax or depreciation stated elsewhere), a figure quoted in a different period, or a "
                "revised revenue number that was not carried through to the profit line."
            ),
            expected=expected,
            actual=actual,
            currency=currency,
            citations=[c for c in (rev.citation, exp.citation, prof.citation) if c],
            evidence=[
                f"Revenue: {rev.raw_value}",
                f"Expenses: {exp.raw_value}",
                f"Stated profit: {prof.raw_value}",
            ],
            fact_ids=[rev.id, exp.id, prof.id],
        )
    ]


def check_margin_consistency(facts: list[Fact]) -> list[Finding]:
    """A stated margin % must match profit / revenue."""
    revenue = _by_label(facts, "revenue", "turnover", "sales")
    profit = _by_label(facts, "profit", "net income")
    margins = [f for f in facts if f.fact_type == FactType.PERCENTAGE and "margin" in f.label.lower()]
    if not (revenue and profit and margins):
        return []

    rev, prof, margin = revenue[0], profit[0], margins[0]
    if not rev.numeric_value:
        return []
    expected = prof.numeric_value / rev.numeric_value * 100
    actual = margin.numeric_value
    if actual is None or abs(expected - actual) <= 0.1:
        return []

    return [
        Finding(
            category=FindingCategory.NUMERIC,
            finding_type="margin_mismatch",
            severity=_severity_for(_relative(expected, actual)),
            confidence=0.9,
            title="Stated margin does not follow from the reported profit and revenue",
            explanation=(
                f"Margin is defined as profit divided by revenue. With profit of "
                f"{format_money(prof.numeric_value)} against revenue of {format_money(rev.numeric_value)}, "
                f"the implied margin is {expected:.2f}%, but the document states {actual:.2f}%. A gap here "
                "usually means the margin was computed on a different profit measure (gross versus net) "
                "or against a prior-period revenue base."
            ),
            expected_value=f"{expected:.2f}%",
            actual_value=f"{actual:.2f}%",
            difference=f"{actual - expected:+.2f} percentage points",
            suggested_correction=f"Restate the margin as {expected:.2f}% or clarify which profit measure it refers to.",
            evidence=[rev.raw_value, prof.raw_value, margin.raw_value],
            citations=[c for c in (rev.citation, prof.citation, margin.citation) if c],
            related_fact_ids=[rev.id, prof.id, margin.id],
        )
    ]


def check_repeated_values(facts: list[Fact]) -> list[Finding]:
    """The same named quantity stated twice with different numbers."""
    buckets: dict[str, list[Fact]] = defaultdict(list)
    for fact in facts:
        if fact.numeric_value is None or not fact.label:
            continue
        buckets[fact.label.lower().strip()].append(fact)

    findings: list[Finding] = []
    for label, group in buckets.items():
        values = {round(f.numeric_value, 2) for f in group}
        if len(group) < 2 or len(values) < 2:
            continue
        ordered = sorted(group, key=lambda f: (f.page or 0, f.char_start or 0))
        first, second = ordered[0], ordered[-1]
        findings.append(
            Finding(
                category=FindingCategory.NUMERIC,
                finding_type="repeated_value_conflict",
                severity=_severity_for(_relative(first.numeric_value or 1, second.numeric_value or 0)),
                confidence=0.8,
                title=f"'{label}' is stated with two different values",
                explanation=(
                    f"The quantity '{label}' appears {len(group)} times in this document with "
                    f"{len(values)} different values: {', '.join(format_money(v) for v in sorted(values))}. "
                    "Repeated quantities are expected to agree; a divergence normally means one occurrence "
                    "was updated during revision while the others were left stale, or the same label is "
                    "being used for two different scopes (for example a per-unit and a total figure)."
                ),
                expected_value=format_money(first.numeric_value),
                actual_value=format_money(second.numeric_value),
                difference=format_money((second.numeric_value or 0) - (first.numeric_value or 0)),
                suggested_correction="Confirm which occurrence is authoritative and align the others, or disambiguate the labels.",
                evidence=[f"{f.raw_value} ({f.citation.locator if f.citation else 'document'})" for f in ordered],
                citations=[f.citation for f in ordered if f.citation],
                related_fact_ids=[f.id for f in group],
            )
        )
    return findings


def check_percentage_bounds(facts: list[Fact]) -> list[Finding]:
    findings: list[Finding] = []
    for fact in facts:
        if fact.fact_type != FactType.PERCENTAGE:
            continue
        value = fact.numeric_value
        if value is None or -100 <= value <= 100:
            continue
        findings.append(
            Finding(
                category=FindingCategory.NUMERIC,
                finding_type="percentage_out_of_range",
                severity=Severity.MEDIUM,
                confidence=0.7,
                title=f"Percentage outside the plausible range: {fact.raw_value}",
                explanation=(
                    f"'{fact.label or fact.raw_value}' is expressed as {value}%. Shares, rates and margins "
                    "are bounded by 100% unless the figure is a growth multiple. Values beyond that bound "
                    "usually come from a decimal-shift typo or from a growth rate mislabelled as a share."
                ),
                expected_value="between -100% and 100%",
                actual_value=f"{value}%",
                suggested_correction="Verify the decimal placement, or relabel the figure as a growth rate.",
                evidence=[fact.raw_value],
                citations=[fact.citation] if fact.citation else [],
                related_fact_ids=[fact.id],
            )
        )
    return findings


def check_currency_consistency(facts: list[Fact]) -> list[Finding]:
    currencies = {
        f.normalized_value.get("currency")
        for f in facts
        if f.fact_type == FactType.CURRENCY and f.normalized_value.get("currency") not in (None, "UNKNOWN")
    }
    if len(currencies) < 2:
        return []
    samples = [f for f in facts if f.fact_type == FactType.CURRENCY][:8]
    return [
        Finding(
            category=FindingCategory.NUMERIC,
            finding_type="mixed_currency",
            severity=Severity.HIGH,
            confidence=0.85,
            title=f"Document mixes {len(currencies)} currencies: {', '.join(sorted(currencies))}",
            explanation=(
                "Monetary amounts in a single financial document are expected to share one presentation "
                f"currency, or to state a conversion basis. This document uses {', '.join(sorted(currencies))} "
                "without a stated exchange rate, which makes every total that combines them arithmetically "
                "undefined and is a frequent source of overstated or understated balances."
            ),
            expected_value="a single presentation currency, or an explicit FX basis",
            actual_value=", ".join(sorted(currencies)),
            suggested_correction="State the presentation currency and the exchange rate used for converted amounts.",
            evidence=[f.raw_value for f in samples],
            citations=[f.citation for f in samples if f.citation],
            related_fact_ids=[f.id for f in samples],
        )
    ]


CHECKS: tuple[Callable[[list[Fact]], list[Finding]], ...] = (
    check_profit_identity,
    check_margin_consistency,
    check_repeated_values,
    check_percentage_bounds,
    check_currency_consistency,
)


class ArithmeticEngine:
    """Composes every registered check. Stateless and dependency-free, so it
    can be exercised in tests without a database or an LLM."""

    def __init__(self, checks: Iterable[Callable[[list[Fact]], list[Finding]]] = CHECKS) -> None:
        self._checks = tuple(checks)

    def run(self, facts: list[Fact], tables: list[Table] | None = None, document_id=None) -> list[Finding]:
        findings: list[Finding] = []
        for check in self._checks:
            findings.extend(check(facts))
        if tables:
            findings.extend(check_table_totals(tables, document_id))
        for finding in findings:
            finding.document_id = finding.document_id or document_id
        return findings
