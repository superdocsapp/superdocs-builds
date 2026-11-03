"""Tests for rfe_response_builder/validation.py."""
from rfe_response_builder.consistency import ConsistencyFlag
from rfe_response_builder.injection_guard import InjectionRiskResult
from rfe_response_builder.rfe import CoverageRow, EvidenceStatus, Exhibit
from rfe_response_builder.validation import CheckStatus, build_validation_summary


def _row(request_id, answered, evidence_status=EvidenceStatus.ALREADY_SUBMITTED, exhibits=None):
    return CoverageRow(
        request_id=request_id, request_text="some request text", answered=answered,
        matched_prior_arguments=["p. 1"] if answered else [], new_evidence=[],
        exhibit_numbers=exhibits or [], response_section=f"Response to Item {request_id}" if answered else "(not answered)",
        evidence_status=evidence_status,
    )


def test_all_pass_when_everything_is_clean():
    coverage = [_row("1", True), _row("2", True)]
    summary = build_validation_summary(coverage)
    assert summary.overall_status == CheckStatus.PASS
    assert not summary.has_failures
    assert not summary.has_warnings


def test_fails_when_any_item_is_unanswered():
    coverage = [_row("1", True), _row("2", False)]
    summary = build_validation_summary(coverage)
    assert summary.overall_status == CheckStatus.FAIL
    assert summary.has_failures
    fail_check = next(c for c in summary.checks if c.label == "Every request answered")
    assert fail_check.status == CheckStatus.FAIL
    assert "2" in fail_check.detail


def test_unanswered_check_lists_all_unanswered_ids_but_not_answered_ones():
    coverage = [_row("1", False), _row("2", True), _row("3", False)]
    summary = build_validation_summary(coverage)
    fail_check = next(c for c in summary.checks if c.label == "Every request answered")
    listed_ids = fail_check.detail.split("Item(s) ")[1].split(" are")[0].split(", ")
    assert set(listed_ids) == {"1", "3"}


def test_warns_when_evidence_needs_attorney_review():
    coverage = [_row("1", True, evidence_status=EvidenceStatus.NEEDS_ATTORNEY_REVIEW)]
    summary = build_validation_summary(coverage)
    check = next(c for c in summary.checks if c.label == "Evidence gaps identified")
    assert check.status == CheckStatus.WARN
    assert summary.overall_status == CheckStatus.WARN  # warn, not fail, since evidence gaps aren't the hard-stop check


def test_passes_evidence_check_when_already_submitted_or_new_evidence_identified():
    coverage = [
        _row("1", True, evidence_status=EvidenceStatus.ALREADY_SUBMITTED),
        _row("2", True, evidence_status=EvidenceStatus.NEW_EVIDENCE_IDENTIFIED),
    ]
    summary = build_validation_summary(coverage)
    check = next(c for c in summary.checks if c.label == "Evidence gaps identified")
    assert check.status == CheckStatus.PASS


def test_exhibit_numbering_passes_when_sequential_no_gaps():
    coverage = [_row("1", True, exhibits=[1])]
    exhibits = [Exhibit(1, "Exhibit A", "desc", ["1"]), Exhibit(2, "Exhibit B", "desc", ["1"])]
    summary = build_validation_summary(coverage, exhibits=exhibits)
    check = next(c for c in summary.checks if c.label == "Exhibit numbers valid")
    assert check.status == CheckStatus.PASS


def test_exhibit_numbering_fails_on_gap_or_duplicate():
    coverage = [_row("1", True, exhibits=[1])]
    exhibits = [Exhibit(1, "Exhibit A", "desc", ["1"]), Exhibit(3, "Exhibit C", "desc", ["1"])]  # gap: no 2
    summary = build_validation_summary(coverage, exhibits=exhibits)
    check = next(c for c in summary.checks if c.label == "Exhibit numbers valid")
    assert check.status == CheckStatus.FAIL


def test_exhibit_check_passes_trivially_when_no_exhibits():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage, exhibits=[])
    check = next(c for c in summary.checks if c.label == "Exhibit numbers valid")
    assert check.status == CheckStatus.PASS


def test_warns_on_consistency_flags():
    coverage = [_row("1", True), _row("2", True)]
    flags = [ConsistencyFlag("1", "2", "Acme Corp", ["2018"], ["2019"])]
    summary = build_validation_summary(coverage, consistency_flags=flags)
    check = next(c for c in summary.checks if c.label == "Cross-item consistency checked")
    assert check.status == CheckStatus.WARN
    assert summary.overall_status == CheckStatus.WARN


def test_warns_on_injection_flags():
    coverage = [_row("1", True)]
    flags = [("RFE notice", InjectionRiskResult(matched_labels=["ignore previous/prior instructions"],
                                                  matched_snippets=["..."]))]
    summary = build_validation_summary(coverage, injection_flags=flags)
    check = next(c for c in summary.checks if c.label == "Uploaded material scanned for injection risk")
    assert check.status == CheckStatus.WARN


def test_fail_takes_precedence_over_warn_in_overall_status():
    coverage = [_row("1", False, evidence_status=EvidenceStatus.NEEDS_ATTORNEY_REVIEW)]
    summary = build_validation_summary(coverage)
    assert summary.has_failures
    assert summary.has_warnings
    assert summary.overall_status == CheckStatus.FAIL  # fail wins even though warn is also present


def test_empty_coverage_list_does_not_crash():
    summary = build_validation_summary([])
    assert summary.overall_status == CheckStatus.PASS


# --- fact-grounding / quality-gate rows (item #9) ------------------------------

def test_grounding_warns_when_ungrounded_facts_present():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage, ungrounded_by_request={"1": ["a stray unsupported date"]})
    check = next(c for c in summary.checks if c.label == "Draft text checked for unsupported facts")
    assert check.status == CheckStatus.WARN
    assert "1" in check.detail
    assert summary.overall_status == CheckStatus.WARN


def test_grounding_passes_when_ungrounded_by_request_supplied_but_empty():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage, ungrounded_by_request={})
    check = next(c for c in summary.checks if c.label == "Draft text checked for unsupported facts")
    assert check.status == CheckStatus.PASS


def test_grounding_passes_trivially_when_not_supplied_at_all():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage)
    check = next(c for c in summary.checks if c.label == "Draft text checked for unsupported facts")
    assert check.status == CheckStatus.PASS
    assert "not checked" in check.detail.lower()


def test_quality_gate_warns_on_weak_verdicts():
    coverage = [_row("1", True), _row("2", True)]
    summary = build_validation_summary(coverage, weak_quality_request_ids=["2"])
    check = next(c for c in summary.checks if c.label == "Quality gate verdicts")
    assert check.status == CheckStatus.WARN
    assert "2" in check.detail
    assert summary.overall_status == CheckStatus.WARN


def test_quality_gate_passes_when_no_weak_verdicts():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage, weak_quality_request_ids=[])
    check = next(c for c in summary.checks if c.label == "Quality gate verdicts")
    assert check.status == CheckStatus.PASS


def test_quality_gate_passes_trivially_when_not_supplied():
    coverage = [_row("1", True)]
    summary = build_validation_summary(coverage)
    check = next(c for c in summary.checks if c.label == "Quality gate verdicts")
    assert check.status == CheckStatus.PASS
