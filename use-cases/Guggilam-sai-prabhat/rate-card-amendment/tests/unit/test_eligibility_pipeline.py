"""Steps 3-13 end-to-end, one case per fixture in expected_results.json.

Proves: partner/contract metadata, notice-period extraction, pricing-lock
detection, mutual-consent detection, conflict detection, eligibility
decision, and amendment-letter blocking — all driven from ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.models import EligibilityStatus
from src.pipeline import analyze_contract

_STATUS_BY_ELIGIBILITY = {
    "eligible": EligibilityStatus.ELIGIBLE,
    "not_eligible": EligibilityStatus.NOT_ELIGIBLE,
    "not_eligible_unilaterally": EligibilityStatus.NOT_ELIGIBLE_UNILATERALLY,
    "requires_human_escalation": EligibilityStatus.REQUIRES_REVIEW,
}


def _case_ids(expected_cases: list[dict]) -> list[str]:
    return [case["case_id"] for case in expected_cases]


@pytest.fixture
def analyses(expected_cases, reference_date, repo_root):
    return {
        case["case_id"]: analyze_contract(
            str(repo_root / case["contract_file"]), reference_date
        )
        for case in expected_cases
    }


class TestPartnerContractMetadata:
    def test_partner_name(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert analysis.partner_contract.partner_name == case["partner_name"], case["case_id"]

    def test_our_entity(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert analysis.partner_contract.our_entity == case["our_entity"], case["case_id"]

    def test_contract_identifier(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert (
                analysis.partner_contract.contract_identifier == case["contract_identifier"]
            ), case["case_id"]

    def test_every_partner_contract_fact_is_cited(self, expected_cases, analyses):
        for case in expected_cases:
            citation = analyses[case["case_id"]].partner_contract.citation
            assert citation.document_id
            assert citation.source_span
            assert 0.0 <= citation.confidence <= 1.0
            assert citation.extraction_method is not None


class TestNoticePeriod:
    def test_notice_period_days(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert (
                analysis.notice.notice_period_days == case["notice_period_days"]
            ), case["case_id"]

    def test_unsupported_notice_period_stays_null(self, analyses):
        # case_05: contract states only a qualitative standard, no fixed days.
        analysis = analyses["case_05_ambiguous_requires_human_escalation"]
        assert analysis.notice.notice_period_days is None
        assert analysis.notice.notice_period_type is not None


class TestPricingLockAndMutualConsent:
    def test_pricing_lock_active(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert (
                analysis.eligibility.pricing_lock_active == case["pricing_lock_active"]
            ), case["case_id"]

    def test_mutual_consent_required(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert (
                analysis.eligibility.mutual_consent_required
                == case["mutual_consent_required"]
            ), case["case_id"]


class TestConflictDetection:
    def test_only_ambiguous_contract_has_conflicts(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            if case["case_id"] == "case_05_ambiguous_requires_human_escalation":
                assert len(analysis.conflicts) > 0
            else:
                assert len(analysis.conflicts) == 0, case["case_id"]

    def test_prompt_injection_flagged_but_not_actioned(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            expected_present = case.get("prompt_injection_present", False)
            assert (
                analysis.eligibility.prompt_injection_present == expected_present
            ), case["case_id"]

    def test_prompt_injection_does_not_force_approval(self, analyses):
        # The one contract with the injection must still resolve to
        # requires_review, never eligible, proving the injected text was
        # not treated as an instruction.
        analysis = analyses["case_05_ambiguous_requires_human_escalation"]
        assert analysis.eligibility.prompt_injection_present is True
        assert analysis.eligibility.status == EligibilityStatus.REQUIRES_REVIEW
        assert analysis.eligibility.status != EligibilityStatus.ELIGIBLE


class TestEligibilityDecision:
    def test_status_matches_expected(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            expected_status = _STATUS_BY_ELIGIBILITY[case["amendment_eligibility"]]
            assert analysis.eligibility.status == expected_status, case["case_id"]

    def test_requires_human_escalation_flag(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            assert (
                analysis.eligibility.requires_human_escalation
                == case["requires_human_escalation"]
            ), case["case_id"]

    def test_exclusion_reason_null_only_when_eligible(self, expected_cases, analyses):
        for case in expected_cases:
            analysis = analyses[case["case_id"]]
            if case["amendment_eligibility"] == "eligible":
                assert analysis.eligibility.exclusion_reason is None
            else:
                assert analysis.eligibility.exclusion_reason is not None

    def test_low_confidence_or_conflicted_becomes_requires_review(self, analyses):
        analysis = analyses["case_05_ambiguous_requires_human_escalation"]
        assert analysis.eligibility.status == EligibilityStatus.REQUIRES_REVIEW


class TestAmendmentLetterBlocking:
    def test_pricing_lock_never_generates_letter(self, analyses):
        analysis = analyses["case_03_active_pricing_lock"]
        assert analysis.eligibility.pricing_lock_active is True
        assert analysis.amendment_letter_data.blocked is True
        assert analysis.amendment_letter_data.required_notice_period_days is None

    def test_mutual_consent_never_generates_letter(self, analyses):
        analysis = analyses["case_04_mutual_written_consent_required"]
        assert analysis.eligibility.mutual_consent_required is True
        assert analysis.amendment_letter_data.blocked is True
        assert analysis.amendment_letter_data.required_notice_period_days is None

    def test_requires_review_never_generates_letter(self, analyses):
        analysis = analyses["case_05_ambiguous_requires_human_escalation"]
        assert analysis.amendment_letter_data.blocked is True

    def test_eligible_cases_produce_unblocked_letter_data(self, analyses):
        for case_id in (
            "case_01_eligible_30_day_notice",
            "case_02_eligible_60_day_notice",
        ):
            analysis = analyses[case_id]
            assert analysis.amendment_letter_data.blocked is False
            assert analysis.amendment_letter_data.required_notice_period_days is not None
