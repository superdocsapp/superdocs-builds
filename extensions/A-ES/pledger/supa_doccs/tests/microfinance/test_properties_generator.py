"""Property-based tests for synthetic document generator (Properties 17–20).

Feature: microfinance-ingestion-pipeline
Tests generator output structure, conflict manifest validity,
chronological coherence, and determinism.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.synthetic.generator import SyntheticDocumentGenerator


# ---------------------------------------------------------------------------
# Property 17: Generator Output Structure
# ---------------------------------------------------------------------------


class TestProperty17GeneratorOutputStructure:
    """Property 17: For any seed, exactly 5 docs, >=1 of each type,
    exactly 2 conflicts, >=2 formats.

    **Validates: Requirements 6.1, 6.2, 6.4**
    """

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_exactly_5_documents(self, seed: int):
        """Generator always produces exactly 5 documents."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        assert len(pile.documents) == 5

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_at_least_one_of_each_type(self, seed: int):
        """Generator produces at least 1 loan, 1 modification, 1 repayment."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        types = {doc.document_type for doc in pile.documents}
        assert "loan_agreement" in types
        assert "modification_agreement" in types
        assert "repayment_statement" in types

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_exactly_2_conflicts(self, seed: int):
        """Generator produces exactly 2 factual conflicts."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        assert len(pile.manifest.conflicts) == 2

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_at_least_2_formats(self, seed: int):
        """Generator uses at least 2 different document formats."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        formats = {doc.format for doc in pile.documents}
        assert len(formats) >= 2


# ---------------------------------------------------------------------------
# Property 18: Conflict Manifest Validity
# ---------------------------------------------------------------------------


class TestProperty18ConflictManifestValidity:
    """Property 18: Each conflict references one mod and one repayment,
    non-empty field/values.

    **Validates: Requirements 6.3, 6.6**
    """

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_conflict_references_valid_filenames(self, seed: int):
        """Each conflict references filenames present in the pile."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        all_filenames = {doc.filename for doc in pile.documents}
        mod_filenames = {
            doc.filename for doc in pile.documents
            if doc.document_type == "modification_agreement"
        }
        repay_filenames = {
            doc.filename for doc in pile.documents
            if doc.document_type == "repayment_statement"
        }

        for conflict in pile.manifest.conflicts:
            # modification_filename must be in the pile and be a modification doc
            assert conflict.modification_filename in all_filenames, (
                f"Modification filename '{conflict.modification_filename}' not in pile"
            )
            assert conflict.modification_filename in mod_filenames, (
                f"'{conflict.modification_filename}' is not a modification document"
            )

            # repayment_filename must be in the pile and be a repayment doc
            assert conflict.repayment_filename in all_filenames, (
                f"Repayment filename '{conflict.repayment_filename}' not in pile"
            )
            assert conflict.repayment_filename in repay_filenames, (
                f"'{conflict.repayment_filename}' is not a repayment document"
            )

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_conflict_fields_non_empty(self, seed: int):
        """Each conflict has non-empty field_name, expected_value, contradicting_value."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        for conflict in pile.manifest.conflicts:
            assert conflict.field_name and len(conflict.field_name.strip()) > 0
            assert conflict.expected_value and len(conflict.expected_value.strip()) > 0
            assert conflict.contradicting_value and len(conflict.contradicting_value.strip()) > 0


# ---------------------------------------------------------------------------
# Property 19: Chronological Coherence
# ---------------------------------------------------------------------------


class TestProperty19ChronologicalCoherence:
    """Property 19: Loan date < modification dates < repayment dates,
    shared loan reference.

    **Validates: Requirements 6.7**
    """

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_shared_loan_reference(self, seed: int):
        """All documents in the pile share a common loan reference identifier."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        # Extract loan references from text content
        # Look for a common loan ID pattern (e.g., MFL-XXXXXX)
        loan_ref_pattern = re.compile(r"MFL-\d{6}")

        refs_per_doc: list[set[str]] = []
        for doc in pile.documents:
            refs = set(loan_ref_pattern.findall(doc.text_content))
            refs_per_doc.append(refs)

        # All documents should share at least one common reference
        if refs_per_doc:
            common_refs = refs_per_doc[0]
            for refs in refs_per_doc[1:]:
                common_refs = common_refs & refs
            assert len(common_refs) >= 1, (
                f"No common loan reference across documents. "
                f"Per-doc refs: {refs_per_doc}"
            )

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_chronological_order(self, seed: int):
        """Loan date < modification effective date < repayment start dates."""
        gen = SyntheticDocumentGenerator(seed=seed)
        pile = gen.generate()

        # Extract dates from documents
        date_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")

        loan_dates: list[date] = []
        mod_dates: list[date] = []
        repay_dates: list[date] = []

        for doc in pile.documents:
            dates_found = date_pattern.findall(doc.text_content)
            parsed_dates = []
            for d in dates_found:
                try:
                    parsed_dates.append(date.fromisoformat(d))
                except ValueError:
                    continue

            if parsed_dates:
                if doc.document_type == "loan_agreement":
                    loan_dates.extend(parsed_dates)
                elif doc.document_type == "modification_agreement":
                    mod_dates.extend(parsed_dates)
                elif doc.document_type == "repayment_statement":
                    repay_dates.extend(parsed_dates)

        # Loan dates should precede modification dates
        if loan_dates and mod_dates:
            earliest_loan = min(loan_dates)
            for md in mod_dates:
                # Modification dates should be >= earliest loan date
                assert md >= earliest_loan, (
                    f"Modification date {md} precedes loan date {earliest_loan}"
                )

        # Modification dates should precede repayment dates
        if mod_dates and repay_dates:
            earliest_mod = min(mod_dates)
            earliest_repay = min(repay_dates)
            assert earliest_repay >= earliest_mod, (
                f"Repayment date {earliest_repay} precedes modification date {earliest_mod}"
            )


# ---------------------------------------------------------------------------
# Property 20: Generator Determinism
# ---------------------------------------------------------------------------


class TestProperty20GeneratorDeterminism:
    """Property 20: Same seed -> identical output.

    **Validates: Requirements 6.8**
    """

    @given(seed=st.integers())
    @settings(max_examples=100)
    def test_same_seed_produces_identical_output(self, seed: int):
        """Two invocations with the same seed produce byte-identical output."""
        gen1 = SyntheticDocumentGenerator(seed=seed)
        pile1 = gen1.generate()

        gen2 = SyntheticDocumentGenerator(seed=seed)
        pile2 = gen2.generate()

        # Same number of documents
        assert len(pile1.documents) == len(pile2.documents)

        # Each document is identical
        for doc1, doc2 in zip(pile1.documents, pile2.documents):
            assert doc1.filename == doc2.filename
            assert doc1.document_type == doc2.document_type
            assert doc1.format == doc2.format
            assert doc1.content == doc2.content
            assert doc1.text_content == doc2.text_content

        # Conflict manifest is identical
        assert len(pile1.manifest.conflicts) == len(pile2.manifest.conflicts)
        for c1, c2 in zip(pile1.manifest.conflicts, pile2.manifest.conflicts):
            assert c1.field_name == c2.field_name
            assert c1.expected_value == c2.expected_value
            assert c1.contradicting_value == c2.contradicting_value
            assert c1.modification_filename == c2.modification_filename
            assert c1.repayment_filename == c2.repayment_filename
