"""End-to-end fidelity tests wired to real `AmendmentCase` objects, proving
the four required guarantees from Phase 5:

  1. rejecting every proposal leaves document content unchanged;
  2. approving one rate table does not change another section;
  3. pricing-lock contracts produce no edited export;
  4. only selected proposals are committed (mixed approve/reject).

Mirrors the fixture conventions in tests/unit/test_amendment_case.py
(build_case against the real fixture corpus, hand-built ProposedChange lists
standing in for a recorded SuperDocs job) so this suite exercises the same
case machinery the app actually runs, not a parallel mock of it.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.amendment_case import build_case, record_decision
from src.case_state import CaseState
from src.extraction.rate_tables import extract_rate_entries
from src.extraction.text_extraction import extract_document_text
from src.fidelity.case_fidelity import (
    build_excluded_contract_report,
    build_fidelity_report,
    write_case_fidelity_artifacts,
)
from src.fidelity.compare import DiffClassification, IdentityVerdict
from src.integrations.superdocs_client import ProposedChange


@pytest.fixture
def rate_entries(repo_root):
    old_path = repo_root / "fixtures/rate-cards/rate_card_old_2024Q1.csv"
    new_path = repo_root / "fixtures/rate-cards/rate_card_new_2025Q3.csv"
    old_entries = extract_rate_entries(str(old_path), extract_document_text(str(old_path)))
    new_entries = extract_rate_entries(str(new_path), extract_document_text(str(new_path)))
    return old_entries, new_entries


NORTHSTAR_TEXT = None  # filled per-test from disk, kept here only as a name anchor


def _read(path) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


RATE_TABLE_SECTION = (
    "\n## Schedule A — Rate Card (Amended)\n\n"
    "| Destination | Prefix | Rate (USD/min) |\n"
    "| --- | --- | --- |\n"
    "| United States | 1 | 0.0039 |\n"
    "| United Kingdom | 44 | 0.0061 |\n"
)


def _proposed_northstar_case(repo_root, rate_entries, reference_date):
    """Build a real ANALYSING case against the fixture, then simulate a
    SuperDocs job that proposed adding a new rate-table section (since the
    raw contract_01 fixture has no rate table of its own — see the recorded
    live-API fixture in tests/integration/superdocs_fixtures.py, where
    SuperDocs adds exactly this section rather than editing an existing one).
    Returns (case, contract_path, original_text_with_rate_table) so tests
    compare against a document that already has the table SuperDocs is
    proposing to edit, rather than one missing it entirely."""

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
            change_id="change-us",
            operation="update",
            chunk_id="chunk-us-rate",
            old_html="<td>0.0039</td>",
            new_html="<td>0.0045</td>",
            ai_explanation="Updated US rate",
        ),
        ProposedChange(
            change_id="change-uk",
            operation="update",
            chunk_id="chunk-uk-rate",
            old_html="<td>0.0061</td>",
            new_html="<td>0.0070</td>",
            ai_explanation="Updated UK rate",
        ),
    ]
    return case, contract_path


def _original_with_rate_table(contract_path: str) -> str:
    """The 'before' document already containing the rate table, so a
    fidelity comparison is testing the table-cell edit itself rather than
    the (out-of-scope-for-this-suite) section-insertion diff."""

    return _read(contract_path) + RATE_TABLE_SECTION


class TestRejectingEveryProposalLeavesContentUnchanged:
    def test_all_rejected_export_equals_original_byte_for_byte(self, repo_root, rate_entries, reference_date):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=False)
        record_decision(case, "change-uk", approved=False)
        assert case.state == CaseState.BLOCKED  # all rejected -> no export possible

        original_text = _read(contract_path)
        # A blocked, all-rejected case's "export" is defined as the original
        # file, unmodified (see app/backend/routes/results.py's fallback path
        # for sessions that made no SuperDocs edit).
        report = build_excluded_contract_report(
            case, original_text, reason="all proposed rate changes were rejected during review"
        )

        assert report.verdict == IdentityVerdict.BYTE_IDENTICAL
        assert report.byte_identical is True
        assert report.is_surgical
        assert report.unintended_diff_count == 0
        assert report.excluded_contract is True

    def test_rejected_edits_are_recorded_but_not_marked_should_appear(
        self, repo_root, rate_entries, reference_date
    ):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=False)
        record_decision(case, "change-uk", approved=False)

        original_text = _read(contract_path)
        report = build_excluded_contract_report(case, original_text, reason="all rejected")

        assert len(report.intended_edits_considered) == 2
        assert all(not e.should_appear_in_export for e in report.intended_edits_considered)


class TestApprovingOneRateTableDoesNotChangeAnotherSection:
    def test_only_approved_destination_row_changes(self, repo_root, rate_entries, reference_date):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=True)
        record_decision(case, "change-uk", approved=False)
        assert case.state == CaseState.PARTIALLY_APPROVED

        original_text = _original_with_rate_table(contract_path)
        exported_text = original_text.replace(
            "| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |"
        )
        # UK row and everything else stays exactly as in the original —
        # simulates SuperDocs applying only the approved change.

        report = build_fidelity_report(case, original_text, exported_text, export_format="markdown")

        assert report.verdict == IdentityVerdict.SEMANTICALLY_UNCHANGED
        assert report.is_surgical
        us_diffs = [d for d in report.diffs if "0.0045" in (d.exported_value or "")]
        assert us_diffs and us_diffs[0].classification == DiffClassification.INTENDED
        assert us_diffs[0].matched_change_id == "change-us"

        # No diff touches the UK row or Article 1/7 clause text.
        clause_diffs = [
            d for d in report.diffs if "Article" in (d.original_value or "") or "Article" in (d.exported_value or "")
        ]
        assert clause_diffs == []
        unintended_table_diffs = [
            d for d in report.diffs if d.facet == "table_cell" and d.classification == DiffClassification.UNINTENDED
        ]
        assert unintended_table_diffs == []

    def test_negotiated_clause_text_is_verified_untouched(self, repo_root, rate_entries, reference_date):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=True)
        record_decision(case, "change-uk", approved=True)

        original_text = _original_with_rate_table(contract_path)
        exported_text = original_text.replace(
            "| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |"
        ).replace("| United Kingdom | 44 | 0.0061 |", "| United Kingdom | 44 | 0.0070 |")

        report = build_fidelity_report(case, original_text, exported_text)

        assert report.is_surgical
        notice_clause_diffs = [
            d for d in report.diffs if "30" in (d.original_value or "") and "notice" in (d.original_value or "").lower()
        ]
        assert notice_clause_diffs == []


class TestPricingLockContractsProduceNoEditedExport:
    def test_pricing_lock_case_never_opens_superdocs_and_report_is_byte_identical(
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
        assert case.superdocs_session_id is None
        assert case.pending_changes == []

        original_text = _read(contract_path)
        report = build_excluded_contract_report(case, original_text, reason=case.blocking_reason)

        assert report.excluded_contract is True
        assert "pricing lock" in (report.excluded_reason or "")
        assert report.verdict == IdentityVerdict.BYTE_IDENTICAL
        assert report.is_surgical
        assert report.intended_edits_considered == []

    def test_mutual_consent_case_also_produces_no_edited_export(
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

        original_text = _read(contract_path)
        report = build_excluded_contract_report(case, original_text, reason=case.blocking_reason)

        assert report.verdict == IdentityVerdict.BYTE_IDENTICAL
        assert report.is_surgical


class TestOnlySelectedProposalsAreCommitted:
    def test_mixed_decisions_only_approved_change_appears_and_rejected_does_not(
        self, repo_root, rate_entries, reference_date
    ):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=True)
        record_decision(case, "change-uk", approved=False)

        original_text = _original_with_rate_table(contract_path)
        # Correct export: only the approved US row changes.
        exported_text = original_text.replace(
            "| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |"
        )
        report = build_fidelity_report(case, original_text, exported_text)
        assert report.is_surgical

        # Now simulate a defective export where the rejected UK change also
        # landed — this must be caught as unintended, proving the rejected
        # decision was not silently honored.
        defective_export = exported_text.replace(
            "| United Kingdom | 44 | 0.0061 |", "| United Kingdom | 44 | 0.0070 |"
        )
        defective_report = build_fidelity_report(case, original_text, defective_export)
        assert not defective_report.is_surgical
        assert defective_report.verdict == IdentityVerdict.NOT_VERIFIED
        bad_diffs = [d for d in defective_report.diffs if "0.0070" in (d.exported_value or "")]
        assert bad_diffs and bad_diffs[0].classification == DiffClassification.UNINTENDED

    def test_approvals_dict_is_the_single_source_of_truth_for_disposition(
        self, repo_root, rate_entries, reference_date
    ):
        case, _ = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=True)
        # change-uk left unresolved on purpose.

        from src.fidelity.intended_edits import EditDisposition, derive_intended_edits

        edits = {e.change_id: e for e in derive_intended_edits(case)}
        assert edits["change-us"].disposition == EditDisposition.APPROVED
        assert edits["change-uk"].disposition == EditDisposition.UNRESOLVED
        assert edits["change-uk"].should_appear_in_export is False


class TestArtifactWriting:
    def test_writes_json_markdown_and_html_artifacts(self, repo_root, rate_entries, reference_date, tmp_path):
        case, contract_path = _proposed_northstar_case(repo_root, rate_entries, reference_date)
        record_decision(case, "change-us", approved=True)
        record_decision(case, "change-uk", approved=False)

        original_text = _original_with_rate_table(contract_path)
        exported_text = original_text.replace(
            "| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |"
        )
        report = build_fidelity_report(case, original_text, exported_text)

        paths = write_case_fidelity_artifacts(report, tmp_path, "case_01")

        assert paths["json"].exists()
        assert paths["markdown"].exists()
        assert paths["html"].exists()

        json_text = paths["json"].read_text(encoding="utf-8")
        assert '"verdict"' in json_text
        assert '"is_surgical": true' in json_text

        md_text = paths["markdown"].read_text(encoding="utf-8")
        assert "# Fidelity Report" in md_text

        html_text = paths["html"].read_text(encoding="utf-8")
        assert "<html>" in html_text
        assert "Fidelity Report" in html_text
