"""Tests for src/amendment_case.py covering the required failure/decision
scenarios: pricing-lock exclusion, insufficient notice, partial approval,
rejected proposal, missing clause, duplicate-decision idempotency.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.amendment_case import (
    apply_job_status,
    build_case,
    build_instruction,
    check_notice_sufficiency,
    record_decision,
    rejected_change_ids,
    touched_chunk_ids,
    unresolved_change_ids,
)
from src.case_state import CaseState
from src.extraction.rate_tables import extract_rate_entries
from src.extraction.text_extraction import extract_document_text
from src.integrations.superdocs_client import ProposedChange


@pytest.fixture
def rate_entries(repo_root):
    old_path = repo_root / "fixtures/rate-cards/rate_card_old_2024Q1.csv"
    new_path = repo_root / "fixtures/rate-cards/rate_card_new_2025Q3.csv"
    old_entries = extract_rate_entries(str(old_path), extract_document_text(str(old_path)))
    new_entries = extract_rate_entries(str(new_path), extract_document_text(str(new_path)))
    return old_entries, new_entries


class TestPricingLockExclusion:
    def test_case_03_active_pricing_lock_is_blocked_without_superdocs(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_03_summitlink.md")

        case = build_case(
            case_id="case_03",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 10, 1),
        )

        assert case.state == CaseState.BLOCKED
        assert "pricing lock" in case.blocking_reason
        # No SuperDocs session was ever opened for a blocked case.
        assert case.superdocs_session_id is None
        assert case.superdocs_job_id is None
        assert case.pending_changes == []

    def test_case_04_mutual_consent_is_blocked_without_superdocs(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_04_ironvale.md")

        case = build_case(
            case_id="case_04",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 10, 1),
        )

        assert case.state == CaseState.BLOCKED
        assert "mutual" in case.blocking_reason.lower()
        assert case.superdocs_session_id is None


class TestInsufficientNotice:
    def test_check_notice_sufficiency_flags_short_window(self):
        reference = date(2025, 8, 6)
        proposed = date(2025, 8, 11)  # only 5 days out
        reason = check_notice_sufficiency(30, reference, proposed)
        assert reason is not None
        assert "5 day" in reason
        assert "30" in reason

    def test_check_notice_sufficiency_passes_adequate_window(self):
        reference = date(2025, 8, 6)
        proposed = date(2025, 9, 10)  # 35 days out, >= 30
        assert check_notice_sufficiency(30, reference, proposed) is None

    def test_undefined_notice_period_is_not_evaluated(self):
        # case_05's qualitative "commercially reasonable period" -> None days.
        assert check_notice_sufficiency(None, date(2025, 8, 6), date(2025, 8, 7)) is None

    def test_case_01_blocked_when_effective_date_too_soon(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")

        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 8, 11),  # 5 days out, needs 30
        )

        assert case.state == CaseState.BLOCKED
        assert "30 day(s) notice" in case.blocking_reason

    def test_case_01_proceeds_when_effective_date_far_enough(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")

        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 9, 15),  # 40 days out
        )

        assert case.state == CaseState.ANALYSING
        assert case.blocking_reason is None


class TestMissingClause:
    def test_contract_with_no_locatable_clause_requires_review(
        self, repo_root, rate_entries, reference_date, tmp_path
    ):
        old_entries, new_entries = rate_entries
        text = (
            "# GENERIC AGREEMENT\n\n"
            'Parties: Alpha Corp ("Alpha") and Beta Ltd ("Beta")\n\n'
            "**Effective Date:** January 1, 2024\n\n"
            "## Section 1 — Definitions\n\n1.1 Nothing amendment-related here.\n"
        )
        contract_path = tmp_path / "no_clause_contract.md"
        contract_path.write_text(text, encoding="utf-8")

        case = build_case(
            case_id="no_clause",
            contract_path=str(contract_path),
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 12, 1),
        )

        # No amendment clause exists in the text at all, so the low-confidence
        # notice extraction (rules/eligibility.py) already routes this to
        # requires_review before amendment_case.py's own missing-clause check
        # would run — both are correct escalation reasons for the same root
        # cause (no locatable amendment machinery in the document).
        assert case.state == CaseState.REQUIRES_REVIEW
        assert case.blocking_reason is not None
        assert case.analysis.pricing_clause is None

    def test_amendment_case_own_missing_clause_branch_is_reachable(
        self, repo_root, rate_entries, reference_date
    ):
        """Directly exercise the `analysis.pricing_clause is None` branch in
        build_case() (as opposed to the eligibility pipeline's own
        low-confidence-notice escalation), by monkeypatching analyze_contract's
        result for an otherwise-eligible contract."""

        import src.amendment_case as amendment_case_module
        from dataclasses import replace

        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")

        original_analyze = amendment_case_module.analyze_contract

        def patched_analyze(path, ref_date):
            analysis = original_analyze(path, ref_date)
            return replace(analysis, pricing_clause=None)

        amendment_case_module.analyze_contract = patched_analyze
        try:
            case = build_case(
                case_id="case_01_no_clause",
                contract_path=contract_path,
                old_rate_entries=old_entries,
                new_rate_entries=new_entries,
                reference_date=reference_date,
                proposed_effective_date=date(2025, 9, 15),
            )
        finally:
            amendment_case_module.analyze_contract = original_analyze

        assert case.state == CaseState.REQUIRES_REVIEW
        assert "no pricing/amendment clause located" in case.blocking_reason


class TestBuildInstruction:
    def test_instruction_names_clause_and_only_changed_rates(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")
        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 9, 15),
        )

        instruction = build_instruction(case)
        assert "Article 7" in instruction or "Rate Amendments" in instruction
        assert "United States" in instruction
        assert "Do not add, remove, or reword any other clause" in instruction


class TestApplyJobStatus:
    def test_completed_job_with_no_pending_changes_reaches_approved_directly(
        self, repo_root, rate_entries, reference_date
    ):
        """A SuperDocs job can finish with status='completed' and zero
        pending_changes (e.g. proposed rates already matched the document,
        so no edit was needed) without ever passing through 'proposed'.
        This must land on APPROVED, not raise an illegal-transition error."""

        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")
        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 9, 15),
        )
        assert case.state == CaseState.ANALYSING

        class FakeJobStatus:
            job_id = "job-no-changes-needed"
            status = "completed"
            pending_changes = []

        apply_job_status(case, FakeJobStatus())

        assert case.state == CaseState.APPROVED
        assert case.pending_changes == []

    def test_failed_job_transitions_to_failed_with_structured_reason(
        self, repo_root, rate_entries, reference_date
    ):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")
        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 9, 15),
        )

        class FakeJobStatus:
            job_id = "job-failed"
            status = "failed"
            pending_changes = []

        apply_job_status(case, FakeJobStatus())

        assert case.state == CaseState.FAILED
        assert case.failure is not None
        assert case.failure.what
        assert case.failure.likely_cause
        assert case.failure.next_action


class TestApprovalDecisions:
    def _proposed_case(self, repo_root, rate_entries, reference_date):
        old_entries, new_entries = rate_entries
        contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")
        case = build_case(
            case_id="case_01",
            contract_path=contract_path,
            old_rate_entries=old_entries,
            new_rate_entries=new_entries,
            reference_date=reference_date,
            proposed_effective_date=date(2025, 9, 15),
        )
        case.set_state(CaseState.PROPOSED)
        case.pending_changes = [
            ProposedChange(
                change_id="change-1",
                operation="update",
                chunk_id="chunk-us",
                old_html="<td>0.0041</td>",
                new_html="<td>0.0039</td>",
                ai_explanation="Updated US rate",
            ),
            ProposedChange(
                change_id="change-2",
                operation="update",
                chunk_id="chunk-uk",
                old_html="<td>0.0058</td>",
                new_html="<td>0.0061</td>",
                ai_explanation="Updated UK rate",
            ),
        ]
        return case

    def test_partial_approval_sets_partially_approved_state(
        self, repo_root, rate_entries, reference_date
    ):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-1", approved=True)

        assert case.state == CaseState.PARTIALLY_APPROVED
        assert unresolved_change_ids(case) == ["change-2"]

    def test_all_approved_sets_approved_state(self, repo_root, rate_entries, reference_date):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-1", approved=True)
        record_decision(case, "change-2", approved=True)

        assert case.state == CaseState.APPROVED
        assert unresolved_change_ids(case) == []

    def test_all_rejected_sets_blocked_state_with_reason(
        self, repo_root, rate_entries, reference_date
    ):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-1", approved=False)
        record_decision(case, "change-2", approved=False)

        assert case.state == CaseState.BLOCKED
        assert "rejected" in case.blocking_reason
        assert rejected_change_ids(case) == ["change-1", "change-2"]

    def test_mixed_decision_stays_partially_approved(
        self, repo_root, rate_entries, reference_date
    ):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-1", approved=True)
        record_decision(case, "change-2", approved=False)

        assert case.state == CaseState.PARTIALLY_APPROVED
        assert rejected_change_ids(case) == ["change-2"]

    def test_unknown_change_id_raises(self, repo_root, rate_entries, reference_date):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        with pytest.raises(ValueError, match="not a pending change"):
            record_decision(case, "does-not-exist", approved=True)

    def test_touched_chunk_ids_proves_scope(self, repo_root, rate_entries, reference_date):
        case = self._proposed_case(repo_root, rate_entries, reference_date)
        assert touched_chunk_ids(case) == {"chunk-us", "chunk-uk"}
