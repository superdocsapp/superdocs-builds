"""Tests for claim-to-source span resolution (span_resolution.py).

The LLM paraphrases claims ("Loan Reference is MFL-770487" for source
"Loan Reference: MFL-770487"), so exact-substring lookup alone marked
supported claims unverifiable. These tests pin the resolution ladder:
exact → normalized → token-anchor fuzzy, with hallucination rejection.
"""

from __future__ import annotations

import pytest

from src.pipeline.extractors.llm_extractor import locate_span
from src.pipeline.span_resolution import resolve_span


REPAYMENT_SOURCE = (
    "============================================================\n"
    "REPAYMENT STATEMENT\n"
    "============================================================\n"
    "\n"
    "Loan Reference: MFL-770487\n"
    "Borrower: Rajesh Okafor\n"
    "Statement Period: 2023-08-03 to 2023-12-02\n"
    "Interest Rate Applied: 15.70%\n"
    "\n"
    "------------------------------------------------------------\n"
    "Date         Amount Paid     Late Fee     Outstanding\n"
    "------------------------------------------------------------\n"
    "2023-08-03   37,967.53       0.00         355,818.47\n"
    "2023-09-02   34,306.83       0.00         351,847.29\n"
    "2023-10-02   34,306.83       686.14       351,160.32\n"
)


class TestExactMatch:
    def test_exact_substring(self):
        span = resolve_span("Borrower: Rajesh Okafor", REPAYMENT_SOURCE)
        assert span is not None
        start, end = span
        assert REPAYMENT_SOURCE[start:end] == "Borrower: Rajesh Okafor"

    def test_empty_claim_or_source(self):
        assert resolve_span("", REPAYMENT_SOURCE) is None
        assert resolve_span("anything", "") is None
        assert resolve_span("", "") is None


class TestNormalizedMatch:
    def test_case_and_whitespace_differences(self):
        span = resolve_span(
            "LOAN REFERENCE:    mfl-770487",
            " preamble\n\nLoan Reference: MFL-770487\n",
        )
        assert span is not None
        start, end = span
        assert REPAYMENT_SOURCE.__class__(  # sanity: slice maps into original
            "Loan Reference: MFL-770487"
        ) in " preamble\n\nLoan Reference: MFL-770487\n"[start:end]


class TestTokenAnchorMatch:
    def test_paraphrased_is_vs_colon(self):
        """'X is Y' claim against 'X: Y' source must ground."""
        span = resolve_span("Loan Reference is MFL-770487", REPAYMENT_SOURCE)
        assert span is not None
        start, end = span
        grounded = REPAYMENT_SOURCE[start:end]
        assert "MFL-770487" in grounded

    def test_paraphrased_field_value_pair(self):
        span = resolve_span("Borrower is Rajesh Okafor", REPAYMENT_SOURCE)
        assert span is not None
        start, end = span
        grounded = REPAYMENT_SOURCE[start:end]
        assert "Rajesh Okafor" in grounded

    def test_table_row_claim_grounds_to_row(self):
        """A claim citing date + amount resolves into the table row."""
        span = resolve_span(
            "On 2023-08-03, amount paid is 37,967.53", REPAYMENT_SOURCE
        )
        assert span is not None
        start, end = span
        grounded = REPAYMENT_SOURCE[start:end]
        assert "2023-08-03" in grounded
        assert "37,967.53" in grounded
        # Must not swallow the whole document
        assert len(grounded) < 200

    def test_distinct_rows_ground_to_distinct_spans(self):
        span_a = resolve_span(
            "On 2023-09-02, amount paid is 34,306.83", REPAYMENT_SOURCE
        )
        span_b = resolve_span(
            "On 2023-08-03, amount paid is 37,967.53", REPAYMENT_SOURCE
        )
        assert span_a is not None and span_b is not None
        assert span_a[0] >= span_b[1]  # row 2 starts after row 1 ends

    def test_interest_rate_claim(self):
        span = resolve_span("Interest Rate Applied is 15.70%", REPAYMENT_SOURCE)
        assert span is not None
        start, end = span
        assert "15.70%" in REPAYMENT_SOURCE[start:end]

    def test_hallucinated_claim_rejected(self):
        """No matching tokens → unverifiable, never a fabricated span."""
        assert (
            resolve_span(
                "Insurance premium is 42,000.00", REPAYMENT_SOURCE
            )
            is None
        )

    def test_below_threshold_claim_rejected(self):
        """Only a small minority of tokens matching must not ground."""
        assert (
            resolve_span(
                "Collateral registry document reference is 88,412.99",
                REPAYMENT_SOURCE,
            )
            is None
        )

    def test_generic_single_token_claim_rejected(self):
        """One significant token absent from the source could match
        nowhere — refuse to ground. (A single token that IS present
        verbatim grounds via exact/normalized match, which is correct.)"""
        assert resolve_span("Collateral", REPAYMENT_SOURCE) is None

    def test_stopword_only_claim_rejected(self):
        assert resolve_span("It is the", REPAYMENT_SOURCE) is None


class TestLocateSpanDelegation:
    """llm_extractor.locate_span keeps its SourceSpan contract and gains
    the token-anchor fallback."""

    def test_exact_quote_still_works(self):
        span = locate_span("Borrower: Rajesh Okafor", REPAYMENT_SOURCE)
        assert span is not None
        assert span.start_offset == REPAYMENT_SOURCE.find("Borrower: Rajesh Okafor")

    def test_paraphrased_quote_now_grounded(self):
        span = locate_span("Statement Period is 2023-08-03 to 2023-12-02", REPAYMENT_SOURCE)
        assert span is not None
        grounded = REPAYMENT_SOURCE[span.start_offset:span.end_offset]
        assert "Statement Period" in grounded
        assert "2023-08-03" in grounded

    def test_unverifiable_quote_still_none(self):
        assert locate_span("Totally fabricated content xyz", REPAYMENT_SOURCE) is None

    def test_empty_inputs(self):
        assert locate_span("", REPAYMENT_SOURCE) is None
        assert locate_span("quote", "") is None


class TestSpanRoundTrip:
    """Every grounded span must slice the source to text containing the
    claim's factual payload — the facts API re-slices stored text with
    these offsets."""

    @pytest.mark.parametrize(
        "claim,payload",
        [
            ("Loan Reference is MFL-770487", "MFL-770487"),
            ("Borrower is Rajesh Okafor", "Rajesh Okafor"),
            ("Interest Rate Applied is 15.70%", "15.70%"),
            ("On 2023-10-02, late fee is 686.14", "686.14"),
            ("Outstanding balance on 2023-10-02 is 351,160.32", "351,160.32"),
        ],
    )
    def test_payload_inside_grounded_span(self, claim, payload):
        span = resolve_span(claim, REPAYMENT_SOURCE)
        assert span is not None, claim
        start, end = span
        assert 0 <= start < end <= len(REPAYMENT_SOURCE)
        assert payload in REPAYMENT_SOURCE[start:end]
