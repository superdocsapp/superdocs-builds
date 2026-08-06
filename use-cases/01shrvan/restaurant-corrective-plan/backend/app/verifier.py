from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from .models import CodeCoverage, CorrectivePlan, CoverageReport, Violation


_BOILERPLATE_PATTERNS = (
    re.compile(r"\b(correct|corrective|address|resolve)\s+(the\s+)?violation\b", re.I),
    re.compile(r"\b(per|according to|in accordance with)\s+(code|requirements?)\b", re.I),
    re.compile(r"\b(code|food code)\s+requirements?\b", re.I),
)


def verify_coverage(
    violations: tuple[Violation, ...] | list[Violation],
    plan: CorrectivePlan,
) -> CoverageReport:
    items_by_code = {item.code: item for item in plan.items}
    action_counts = Counter(_fingerprint(item.corrective_action) for item in plan.items)
    owner_counts = Counter(_fingerprint(item.responsible_party) for item in plan.items)

    code_reports: list[CodeCoverage] = []
    for violation in violations:
        item = items_by_code.get(violation.code)
        reasons: list[str] = []
        if item is None:
            code_reports.append(
                CodeCoverage(
                    code=violation.code,
                    status="incomplete",
                    reasons=("code not present in corrective plan",),
                )
            )
            continue

        action = item.corrective_action.strip()
        owner = item.responsible_party.strip()
        finding = item.finding.strip()

        if _fingerprint(action) == _fingerprint(finding):
            reasons.append("corrective action repeats the finding instead of stating a fix")
        if action_counts[_fingerprint(action)] > 1:
            reasons.append("corrective action is copied from another violation")
        if owner_counts[_fingerprint(owner)] > 1:
            reasons.append("responsible party is copied from another violation")
        if _is_boilerplate(action, violation):
            reasons.append("corrective action is boilerplate and not specific to the violation")
        if _near_duplicate_action(action, item.code, plan):
            reasons.append("corrective action is near-identical to another violation")

        code_reports.append(
            CodeCoverage(
                code=violation.code,
                status="incomplete" if reasons else "covered",
                reasons=tuple(reasons),
            )
        )

    return CoverageReport(codes=tuple(code_reports))


def _fingerprint(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _without_code(value: str, code: str) -> str:
    return _fingerprint(value.replace(code, " "))


def _is_boilerplate(action: str, violation: Violation) -> bool:
    normalized = _without_code(action, violation.code)
    has_boilerplate = sum(1 for pattern in _BOILERPLATE_PATTERNS if pattern.search(normalized)) >= 2
    has_domain_detail = any(
        word in normalized
        for word in _meaningful_terms(violation.description, violation.location)
    )
    return has_boilerplate and not has_domain_detail


def _near_duplicate_action(action: str, code: str, plan: CorrectivePlan) -> bool:
    candidate = _without_code(action, code)
    for other in plan.items:
        if other.code == code:
            continue
        other_action = _without_code(other.corrective_action, other.code)
        if SequenceMatcher(None, candidate, other_action).ratio() >= 0.82:
            return True
    return False


def _meaningful_terms(description: str, location: str | None) -> set[str]:
    text = f"{description} {location or ''}".lower()
    words = {
        word
        for word in re.findall(r"[a-z][a-z0-9-]{3,}", text)
        if word
        not in {
            "area",
            "code",
            "with",
            "that",
            "this",
            "from",
            "requirement",
            "requirements",
            "minimum",
            "violation",
            "violations",
            "supplied",
        }
    }
    return words

