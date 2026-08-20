"""Date consistency engine.

Detects timeline defects that deterministic logic can prove: reversed ranges,
deadlines that fall outside their governing period, duplicates of the same
labelled date with different values, impossible/implausible calendar values and
ambiguous locale-dependent formats.

Every check is a registered function so a new temporal rule ("renewal must be
>= 30 days before expiry") is one function plus one registry entry.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app.schemas.domain import (
    Citation,
    Fact,
    FactType,
    Finding,
    FindingCategory,
    Severity,
)

# Label vocabulary. Configuration, not code: extend to teach the engine new
# roles without touching any check.
ROLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "start": re.compile(r"\b(start\w*|commenc\w*|effective|from|begin\w*|issue\w*|invoice)\b", re.I),
    "end": re.compile(r"\b(end\w*|expir\w*|terminat\w*|until|to date|valid till|due)\b", re.I),
    "deadline": re.compile(r"\b(deadline|due|deliver\w*|milestone|submission|payment)\b", re.I),
    "signature": re.compile(r"\b(sign\w*|execut\w*)\b", re.I),
}

MAX_PLAUSIBLE_YEARS_AHEAD = 50
MIN_PLAUSIBLE_YEAR = 1900


@dataclass(slots=True)
class DatePoint:
    label: str
    value: date
    raw: str
    ambiguous: bool
    citation: Citation
    fact_id: object = None

    def role(self) -> str | None:
        for role, pattern in ROLE_PATTERNS.items():
            if pattern.search(self.label) or pattern.search(self.raw):
                return role
        return None


def _citation_of(fact: Fact) -> Citation:
    return fact.citation or Citation(
        document_id=fact.document_id,
        page=fact.page,
        section=fact.section,
        paragraph=fact.paragraph,
        quote=fact.raw_value,
    )


def collect_date_points(facts: list[Fact]) -> list[DatePoint]:
    points: list[DatePoint] = []
    for fact in facts:
        if fact.fact_type not in (FactType.DATE, FactType.DEADLINE):
            continue
        value = fact.date_value
        if value is None:
            continue
        points.append(
            DatePoint(
                label=fact.label or fact.raw_value,
                value=value,
                raw=fact.raw_value,
                ambiguous=bool(fact.normalized_value.get("ambiguous")),
                citation=_citation_of(fact),
                fact_id=fact.id,
            )
        )
    return points


def _finding(
    *,
    finding_type: str,
    title: str,
    explanation: str,
    severity: Severity,
    confidence: float,
    points: list[DatePoint],
    expected: str | None = None,
    actual: str | None = None,
    difference: str | None = None,
    suggestion: str | None = None,
) -> Finding:
    return Finding(
        category=FindingCategory.DATE,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        title=title,
        explanation=explanation,
        expected_value=expected,
        actual_value=actual,
        difference=difference,
        suggested_correction=suggestion,
        evidence=[f"{p.label}: {p.raw} → {p.value.isoformat()} ({p.citation.locator})" for p in points],
        citations=[p.citation for p in points],
        related_fact_ids=[p.fact_id for p in points if p.fact_id is not None],
    )


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_reversed_ranges(points: list[DatePoint]) -> list[Finding]:
    """A period whose end precedes its start is always an error."""
    starts = [p for p in points if p.role() == "start"]
    ends = [p for p in points if p.role() == "end"]
    findings: list[Finding] = []
    for start in starts:
        for end in ends:
            if end.value >= start.value:
                continue
            gap = (start.value - end.value).days
            findings.append(
                _finding(
                    finding_type="reversed_date_range",
                    title=f"End date precedes start date ({end.raw} before {start.raw})",
                    explanation=(
                        f"'{start.label}' is {start.value.isoformat()} while '{end.label}' is "
                        f"{end.value.isoformat()}, so the period closes {gap} day(s) before it opens. "
                        "A term cannot run backwards, so one of the two dates is transcribed wrong."
                    ),
                    severity=Severity.CRITICAL,
                    confidence=0.97,
                    points=[start, end],
                    expected=f"end ≥ {start.value.isoformat()}",
                    actual=end.value.isoformat(),
                    difference=f"-{gap} days",
                    suggestion=(
                        f"Confirm whether '{end.label}' should be after {start.value.isoformat()} "
                        f"or whether '{start.label}' was mistyped."
                    ),
                )
            )
    return findings


def check_deadlines_outside_period(points: list[DatePoint]) -> list[Finding]:
    """Deliverable deadlines must sit inside the governing contract window."""
    starts = [p for p in points if p.role() == "start"]
    ends = [p for p in points if p.role() == "end"]
    if not starts or not ends:
        return []
    window_start = min(p.value for p in starts)
    window_end = max(p.value for p in ends)
    if window_end < window_start:
        return []  # already reported as a reversed range

    findings: list[Finding] = []
    for point in points:
        if point.role() != "deadline":
            continue
        if window_start <= point.value <= window_end:
            continue
        drift = (
            (point.value - window_end).days
            if point.value > window_end
            else (window_start - point.value).days
        )
        side = "after the period ends" if point.value > window_end else "before the period starts"
        findings.append(
            _finding(
                finding_type="deadline_outside_period",
                title=f"Deadline '{point.label}' falls {side}",
                explanation=(
                    f"The governing period runs {window_start.isoformat()} → {window_end.isoformat()}, "
                    f"but '{point.label}' is scheduled for {point.value.isoformat()} — {drift} day(s) "
                    f"{side}. Obligations outside the term are unenforceable as written."
                ),
                severity=Severity.HIGH,
                confidence=0.9,
                points=[point],
                expected=f"{window_start.isoformat()} … {window_end.isoformat()}",
                actual=point.value.isoformat(),
                difference=f"{drift} days {side}",
                suggestion="Move the deadline inside the term or extend the term to cover it.",
            )
        )
    return findings


def check_conflicting_duplicates(points: list[DatePoint]) -> list[Finding]:
    """The same labelled date stated twice with different values."""
    buckets: dict[str, list[DatePoint]] = defaultdict(list)
    for point in points:
        key = re.sub(r"[^a-z0-9]+", " ", point.label.lower()).strip()
        if key:
            buckets[key].append(point)

    findings: list[Finding] = []
    for key, group in buckets.items():
        distinct = {p.value for p in group}
        if len(distinct) < 2:
            continue
        ordered = sorted(distinct)
        spread = (ordered[-1] - ordered[0]).days
        findings.append(
            _finding(
                finding_type="conflicting_date_values",
                title=f"'{key}' is stated with {len(distinct)} different dates",
                explanation=(
                    f"The same field is given as {', '.join(d.isoformat() for d in ordered)} in "
                    f"different places ({spread} day spread). Downstream systems will disagree "
                    "depending on which occurrence they read."
                ),
                severity=Severity.HIGH if spread > 1 else Severity.MEDIUM,
                confidence=0.92,
                points=group,
                expected="a single consistent value",
                actual=", ".join(d.isoformat() for d in ordered),
                difference=f"{spread} day spread",
                suggestion="Pick the authoritative occurrence and align every other mention.",
            )
        )
    return findings


def check_implausible_dates(points: list[DatePoint]) -> list[Finding]:
    """Calendar values that are legal but almost certainly typos."""
    today = date.today()
    horizon = today + timedelta(days=365 * MAX_PLAUSIBLE_YEARS_AHEAD)
    findings: list[Finding] = []
    for point in points:
        if MIN_PLAUSIBLE_YEAR <= point.value.year and point.value <= horizon:
            continue
        findings.append(
            _finding(
                finding_type="implausible_date",
                title=f"Implausible date {point.value.isoformat()} for '{point.label}'",
                explanation=(
                    f"'{point.raw}' parses to {point.value.isoformat()}, outside the plausible range "
                    f"{MIN_PLAUSIBLE_YEAR}–{horizon.year}. This is usually a mistyped or "
                    "misrecognised year rather than a genuine value."
                ),
                severity=Severity.MEDIUM,
                confidence=0.8,
                points=[point],
                expected=f"{MIN_PLAUSIBLE_YEAR} … {horizon.year}",
                actual=point.value.isoformat(),
                suggestion="Verify the year against the source document.",
            )
        )
    return findings


def check_ambiguous_formats(points: list[DatePoint]) -> list[Finding]:
    """Locale-ambiguous numeric dates: flagged, never silently resolved."""
    findings: list[Finding] = []
    for point in points:
        if not point.ambiguous:
            continue
        findings.append(
            _finding(
                finding_type="ambiguous_date_format",
                title=f"Ambiguous date format '{point.raw}'",
                explanation=(
                    f"'{point.raw}' is valid under both day-first and month-first reading. It was "
                    f"interpreted as {point.value.isoformat()}, but the alternative reading is a "
                    "different real date. The interpretation is recorded rather than assumed correct."
                ),
                severity=Severity.LOW,
                confidence=0.75,
                points=[point],
                expected="an unambiguous format (YYYY-MM-DD)",
                actual=point.raw,
                suggestion=f"Restate as {point.value.isoformat()} once the intent is confirmed.",
            )
        )
    return findings


CHECKS: dict[str, Callable[[list[DatePoint]], list[Finding]]] = {
    "reversed_ranges": check_reversed_ranges,
    "deadlines_outside_period": check_deadlines_outside_period,
    "conflicting_duplicates": check_conflicting_duplicates,
    "implausible_dates": check_implausible_dates,
    "ambiguous_formats": check_ambiguous_formats,
}


def run_date_checks(facts: list[Fact], *, enabled: set[str] | None = None) -> list[Finding]:
    """Run every registered temporal check over the extracted date facts."""
    points = collect_date_points(facts)
    if not points:
        return []
    findings: list[Finding] = []
    for name, check in CHECKS.items():
        if enabled is not None and name not in enabled:
            continue
        findings.extend(check(points))
    return findings
