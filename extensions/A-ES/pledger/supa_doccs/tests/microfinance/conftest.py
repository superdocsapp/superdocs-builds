"""Shared Hypothesis strategies and pytest fixtures for microfinance tests.

Provides reusable data generators for property-based testing of the
classification, extraction, and source linking subsystems.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import hypothesis.strategies as st
import pytest

from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor
from src.pipeline.extractors.modification import ModificationExtractor
from src.pipeline.extractors.repayment import RepaymentExtractor
from src.pipeline.nodes.classify_document import (
    ClassificationResult,
    DocumentClassifierService,
)
from src.pipeline.source_linker import SourceLinker


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------


@st.composite
def loan_agreement_text(draw: st.DrawFn) -> str:
    """Generate realistic loan agreement text with random field values.

    Produces structured text containing borrower/lender names, principal,
    interest rate, interest type, tenure, repayment frequency, processing
    fee, and penal rate. Values are within realistic microfinance ranges.
    """
    borrower = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters=" "),
        min_size=3,
        max_size=30,
    ).filter(lambda s: s.strip() and len(s.strip()) >= 3))
    lender = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters=" "),
        min_size=3,
        max_size=30,
    ).filter(lambda s: s.strip() and len(s.strip()) >= 3))

    principal = draw(st.integers(min_value=5000, max_value=500000))
    interest_rate = draw(st.floats(min_value=8.0, max_value=36.0, allow_nan=False, allow_infinity=False))
    interest_type = draw(st.sampled_from(["flat rate", "reducing balance"]))
    tenure = draw(st.integers(min_value=6, max_value=60))
    frequency = draw(st.sampled_from(["monthly", "quarterly", "semi-annually", "annually", "bullet"]))
    processing_fee = draw(st.integers(min_value=100, max_value=10000))
    penal_rate = draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))

    text = (
        "LOAN AGREEMENT\n"
        "==============\n\n"
        f"Borrower: {borrower.strip()}\n"
        f"Lender: {lender.strip()}\n\n"
        "TERMS AND CONDITIONS\n"
        "--------------------\n\n"
        f"Principal Amount: ₹{principal:,}\n"
        f"Interest Rate: {interest_rate:.2f}%\n"
        f"Interest Type: {interest_type}\n"
        f"Tenure: {tenure} months\n"
        f"Repayment Frequency: {frequency}\n"
        f"Processing Fee: ₹{processing_fee:,}\n"
        f"Penal Rate: {penal_rate:.2f}%\n"
    )
    return text


@st.composite
def modification_text(draw: st.DrawFn) -> str:
    """Generate modification agreement text with random term changes.

    Produces text with a loan reference, 1-3 supported field changes,
    and an effective date. Only uses supported field types.
    """
    loan_ref = draw(st.from_regex(r"[A-Z]{2,4}[0-9]{4,8}", fullmatch=True))

    # Generate 1-3 supported term changes
    num_changes = draw(st.integers(min_value=1, max_value=3))
    available_changes = [
        ("interest_rate", lambda d: (
            f"Interest Rate changed from {d(st.floats(min_value=10.0, max_value=30.0, allow_nan=False, allow_infinity=False)):.2f}% "
            f"to {d(st.floats(min_value=8.0, max_value=25.0, allow_nan=False, allow_infinity=False)):.2f}%"
        )),
        ("tenure_months", lambda d: (
            f"Tenure extended from {d(st.integers(min_value=12, max_value=36))} months "
            f"to {d(st.integers(min_value=24, max_value=60))} months"
        )),
        ("emi_amount", lambda d: (
            f"EMI reduced from ₹{d(st.integers(min_value=3000, max_value=20000)):,} "
            f"to ₹{d(st.integers(min_value=2000, max_value=15000)):,}"
        )),
        ("moratorium_period_months", lambda d: (
            f"Moratorium of {d(st.integers(min_value=1, max_value=12))} months granted"
        )),
    ]

    # Select distinct changes
    selected_indices = draw(
        st.lists(
            st.sampled_from(range(len(available_changes))),
            min_size=num_changes,
            max_size=num_changes,
            unique=True,
        )
    )

    # Generate effective date
    base_date = date(2023, 1, 1)
    offset_days = draw(st.integers(min_value=0, max_value=730))
    effective_date = base_date + timedelta(days=offset_days)

    # Build document text
    lines = [
        "MODIFICATION AGREEMENT",
        "======================\n",
        f"Reference No: {loan_ref}\n",
        f"Effective Date: {effective_date.strftime('%d/%m/%Y')}\n",
        "AMENDMENTS",
        "----------\n",
    ]

    for idx in selected_indices:
        _, generator = available_changes[idx]
        change_text = generator(draw)
        lines.append(f"  {change_text}\n")

    return "\n".join(lines)


@st.composite
def repayment_text(draw: st.DrawFn) -> str:
    """Generate repayment statement text as a pipe-delimited table.

    Produces a header row and 1-5 payment rows with dates, amounts,
    late fees, and outstanding balances.
    """
    num_rows = draw(st.integers(min_value=1, max_value=5))

    # Generate a starting date and balance
    base_date = date(2023, 1, 1)
    start_offset = draw(st.integers(min_value=0, max_value=365))
    starting_balance = draw(st.integers(min_value=50000, max_value=500000))

    lines = [
        "REPAYMENT STATEMENT",
        "===================\n",
        "| Payment Date | Amount Paid | Late Fee | Outstanding Balance |",
        "|---|---|---|---|",
    ]

    balance = starting_balance
    for i in range(num_rows):
        payment_date = base_date + timedelta(days=start_offset + i * 30)
        max_payment = max(1000, min(50000, balance))
        amount_paid = draw(st.integers(min_value=1000, max_value=max_payment))
        late_fee = draw(st.integers(min_value=0, max_value=500))
        balance = max(0, balance - amount_paid + late_fee)

        date_str = payment_date.strftime("%d/%m/%Y")
        lines.append(
            f"| {date_str} | {amount_paid:.2f} | {late_fee:.2f} | {balance:.2f} |"
        )

    return "\n".join(lines)


@st.composite
def monetary_string(draw: st.DrawFn) -> tuple[str, float]:
    """Generate a monetary string in various formats with expected normalized value.

    Returns a tuple of (raw_string, expected_float_value).
    Formats include: plain number, comma-separated, with currency symbols.
    """
    # Generate the base numeric value
    value = draw(st.floats(min_value=100.0, max_value=1000000.0, allow_nan=False, allow_infinity=False))
    # Round to 2 decimal places for the expected value
    expected = round(value, 2)

    # Choose a format
    fmt = draw(st.sampled_from(["plain", "comma", "currency_inr", "currency_usd"]))

    if fmt == "plain":
        raw = f"{expected}"
    elif fmt == "comma":
        # Format with comma thousands separator
        int_part = int(expected)
        dec_part = f"{expected - int_part:.2f}"[1:]  # .XX part
        raw = f"{int_part:,}{dec_part}"
    elif fmt == "currency_inr":
        raw = f"₹{expected:,.2f}"
    elif fmt == "currency_usd":
        raw = f"${expected:,.2f}"
    else:
        raw = str(expected)

    return raw, expected


@st.composite
def date_string(draw: st.DrawFn) -> tuple[str, str]:
    """Generate a date string in various formats with expected ISO output.

    Returns a tuple of (raw_date_string, expected_iso_string).
    Formats include: YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, DD-MM-YYYY,
    DD Mon YYYY, Mon DD, YYYY.
    """
    # Generate a valid date
    year = draw(st.integers(min_value=2000, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))  # Stay safe with days

    d = date(year, month, day)
    expected_iso = d.strftime("%Y-%m-%d")

    fmt = draw(st.sampled_from([
        "iso",
        "dd_mm_yyyy_slash",
        "dd_mm_yyyy_dash",
        "d_b_Y",
        "b_d_Y",
    ]))

    if fmt == "iso":
        raw = d.strftime("%Y-%m-%d")
    elif fmt == "dd_mm_yyyy_slash":
        raw = d.strftime("%d/%m/%Y")
    elif fmt == "dd_mm_yyyy_dash":
        raw = d.strftime("%d-%m-%Y")
    elif fmt == "d_b_Y":
        raw = d.strftime("%d %b %Y")
    elif fmt == "b_d_Y":
        raw = d.strftime("%b %d, %Y")
    else:
        raw = d.strftime("%Y-%m-%d")

    return raw, expected_iso


@st.composite
def source_pointer_and_text(draw: st.DrawFn) -> tuple[SourceSpan, str]:
    """Generate a text string and a valid SourceSpan within it.

    The source span always has start_offset < end_offset and both
    offsets are within the text bounds.
    """
    # Generate text of reasonable length
    text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=5,
        max_size=200,
    ).filter(lambda t: len(t) >= 5))

    text_len = len(text)

    # Generate valid start/end offsets
    start_offset = draw(st.integers(min_value=0, max_value=text_len - 2))
    end_offset = draw(st.integers(min_value=start_offset + 1, max_value=text_len))

    # Optionally add page_number or section_id
    page_number = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=100)))
    section_id = draw(st.one_of(st.none(), st.from_regex(r"sec_[0-9]{1,3}", fullmatch=True)))

    span = SourceSpan(
        start_offset=start_offset,
        end_offset=end_offset,
        page_number=page_number,
        section_id=section_id,
    )

    return span, text


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier_mock() -> MagicMock:
    """Provide a mock DocumentClassifierService.

    Returns a MagicMock that satisfies the DocumentClassifierService protocol.
    The classify method is an AsyncMock that can be configured per test.
    """
    mock = MagicMock(spec=DocumentClassifierService)
    mock.classify = AsyncMock()
    return mock


@pytest.fixture
def loan_extractor() -> LoanAgreementExtractor:
    """Provide a LoanAgreementExtractor instance."""
    return LoanAgreementExtractor()


@pytest.fixture
def modification_extractor() -> ModificationExtractor:
    """Provide a ModificationExtractor instance."""
    return ModificationExtractor()


@pytest.fixture
def repayment_extractor() -> RepaymentExtractor:
    """Provide a RepaymentExtractor instance."""
    return RepaymentExtractor()


@pytest.fixture
def source_linker() -> SourceLinker:
    """Provide a SourceLinker instance."""
    return SourceLinker()
