from __future__ import annotations

from uuid import uuid4

from app.engines.dates import run_date_checks
from app.schemas.domain import Citation, Fact, FactType


def date_fact(label: str, iso: str, *, raw: str | None = None, ambiguous: bool = False) -> Fact:
    return Fact(
        document_id=uuid4(),
        fact_type=FactType.DATE,
        label=label,
        raw_value=raw or iso,
        normalized_value={"iso_date": iso, "ambiguous": ambiguous},
        citation=Citation(page=1, quote=raw or iso),
    )


def types(findings) -> set[str]:
    return {f.finding_type for f in findings}


def test_reversed_range_is_critical():
    findings = run_date_checks(
        [date_fact("Start Date", "2025-06-01"), date_fact("End Date", "2025-01-01")]
    )
    reversed_findings = [f for f in findings if f.finding_type == "reversed_date_range"]
    assert reversed_findings
    assert reversed_findings[0].severity == "critical"
    assert "backwards" in reversed_findings[0].explanation


def test_valid_range_produces_no_reversal():
    findings = run_date_checks(
        [date_fact("Start Date", "2025-01-01"), date_fact("End Date", "2025-06-01")]
    )
    assert "reversed_date_range" not in types(findings)


def test_deadline_outside_period():
    findings = run_date_checks(
        [
            date_fact("Effective Date", "2025-01-01"),
            date_fact("Expiry Date", "2025-06-30"),
            date_fact("Delivery deadline", "2025-09-15"),
        ]
    )
    hits = [f for f in findings if f.finding_type == "deadline_outside_period"]
    assert hits and "after the period ends" in hits[0].explanation


def test_conflicting_duplicate_dates():
    findings = run_date_checks(
        [date_fact("Signature Date", "2025-03-01"), date_fact("Signature date", "2025-03-14")]
    )
    hits = [f for f in findings if f.finding_type == "conflicting_date_values"]
    assert hits and "13 day spread" in hits[0].difference


def test_ambiguous_format_flagged_not_resolved():
    findings = run_date_checks([date_fact("Issue Date", "2025-04-03", raw="03/04/2025", ambiguous=True)])
    hits = [f for f in findings if f.finding_type == "ambiguous_date_format"]
    assert hits and hits[0].severity == "low"


def test_implausible_year():
    findings = run_date_checks([date_fact("Signature Date", "1725-01-01")])
    assert "implausible_date" in types(findings)


def test_no_dates_no_findings():
    assert run_date_checks([]) == []
