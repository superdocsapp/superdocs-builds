"""Step 6 (amendment-clause identification) and step 14 (control report)."""

from __future__ import annotations

from src.extraction.clauses import find_amendment_clause_block
from src.extraction.text_extraction import extract_document_text
from src.pipeline import analyze_contract
from src.reporting.control_report import generate_control_report


def test_amendment_clause_located_for_every_structural_style(repo_root, expected_cases):
    expected_headings = {
        "case_01_eligible_30_day_notice": "Article 7",
        "case_02_eligible_60_day_notice": "SECTION 4",
        "case_03_active_pricing_lock": "4. Pricing",
        "case_04_mutual_written_consent_required": "Clause II.3",
        "case_05_ambiguous_requires_human_escalation": "§4",
    }
    for case in expected_cases:
        path = repo_root / case["contract_file"]
        text = extract_document_text(str(path))
        block = find_amendment_clause_block(text)
        assert block is not None, case["case_id"]
        assert expected_headings[case["case_id"]] in block.heading


def test_amendment_clause_citation_quotes_exact_source_passage(repo_root, expected_cases):
    # case_01's exact_source_passage from ground truth must appear verbatim
    # inside the located clause block, proving the "quoted source span"
    # requirement holds for at least one structural style end to end.
    case = expected_cases[0]
    path = repo_root / case["contract_file"]
    text = extract_document_text(str(path))
    block = find_amendment_clause_block(text)
    normalized_body = " ".join(block.body.replace("**", "").split())
    normalized_expected = " ".join(case["exact_source_passage"].split())
    assert normalized_expected in normalized_body


def test_control_report_row_per_contract(repo_root, expected_cases, reference_date):
    rows = []
    for case in expected_cases:
        analysis = analyze_contract(str(repo_root / case["contract_file"]), reference_date)
        rows.append((analysis.partner_contract, analysis.eligibility, analysis.conflicts))

    report = generate_control_report(rows)
    assert len(report) == len(expected_cases)

    by_document_id = {row.document_id: row for row in report}
    for case in expected_cases:
        path = str(repo_root / case["contract_file"])
        row = by_document_id[path]
        assert row.partner_name == case["partner_name"]
        assert row.requires_human_escalation == case["requires_human_escalation"]
        assert row.prompt_injection_present == case.get("prompt_injection_present", False)


def test_control_report_flags_only_ambiguous_contract_with_open_conflicts(
    repo_root, expected_cases, reference_date
):
    rows = []
    for case in expected_cases:
        analysis = analyze_contract(str(repo_root / case["contract_file"]), reference_date)
        rows.append((analysis.partner_contract, analysis.eligibility, analysis.conflicts))

    report = generate_control_report(rows)
    for row, case in zip(report, expected_cases):
        if case["case_id"] == "case_05_ambiguous_requires_human_escalation":
            assert row.open_conflicts > 0
        else:
            assert row.open_conflicts == 0
