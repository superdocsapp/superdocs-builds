"""Unit tests for the synthetic document generator."""

import pytest

from tests.synthetic.generator import (
    ConflictEntry,
    ConflictManifest,
    GroundTruthFact,
    SyntheticDocument,
    SyntheticDocumentGenerator,
    SyntheticPile,
)


class TestDataclasses:
    """Tests for dataclass definitions."""

    def test_ground_truth_fact_creation(self):
        fact = GroundTruthFact(
            field_name="principal_amount",
            value="50000.00",
            start_offset=100,
            end_offset=108,
        )
        assert fact.field_name == "principal_amount"
        assert fact.value == "50000.00"
        assert fact.start_offset == 100
        assert fact.end_offset == 108

    def test_synthetic_document_creation(self):
        doc = SyntheticDocument(
            filename="test.txt",
            document_type="loan_agreement",
            format="text",
            content=b"hello",
            text_content="hello",
            ground_truth_facts=[],
        )
        assert doc.filename == "test.txt"
        assert doc.document_type == "loan_agreement"
        assert doc.format == "text"
        assert doc.content == b"hello"
        assert doc.text_content == "hello"
        assert doc.ground_truth_facts == []

    def test_conflict_entry_creation(self):
        entry = ConflictEntry(
            field_name="interest_rate",
            expected_value="10.00%",
            contradicting_value="14.00%",
            modification_filename="mod.txt",
            repayment_filename="repay.txt",
        )
        assert entry.field_name == "interest_rate"
        assert entry.expected_value == "10.00%"
        assert entry.contradicting_value == "14.00%"

    def test_conflict_manifest_creation(self):
        manifest = ConflictManifest(conflicts=[])
        assert manifest.conflicts == []

    def test_synthetic_pile_creation(self):
        pile = SyntheticPile(documents=[], manifest=ConflictManifest())
        assert pile.documents == []
        assert pile.manifest.conflicts == []


class TestSyntheticDocumentGenerator:
    """Tests for the SyntheticDocumentGenerator class."""

    def test_deterministic_with_seed(self):
        """Same seed produces identical output."""
        gen1 = SyntheticDocumentGenerator(seed=42)
        gen2 = SyntheticDocumentGenerator(seed=42)

        pile1 = gen1.generate()
        pile2 = gen2.generate()

        assert len(pile1.documents) == len(pile2.documents)
        for doc1, doc2 in zip(pile1.documents, pile2.documents):
            assert doc1.filename == doc2.filename
            assert doc1.document_type == doc2.document_type
            assert doc1.format == doc2.format
            assert doc1.text_content == doc2.text_content
            assert doc1.content == doc2.content

        assert len(pile1.manifest.conflicts) == len(pile2.manifest.conflicts)
        for c1, c2 in zip(pile1.manifest.conflicts, pile2.manifest.conflicts):
            assert c1.field_name == c2.field_name
            assert c1.expected_value == c2.expected_value
            assert c1.contradicting_value == c2.contradicting_value

    def test_different_seeds_produce_different_output(self):
        """Different seeds produce different documents."""
        gen1 = SyntheticDocumentGenerator(seed=42)
        gen2 = SyntheticDocumentGenerator(seed=123)

        pile1 = gen1.generate()
        pile2 = gen2.generate()

        # At least one document should differ
        texts1 = [d.text_content for d in pile1.documents]
        texts2 = [d.text_content for d in pile2.documents]
        assert texts1 != texts2

    def test_exactly_five_documents(self):
        """Generate produces exactly 5 documents."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        assert len(pile.documents) == 5

    def test_at_least_one_loan_agreement(self):
        """Pile contains at least one loan agreement."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        loan_docs = [d for d in pile.documents if d.document_type == "loan_agreement"]
        assert len(loan_docs) >= 1

    def test_at_least_one_modification_agreement(self):
        """Pile contains at least one modification agreement."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        mod_docs = [d for d in pile.documents if d.document_type == "modification_agreement"]
        assert len(mod_docs) >= 1

    def test_at_least_one_repayment_statement(self):
        """Pile contains at least one repayment statement."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        repay_docs = [d for d in pile.documents if d.document_type == "repayment_statement"]
        assert len(repay_docs) >= 1

    def test_exactly_two_conflicts(self):
        """Manifest contains exactly 2 factual conflicts."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        assert len(pile.manifest.conflicts) == 2

    def test_conflicts_between_modification_and_repayment(self):
        """Conflicts reference modification and repayment documents."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        mod_filenames = {d.filename for d in pile.documents if d.document_type == "modification_agreement"}
        repay_filenames = {d.filename for d in pile.documents if d.document_type == "repayment_statement"}

        for conflict in pile.manifest.conflicts:
            assert conflict.modification_filename in mod_filenames
            assert conflict.repayment_filename in repay_filenames

    def test_at_least_two_formats(self):
        """Documents use at least 2 different formats."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()
        formats = {d.format for d in pile.documents}
        assert len(formats) >= 2

    def test_shared_loan_reference(self):
        """All documents reference the same loan ID."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        # Extract loan reference from each document's text
        # All documents should contain the same loan ID
        loan_docs = [d for d in pile.documents if d.document_type == "loan_agreement"]
        # Get the loan_id from the first loan agreement's ground truth
        loan_id_facts = [
            f for f in loan_docs[0].ground_truth_facts if f.field_name == "loan_id"
        ]
        assert len(loan_id_facts) == 1
        loan_id = loan_id_facts[0].value

        for doc in pile.documents:
            assert loan_id in doc.text_content, (
                f"Document {doc.filename} does not reference loan ID {loan_id}"
            )

    def test_chronological_coherence(self):
        """Loan date < modification date < repayment dates."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        # Get dates from ground truth facts
        mod_docs = [d for d in pile.documents if d.document_type == "modification_agreement"]
        repay_docs = [d for d in pile.documents if d.document_type == "repayment_statement"]

        # Modification effective date
        mod_date_facts = [
            f for f in mod_docs[0].ground_truth_facts if f.field_name == "effective_date"
        ]
        assert len(mod_date_facts) == 1
        mod_date_str = mod_date_facts[0].value

        # Repayment dates (first row payment date)
        for repay_doc in repay_docs:
            row_1_date_facts = [
                f for f in repay_doc.ground_truth_facts if f.field_name == "row_1_payment_date"
            ]
            assert len(row_1_date_facts) == 1
            repay_date_str = row_1_date_facts[0].value
            # Dates are ISO format, lexicographic comparison works
            assert mod_date_str < repay_date_str, (
                f"Modification date {mod_date_str} should precede repayment date {repay_date_str}"
            )

    def test_ground_truth_facts_have_valid_offsets(self):
        """All ground truth facts have valid start/end offsets within text_content."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        for doc in pile.documents:
            for fact in doc.ground_truth_facts:
                assert fact.start_offset >= 0
                assert fact.end_offset > fact.start_offset
                assert fact.end_offset <= len(doc.text_content)
                # The substring at the offsets should match the fact value
                extracted = doc.text_content[fact.start_offset:fact.end_offset]
                assert extracted == fact.value, (
                    f"Fact '{fact.field_name}' offset mismatch: "
                    f"expected '{fact.value}', got '{extracted}'"
                )

    def test_content_is_text_encoded_as_bytes(self):
        """Document content is the text_content encoded as UTF-8 bytes."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        for doc in pile.documents:
            assert doc.content == doc.text_content.encode("utf-8")

    def test_documents_have_realistic_structure(self):
        """Documents contain headers, clause numbering, and financial values."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        loan_docs = [d for d in pile.documents if d.document_type == "loan_agreement"]
        assert any("LOAN AGREEMENT" in d.text_content for d in loan_docs)
        assert any("Clause" in d.text_content for d in loan_docs)

        mod_docs = [d for d in pile.documents if d.document_type == "modification_agreement"]
        assert any("MODIFICATION AGREEMENT" in d.text_content for d in mod_docs)
        assert any("Amendment" in d.text_content for d in mod_docs)

        repay_docs = [d for d in pile.documents if d.document_type == "repayment_statement"]
        assert any("REPAYMENT STATEMENT" in d.text_content for d in repay_docs)

    def test_each_document_has_ground_truth_facts(self):
        """Every document has at least one ground truth fact."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        for doc in pile.documents:
            assert len(doc.ground_truth_facts) >= 1, (
                f"Document {doc.filename} has no ground truth facts"
            )

    def test_conflict_values_differ(self):
        """Conflict expected_value and contradicting_value are different."""
        gen = SyntheticDocumentGenerator(seed=1)
        pile = gen.generate()

        for conflict in pile.manifest.conflicts:
            assert conflict.expected_value != conflict.contradicting_value, (
                f"Conflict for {conflict.field_name}: expected and contradicting values are the same"
            )

    def test_no_seed_still_produces_valid_pile(self):
        """Generator without seed still produces a valid pile."""
        gen = SyntheticDocumentGenerator()
        pile = gen.generate()

        assert len(pile.documents) == 5
        assert len(pile.manifest.conflicts) == 2
        doc_types = {d.document_type for d in pile.documents}
        assert "loan_agreement" in doc_types
        assert "modification_agreement" in doc_types
        assert "repayment_statement" in doc_types
