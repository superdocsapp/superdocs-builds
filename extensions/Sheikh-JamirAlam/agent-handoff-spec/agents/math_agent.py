from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
import re

from schema import HandoffEnvelope, ReviewState, validate_envelope

from .spelling_agent import DocumentState
from .llm import DiffModel


@dataclass(frozen=True)
class MathCheckResult:
    document_id: str
    calculated_total: Decimal
    changed_sections: dict[str, tuple[str, str]]
    next_envelope: HandoffEnvelope


class MathCheckAgent:
    agent_id = "math-check-agent"
    action_name = "verify totals"
    line_item = re.compile(
        r"(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<unit>\d+(?:\.\d+)?)\s*=\s*"
        r"(?P<amount>\d+(?:\.\d+)?)"
    )
    total = re.compile(
        r"(?P<label>\bTotal\s*:\s*)(?P<amount>\d+(?:\.\d+)?)", re.IGNORECASE)

    def __init__(self, llm: DiffModel | None = None,
                 pricing_section: str = "pricing_table",
                 next_section: str = "pricing_table") -> None:
        self.llm = llm
        self.pricing_section = pricing_section
        self.next_section = next_section

    def next_envelope(self, document: DocumentState) -> HandoffEnvelope:
        return HandoffEnvelope(
            document_id=document.document_id,
            assigned_to="spelling-agent",
            scope={"action": "final spelling review",
                   "target_sections": [self.next_section]},
            restrictions={"forbidden_sections": [
                "narrative", "dialogue"], "forbidden_actions": ["edit spelling", "rewrite prose"]},
            review_state=ReviewState.PENDING_REVIEW,
            issued_by="math-check-agent",
            issued_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def money(value: str) -> Decimal:
        return Decimal(re.sub(r"[^0-9.-]", "", value))

    def check_invoice_table(self, before: str) -> tuple[Decimal, str]:
        lines = [line.strip() for line in before.splitlines() if "|" in line]
        if not lines:
            raise ValueError(
                f"{self.pricing_section} contains no parseable table")
        headers = [cell.strip().lower() for cell in lines[0].split("|")]
        required = {"qty", "unit rate", "amount (usd)"}
        if not required.issubset(headers):
            raise ValueError(
                f"{self.pricing_section} table is missing required columns")
        qty_i, rate_i, amount_i = (headers.index("qty"), headers.index(
            "unit rate"), headers.index("amount (usd)"))
        total = Decimal("0")
        corrected = before
        for line in lines[1:]:
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) <= amount_i or not cells[qty_i] or not re.search(r"\d", cells[qty_i]):
                continue
            expected = Decimal(cells[qty_i]) * self.money(cells[rate_i])
            total += expected
            reported = self.money(cells[amount_i])
            if reported != expected:
                replacement = format(expected, ".2f")
                old_line = line
                cells[amount_i] = replacement
                corrected = corrected.replace(old_line, " | ".join(cells))
        total_match = re.search(
            r"(?im)^(?:.*\|\s*)?(?:total due)\s*\|\s*([$\d,.-]+)", before)
        if total_match is None:
            raise ValueError(f"{self.pricing_section} table has no TOTAL DUE")
        if self.money(total_match.group(1)) != total:
            corrected = corrected[:total_match.start(
                1)] + format(total, ".2f") + corrected[total_match.end(1):]
        return total, corrected

    def checkline_items(self, before: str) -> tuple[Decimal, str]:
        matches = list(self.line_item.finditer(before))
        if not matches:
            raise ValueError(
                f"{self.pricing_section} contains no parseable line items")
        total = Decimal("0")
        corrected = before
        for match in reversed(matches):
            expected = Decimal(match["qty"]) * Decimal(match["unit"])
            total += expected
            if Decimal(match["amount"]) != expected:
                corrected = (
                    corrected[:match.start("amount")]
                    + format(expected, "f")
                    + corrected[match.end("amount"):]
                )
        total_match = self.total.search(corrected)
        if total_match is None:
            raise ValueError(f"{self.pricing_section} contains no Total value")
        if Decimal(total_match["amount"]) != total:
            corrected = (
                corrected[:total_match.start("amount")]
                + format(total, "f")
                + corrected[total_match.end("amount"):]
            )
        return total, corrected

    def check_pricing(self, before: str) -> tuple[Decimal, str]:
        if "amount (usd)" in before.lower() and "|" in before:
            return self.check_invoice_table(before)
        return self.checkline_items(before)

    def process(self, raw_envelope: dict, document: DocumentState) -> MathCheckResult:
        envelope = validate_envelope(raw_envelope)
        self.validate_document(envelope, document)
        if envelope.assigned_to != self.agent_id:
            raise ValueError(
                f"envelope is assigned to {envelope.assigned_to}, not {self.agent_id}")
        if envelope.scope.target_sections != [self.pricing_section]:
            raise ValueError(
                f"math-check agent requires {self.pricing_section} as its only target")

        before = document.sections[self.pricing_section]
        is_table = "amount (usd)" in before.lower() and "|" in before
        if self.llm is not None:
            proposal = self.llm.propose(
                action=envelope.scope.action,
                sections={self.pricing_section: before},
                restrictions=envelope.restrictions.forbidden_actions,
            )
            changed_sections = {
                change.section: (change.before, change.after)
                for change in proposal.changes
            }
            if os.getenv("SUPERDOCS_VERBOSE", "").lower() in {"1", "true", "yes", "on"}:
                print(f"[MathAgent] model changes={len(changed_sections)}")
                for section, (change_before, change_after) in changed_sections.items():
                    print(
                        f"[MathAgent] section={section!r} before={change_before!r}")
                    print(
                        f"[MathAgent] section={section!r} after={change_after!r}")
            if any(section != self.pricing_section for section in changed_sections):
                raise ValueError(
                    f"LLM proposed math change outside {self.pricing_section}")
            after = changed_sections.get(
                self.pricing_section, (before, before))[1]
            calculated_total, verified_after = self.check_pricing(before)
            if after == before:
                after = verified_after
        else:
            calculated_total, after = self.check_pricing(before)

        changed_sections = {} if after == before else {
            self.pricing_section: (before, after)}
        return MathCheckResult(
            document.document_id,
            calculated_total,
            changed_sections,
            self.next_envelope(document),
        )

    @staticmethod
    def validate_document(envelope: HandoffEnvelope, document: DocumentState) -> None:
        if envelope.document_id != document.document_id:
            raise ValueError("stale or mismatched document")
        if document.review_state != envelope.review_state:
            raise ValueError(
                f"document review state is {document.review_state.value}, "
                f"envelope says {envelope.review_state.value}"
            )
