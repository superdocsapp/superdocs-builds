from __future__ import annotations

from pathlib import Path

from app.engines.arithmetic import ArithmeticEngine
from app.engines.dates import run_date_checks
from app.services.extraction import extract_deterministic
from app.services.parsing import parse_document


DEMO_DIR = Path(__file__).parents[1] / "demo_data"


def findings_for(filename: str):
    path = DEMO_DIR / filename
    parsed = parse_document(path.name, path.read_bytes())
    facts = extract_deterministic(parsed)
    return facts, ArithmeticEngine().run(facts, parsed.tables) + run_date_checks(facts)


def test_financial_demo_runs_parse_to_cited_numeric_findings():
    facts, findings = findings_for("inconsistent_financial_report.txt")
    finding_types = {finding.finding_type for finding in findings}

    assert facts
    assert "profit_identity_violation" in finding_types
    assert "margin_mismatch" in finding_types
    assert "subtotal_mismatch" in finding_types
    assert "total_mismatch" in finding_types
    assert all(finding.explanation for finding in findings)
    assert all(finding.citations for finding in findings)
    assert all(citation.quote for finding in findings for citation in finding.citations)


def test_contract_demo_runs_parse_to_cited_date_findings():
    facts, findings = findings_for("contract_timeline.txt")
    finding_types = {finding.finding_type for finding in findings}

    assert facts
    assert "deadline_outside_period" in finding_types
    assert "conflicting_date_values" in finding_types
    assert all(finding.citations for finding in findings)