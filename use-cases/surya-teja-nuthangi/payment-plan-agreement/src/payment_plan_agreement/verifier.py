from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from html.parser import HTMLParser

from pydantic import BaseModel, Field

from .models import LateFeeKind, PaymentPlan, ProposedChange


class FindingSeverity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class DocumentLocation(BaseModel):
    section: str | None = None
    table_row: int | None = None
    table_column: str | None = None
    excerpt: str | None = None


class VerificationFinding(BaseModel):
    code: str
    severity: FindingSeverity
    message: str
    expected: str | None = None
    observed: str | None = None
    location: DocumentLocation | None = None
    canonical_fact_keys: list[str] = Field(default_factory=list)
    remediation: str | None = None


class VerificationReport(BaseModel):
    status: str
    checks_run: list[str]
    findings: list[VerificationFinding]
    canonical_fingerprint: str
    document_hash: str
    verifier_version: str = "1.0.0"


@dataclass
class ParsedDocument:
    sections: dict[str, str] = field(default_factory=dict)
    rows: list[list[str]] = field(default_factory=list)
    current_section: str | None = None
    in_schedule: bool = False
    in_row: bool = False
    cell: list[str] | None = None
    row: list[str] | None = None


class _AgreementParser(HTMLParser):
    CHUNK_SECTIONS = {
        "parties": "parties",
        "amounts": "amounts",
        "schedule": "payment-schedule",
        "payment-terms": "payment-terms",
        "late-fee": "late-fee",
        "signatures": "signatures",
        "general": "general",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = ParsedDocument()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        section = data.get("data-agreement-section")
        if tag == "section" and not section:
            section = self.CHUNK_SECTIONS.get(data.get("data-chunk-id") or "")
        if tag == "section" and section:
            self.result.current_section = section
            self.result.sections.setdefault(self.result.current_section, "")
        if tag == "table" and (data.get("data-payment-schedule") == "v1" or self.result.current_section == "payment-schedule"): self.result.in_schedule = True
        if self.result.in_schedule and tag == "tr": self.result.in_row, self.result.row = True, []
        if self.result.in_row and tag in ("td", "th"): self.result.cell = []

    def handle_data(self, data: str) -> None:
        if self.result.current_section: self.result.sections[self.result.current_section] += data + " "
        if self.result.cell is not None: self.result.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.result.cell is not None and self.result.row is not None:
            self.result.row.append(" ".join(self.result.cell).strip()); self.result.cell = None
        if tag == "tr" and self.result.in_row and self.result.row is not None:
            if self.result.row and self.result.row[0].strip().isdigit(): self.result.rows.append(self.result.row)
            self.result.in_row, self.result.row = False, None
        if tag == "table": self.result.in_schedule = False
        if tag == "section": self.result.current_section = None


def _amount(text: str) -> Decimal | None:
    match = re.search(r"[-+]?\d[\d,]*\.\d{2}", text)
    if not match: return None
    try: return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation: return None


def _date(text: str):
    text = text.strip()
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try: return datetime.strptime(text, pattern).date()
        except ValueError: pass
    return None


class AgreementVerifier:
    REQUIRED = [f"V{i:03d}" for i in range(1, 21)]

    def verify(self, plan: PaymentPlan, document_html: str, proposed_changes: list[ProposedChange] | None = None) -> VerificationReport:
        findings: list[VerificationFinding] = []
        parser = _AgreementParser()
        try: parser.feed(document_html); parsed = parser.result
        except Exception as exc:
            findings.append(self._finding("PARSE_FAILED", "Agreement HTML could not be parsed.", observed=str(exc)))
            parsed = ParsedDocument()
        required_sections = {"parties", "amounts", "payment-schedule", "payment-terms", "late-fee", "signatures"}
        missing = sorted(required_sections - parsed.sections.keys())
        if missing: findings.append(self._finding("V020", "Required agreement sections are missing.", expected=", ".join(sorted(required_sections)), observed=", ".join(sorted(parsed.sections))))
        if not parsed.rows:
            findings.append(self._finding("SCHEDULE_TABLE_NOT_FOUND", "Payment schedule table is absent or unreadable."))
        if len(parsed.rows) != len(plan.installments): findings.append(self._finding("V001", "Schedule row count does not match.", str(len(plan.installments)), str(len(parsed.rows)), "payment-schedule"))
        for index, expected in enumerate(plan.installments):
            if index >= len(parsed.rows): break
            row = parsed.rows[index]
            if len(row) < 3:
                findings.append(self._finding("PARSE_FAILED", "Schedule row has too few cells.", location="payment-schedule")); continue
            observed_date = _date(row[1]); observed_amount = _amount(row[2])
            if observed_date != expected.due_date: findings.append(self._finding("V002", f"Payment Schedule row {index+1} due date differs.", str(expected.due_date), str(observed_date), "payment-schedule", index+1, "Due date"))
            if observed_amount != expected.amount: findings.append(self._finding("V003", f"Payment Schedule row {index+1} amount differs.", str(expected.amount), str(observed_amount), "payment-schedule", index+1, "Amount"))
            if len(row) >= 4 and _amount(row[3]) != expected.balance_after: findings.append(self._finding("V005", f"Payment Schedule row {index+1} running balance differs.", str(expected.balance_after), str(_amount(row[3])), "payment-schedule", index+1, "Balance after"))
        observed_total = sum((_amount(r[2]) or Decimal(0) for r in parsed.rows if len(r) >= 3), Decimal(0))
        if observed_total != plan.financed_balance: findings.append(self._finding("V004", "Schedule total differs from financed balance.", str(plan.financed_balance), str(observed_total), "payment-schedule"))
        all_text = " ".join(parsed.sections.values())
        terms = parsed.sections.get("payment-terms", "")
        amounts = parsed.sections.get("amounts", "")
        late = parsed.sections.get("late-fee", "")
        if plan.creditor.legal_name not in parsed.sections.get("parties", "") or plan.debtor.legal_name not in parsed.sections.get("parties", ""): findings.append(self._finding("V015", "Party identity is missing or changed."))
        if str(len(plan.installments)) not in terms: findings.append(self._finding("V008", "Installment count is absent or differs in payment prose.", str(len(plan.installments)), terms, "payment-terms"))
        if plan.terms.frequency.value not in terms.lower(): findings.append(self._finding("V009", "Payment frequency is absent or differs in prose.", plan.terms.frequency.value, terms, "payment-terms"))
        if f"{plan.installments[0].due_date:%B %d, %Y}" not in terms: findings.append(self._finding("V010", "First due date is absent or differs in prose.", str(plan.installments[0].due_date), terms, "payment-terms"))
        if f"{plan.final_due_date:%B %d, %Y}" not in terms: findings.append(self._finding("V011", "Final due date is absent or differs in prose.", str(plan.final_due_date), terms, "payment-terms"))
        if str(plan.terms.original_balance.quantize(Decimal('.01'))) not in amounts.replace(",", ""): findings.append(self._finding("V007", "Original balance is absent or differs."))
        if str(plan.terms.upfront_payment.quantize(Decimal('.01'))) not in amounts.replace(",", ""): findings.append(self._finding("V006", "Upfront payment is absent or differs."))
        if len({x.amount for x in plan.installments}) > 1 and re.search(r"\bequal\b", terms, re.I): findings.append(self._finding("V012", "Unequal rounded installments are described as equal.", location="payment-terms"))
        if plan.terms.reference_id and plan.terms.reference_id not in all_text: findings.append(self._finding("V016", "Reference identifier is missing or changed."))
        fee = plan.terms.late_fee
        if fee.kind == LateFeeKind.NONE and re.search(r"(?:late|processing|returned payment) fee.{0,20}(?:[$€₹£]\s*\d|\d+(?:\.\d+)?%)", all_text, re.I): findings.append(self._finding("V017", "An unsupported monetary fee was invented."))
        if fee.kind == LateFeeKind.FIXED and str(fee.amount) not in late: findings.append(self._finding("V013", "Fixed late fee differs."))
        if fee.kind == LateFeeKind.PERCENT and str(fee.percent) not in late: findings.append(self._finding("V013", "Percentage late fee differs."))
        if fee.kind != LateFeeKind.NONE and str(fee.grace_days) not in late: findings.append(self._finding("V014", "Grace period differs."))
        for change in proposed_changes or []:
            if change.blocked: findings.append(self._finding("V019", f"Proposed change {change.change_id} is already blocked."))
        status = "blocked" if any(f.severity == FindingSeverity.BLOCKER for f in findings) else ("warning" if findings else "pass")
        return VerificationReport(status=status, checks_run=self.REQUIRED.copy(), findings=findings, canonical_fingerprint=plan.semantic_fingerprint, document_hash=hashlib.sha256(document_html.encode()).hexdigest())

    def classify_proposals(self, plan: PaymentPlan, document_html: str, proposals: list[ProposedChange]) -> list[ProposedChange]:
        """Mark a proposal blocked when its independently materialized candidate violates canonical facts."""
        classified: list[ProposedChange] = []
        for proposal in proposals:
            candidate = self._materialize(document_html, proposal)
            report = self.verify(plan, candidate)
            classified.append(proposal.model_copy(update={"blocked": report.status == "blocked"}))
        return classified

    @staticmethod
    def _materialize(document_html: str, proposal: ProposedChange) -> str:
        if proposal.operation == "create":
            return document_html.replace("</article>", (proposal.new_html or "") + "</article>")
        if proposal.old_html and proposal.old_html in document_html:
            return document_html.replace(proposal.old_html, proposal.new_html or "", 1)
        if not proposal.chunk_id:
            return document_html
        chunk = re.escape(proposal.chunk_id)
        pattern = re.compile(
            rf"<(?P<tag>[a-zA-Z][\w:-]*)\b(?=[^>]*\bdata-chunk-id=[\"']{chunk}[\"'])[^>]*>.*?</(?P=tag)>",
            re.DOTALL,
        )
        return pattern.sub(proposal.new_html or "", document_html, count=1)

    @staticmethod
    def _finding(code: str, message: str, expected: str | None = None, observed: str | None = None, location: str | None = None, row: int | None = None, column: str | None = None) -> VerificationFinding:
        return VerificationFinding(code=code, severity=FindingSeverity.BLOCKER, message=message, expected=expected, observed=observed, location=DocumentLocation(section=location, table_row=row, table_column=column) if location else None, remediation="Correct only this mismatch; preserve every other section and protected fact.")
