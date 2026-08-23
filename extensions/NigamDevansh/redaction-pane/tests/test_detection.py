"""8B groundwork, tested where it lives — the reviewer's note that the PII and
store code had no extension-specific tests.

Nothing here needs a key, a network, or Word.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from service.pii.engine import scan
from service.pii.patterns import find, sentence_around
from service.verify_package import check

# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"

SAMPLE = (
    "Patient Jane Whitfield, SSN 123-45-6789, DOB: 4 May 1979, was diagnosed with "
    "hypertension. Card on file 4111 1111 1111 1111; invoice ref 8873 2211 0099 4412. "
    "Contact jane.whitfield@example.com or +1 (415) 555-0142. MRN: AB-99213."
)


class TestPatterns:
    def test_every_span_locates_itself(self) -> None:
        """`text[start:end] == span.text`, always.

        Three things depend on it: the pane highlights by offset, the redaction
        replaces by exact string, and the residue check searches for that
        string. A stripped copy that no longer matches its own offsets breaks
        all three silently.
        """
        for span in find(SAMPLE):
            assert SAMPLE[span.start : span.end] == span.text

    def test_an_invoice_reference_is_not_a_card_number(self) -> None:
        """Luhn is what keeps the pane worth reading. Without it every order
        number in a contract is a card, the list fills with noise, and a
        reviewer learns to click through it — which is the failure that
        matters, because the click is the whole safeguard."""
        kinds = {span.kind for span in find(SAMPLE)}
        assert "credit_card" in kinds
        assert "8873 2211 0099 4412" not in {span.text for span in find(SAMPLE)}

    def test_a_date_of_birth_does_not_swallow_the_next_clause(self) -> None:
        """The marker replaces the span, so an over-captured span deletes words
        the sentence needs. The assignment asks for the sentence to stay
        readable, and this is where that is won or lost."""
        dob = next(span for span in find(SAMPLE) if span.kind == "date_of_birth")
        assert dob.text == "DOB: 4 May 1979"

    def test_categories_are_the_four_the_assignment_names(self) -> None:
        categories = {span.category for span in find(SAMPLE)}
        assert categories <= {"personal", "health", "account", "privileged"}

    def test_the_sentence_is_what_a_reviewer_judges(self) -> None:
        span = next(item for item in find(SAMPLE) if item.kind == "ssn")
        around = sentence_around(SAMPLE, span.start, span.end)
        assert span.text in around
        assert around.startswith("Patient Jane Whitfield")


class FakeLLM:
    """Returns one real span, one privileged span, and one hallucination."""

    model = "fake"

    def structured(self, *, system: str, user: str, schema: dict, max_tokens: int):
        assert "<untrusted-block>" in user, "the document must reach the model as data"
        spans = [{"quote": "NOT PRESENT ANYWHERE", "category": "personal", "kind": "name"}]
        if "counsel" in user:
            spans.append(
                {
                    "quote": "our counsel advises settling below USD 250,000",
                    "category": "privileged",
                    "kind": "legal advice",
                }
            )
        return {"spans": spans}, type("U", (), {"input_tokens": 10, "output_tokens": 4})()


def locate(text: str, quote: str):
    at = text.find(quote)
    return None if at == -1 else (at, at + len(quote))


class TestEngine:
    blocks: ClassVar = [
        ("c1", "body", SAMPLE),
        ("c2", "comment", "Privileged: our counsel advises settling below USD 250,000."),
        ("c3", "tracked_del", "Old card 4111 1111 1111 1111 removed."),
    ]

    def test_it_reads_comments_and_tracked_changes_not_just_the_body(self) -> None:
        """The reason this routes through SuperDocs rather than walking the Word
        body: an identifier inside a tracked deletion is invisible in Word and
        very much present in the file."""
        result = scan(self.blocks, llm=FakeLLM(), locate=locate)
        parts = {candidate.part_type for candidate in result.candidates}

        assert {"comment", "tracked_del"} <= parts

    def test_privileged_passages_come_from_the_model_tier(self) -> None:
        """The fourth category has no shape — no regex and no NER finds legal
        advice, which is why tier 3 exists at all."""
        result = scan(self.blocks, llm=FakeLLM(), locate=locate)
        privileged = [c for c in result.candidates if c.span.category == "privileged"]

        assert len(privileged) == 1
        assert privileged[0].span.detector == "llm"

    def test_a_span_the_model_cannot_quote_is_dropped_and_counted(self) -> None:
        """Offering to remove text that is not in the document would either do
        nothing or remove the wrong thing. Counted rather than silently
        discarded, because "found nothing" and "found four things that are not
        there" are different states."""
        result = scan(self.blocks, llm=FakeLLM(), locate=locate)

        assert "NOT PRESENT ANYWHERE" not in {c.span.text for c in result.candidates}
        assert result.dropped_unverifiable == len(self.blocks)

    def test_tiers_are_reported(self) -> None:
        assert scan(self.blocks, llm=FakeLLM(), locate=locate).tiers == ["patterns", "llm"]
        assert scan(self.blocks).tiers == ["patterns"]


class TestExportResidue:
    """The strongest claim this pane makes, measured on recorded files."""

    removed: ClassVar = ["123-45-6789", "4111 1111 1111 1111"]

    def test_an_ordinary_export_still_carries_the_text(self) -> None:
        """Export alone scrubs nothing — the audit measured that, and this is
        the file that proves it. A pane that assumed otherwise would report a
        document clean while its comments still held the number."""
        report = check((FIXTURES / "13_hidden_export.docx").read_bytes(), self.removed)

        assert report.clean is False
        assert {hit.part for hit in report.residue} == {
            "word/document.xml",
            "word/comments.xml",
        }

    def test_the_redacted_export_is_clean_in_every_part(self) -> None:
        report = check((FIXTURES / "14_hidden_redacted.docx").read_bytes(), self.removed)

        assert report.clean is True
        assert report.markers_found > 0, "clean with no markers usually means nothing applied"
        assert report.parts_checked > 10

    def test_property_residue_is_reported_separately_never_as_cleaned(self) -> None:
        """docProps is outside the pipeline. Counting it as ordinary residue
        would claim a removal this pane does not perform; ignoring it would hide
        one it can see."""
        report = check((FIXTURES / "14_hidden_redacted.docx").read_bytes(), self.removed)

        assert report.property_residue == [] or all(
            hit.in_document_properties for hit in report.property_residue
        )
        assert "document properties" in report.summary or report.clean
