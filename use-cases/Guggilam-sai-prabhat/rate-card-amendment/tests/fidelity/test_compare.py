"""Unit tests for src/fidelity/compare.py's diff classification and verdicts.

Uses hand-built `IntendedEdit`s rather than a live `AmendmentCase`/SuperDocs
session, so these tests exercise the classifier logic in isolation. See
tests/fidelity/test_case_fidelity.py for the end-to-end AmendmentCase path.
"""

from __future__ import annotations

from src.fidelity.compare import DiffClassification, IdentityVerdict, compare_documents
from src.fidelity.intended_edits import EditDisposition, IntendedEdit

ORIGINAL = (
    "# INTERCONNECTION AGREEMENT\n\n"
    "**Parties:** Northstar and Meridian\n\n"
    "## Article 1 — Definitions\n\n"
    "1.1 Services means voice termination.\n\n"
    "## Schedule A — Rate Card\n\n"
    "| Destination | Prefix | Rate (USD/min) |\n"
    "| --- | --- | --- |\n"
    "| United States | 1 | 0.0039 |\n"
    "| United Kingdom | 44 | 0.0061 |\n\n"
    "## Article 7 — Rate Amendments\n\n"
    "7.1 Either Party may propose an amendment with 30 days notice.\n"
)


def _approved_rate_edit() -> IntendedEdit:
    return IntendedEdit(
        change_id="change-1",
        chunk_id="chunk-rate-table",
        old_fragment="<td>0.0039</td>",
        new_fragment="<td>0.0045</td>",
        disposition=EditDisposition.APPROVED,
        ai_explanation="Updated US rate",
    )


class TestByteIdentical:
    def test_no_changes_at_all_is_byte_identical(self):
        report = compare_documents("doc_01", ORIGINAL, ORIGINAL, intended_edits=[])
        assert report.verdict == IdentityVerdict.BYTE_IDENTICAL
        assert report.byte_identical is True
        assert report.is_surgical
        assert report.unintended_diff_count == 0


class TestStructurallyIdentical:
    def test_whitespace_only_difference_is_structurally_identical_not_byte(self):
        exported = ORIGINAL + "\n\n"  # trailing whitespace only
        report = compare_documents("doc_01", ORIGINAL, exported, intended_edits=[])
        assert report.byte_identical is False
        assert report.verdict == IdentityVerdict.STRUCTURALLY_IDENTICAL


class TestSemanticallyUnchanged:
    def test_approved_rate_change_is_intended_and_nothing_else_flagged(self):
        exported = ORIGINAL.replace("| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |")
        report = compare_documents(
            "doc_01", ORIGINAL, exported, intended_edits=[_approved_rate_edit()]
        )
        assert report.verdict == IdentityVerdict.SEMANTICALLY_UNCHANGED
        assert report.is_surgical
        assert report.unintended_diff_count == 0
        assert report.intended_diff_count >= 1
        assert all(d.classification == DiffClassification.INTENDED for d in report.diffs if d.facet == "table_cell")

    def test_other_table_rows_and_articles_remain_untouched(self):
        exported = ORIGINAL.replace("| United States | 1 | 0.0039 |", "| United States | 1 | 0.0045 |")
        report = compare_documents(
            "doc_01", ORIGINAL, exported, intended_edits=[_approved_rate_edit()]
        )
        uk_row_diffs = [d for d in report.diffs if "row=1" in d.location]
        assert uk_row_diffs == []
        article_diffs = [d for d in report.diffs if "Article" in (d.original_value or "") or "Article" in (d.exported_value or "")]
        assert article_diffs == []


class TestUnintendedChangesAreCaught:
    def test_unapproved_edit_to_negotiated_clause_is_flagged_unintended(self):
        exported = ORIGINAL.replace(
            "7.1 Either Party may propose an amendment with 30 days notice.",
            "7.1 Either Party may propose an amendment with 5 days notice.",
        )
        report = compare_documents("doc_01", ORIGINAL, exported, intended_edits=[_approved_rate_edit()])
        assert report.verdict == IdentityVerdict.NOT_VERIFIED
        assert not report.is_surgical
        assert report.unintended_diff_count >= 1
        clause_diffs = [d for d in report.diffs if d.facet == "paragraph" and "5 days" in (d.exported_value or "")]
        assert clause_diffs and clause_diffs[0].classification == DiffClassification.UNINTENDED

    def test_rejected_change_appearing_in_export_is_flagged_unintended(self):
        rejected_edit = IntendedEdit(
            change_id="change-2",
            chunk_id="chunk-uk",
            old_fragment="<td>0.0061</td>",
            new_fragment="<td>0.0099</td>",
            disposition=EditDisposition.REJECTED,
            ai_explanation="rejected by reviewer",
        )
        # UK rate changed as if the rejected edit had been applied anyway.
        exported = ORIGINAL.replace("| United Kingdom | 44 | 0.0061 |", "| United Kingdom | 44 | 0.0099 |")
        report = compare_documents("doc_01", ORIGINAL, exported, intended_edits=[rejected_edit])
        assert not report.is_surgical
        uk_diffs = [d for d in report.diffs if "row=1" in d.location and d.facet == "table_cell"]
        assert uk_diffs and uk_diffs[0].classification == DiffClassification.UNINTENDED

    def test_removed_heading_is_unintended_even_with_an_approved_edit_present(self):
        exported = ORIGINAL.replace("## Article 1 — Definitions\n\n1.1 Services means voice termination.\n\n", "")
        report = compare_documents("doc_01", ORIGINAL, exported, intended_edits=[_approved_rate_edit()])
        assert not report.is_surgical
        section_diffs = [d for d in report.diffs if d.facet == "section_order"]
        assert section_diffs and section_diffs[0].classification == DiffClassification.UNINTENDED


class TestFacetChecksHonestAboutNotApplicable:
    def test_headers_footers_footnotes_not_applicable_for_markdown_export(self):
        report = compare_documents("doc_01", ORIGINAL, ORIGINAL, intended_edits=[])
        by_facet = {fc.facet: fc for fc in report.facet_checks}
        for facet in ("headers", "footers", "footnotes"):
            assert by_facet[facet].status.value == "not_applicable"
            assert by_facet[facet].reason

    def test_core_facets_are_marked_checked(self):
        report = compare_documents("doc_01", ORIGINAL, ORIGINAL, intended_edits=[])
        by_facet = {fc.facet: fc for fc in report.facet_checks}
        for facet in ("body_paragraphs", "tables", "headings_and_section_order", "non_target_text", "target_rate_cells"):
            assert by_facet[facet].status.value == "checked"


class TestExcludedContractFlag:
    def test_excluded_contract_metadata_is_carried_through(self):
        report = compare_documents(
            "doc_03",
            ORIGINAL,
            ORIGINAL,
            intended_edits=[],
            excluded_contract=True,
            excluded_reason="active pricing lock",
        )
        assert report.excluded_contract is True
        assert report.excluded_reason == "active pricing lock"
        assert report.verdict == IdentityVerdict.BYTE_IDENTICAL
