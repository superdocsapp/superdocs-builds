"""Loan-file vertical: a mini-app for one industry (lending) on the SuperDocs surface.

Takes a borrower's loan file — sanction letter, disbursement advice, salary slip, EMI
schedule — and produces a grounded decision memo: does disbursal exceed sanction, and is
the EMI affordable against income. Classification + rules are the vertical's data.
"""
from __future__ import annotations
import re

AMOUNT_RE = re.compile(r"(?:₹\s*|(?<![a-z])rs\.?\s+|(?<![a-z])inr\.?\s+)([\d][\d,]*)", re.I)

# what each document contributes (the vertical's schema, as data)
KIND = {"sanction": "sanctioned", "disbursement": "disbursed", "disburse": "disbursed",
        "salary": "monthly_income", "payslip": "monthly_income", "emi": "emi"}


def classify(name: str) -> str:
    n = name.lower()
    for kw, kind in KIND.items():
        if kw in n:
            return kind
    return "other"


def _amount(text: str):
    m = AMOUNT_RE.search(text)
    if not m:
        return None
    d = m.group(1).replace(",", "")
    return int(d) if d.isdigit() else None


def analyze(docs: dict[str, str]) -> dict:
    """docs = {filename: text}. Returns grounded facts, findings, and a decision."""
    facts: dict[str, tuple[int, str]] = {}
    for name, text in docs.items():
        kind, amt = classify(name), _amount(text)
        if kind != "other" and amt is not None:
            facts[kind] = (amt, name)

    findings = []
    s, d = facts.get("sanctioned"), facts.get("disbursed")
    inc, emi = facts.get("monthly_income"), facts.get("emi")
    if s and d and d[0] > s[0]:
        findings.append({"rule": "disbursed_not_exceed_sanctioned",
                         "message": f"Disbursed {d[0]} exceeds the sanctioned amount {s[0]}",
                         "citations": [d[1], s[1]]})
    if inc and emi and emi[0] > 0.5 * inc[0]:
        findings.append({"rule": "emi_affordability",
                         "message": f"EMI {emi[0]} is over 50% of monthly income {inc[0]}",
                         "citations": [emi[1], inc[1]]})
    return {
        "facts": {k: v[0] for k, v in facts.items()},
        "sources": {k: v[1] for k, v in facts.items()},
        "findings": findings,
        "decision": "refer" if findings else "clear",
    }
