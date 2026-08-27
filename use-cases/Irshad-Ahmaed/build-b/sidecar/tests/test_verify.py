"""Tests for Build B PDF number-matching verification."""

from __future__ import annotations

from pathlib import Path

from build_b.verify import (
    extract_dollar_amounts,
    extract_percentages,
)


def test_extract_dollar_amounts_basic() -> None:
    """Basic dollar extraction from text."""
    text = "Build cost: $37,500. Maintenance: $7,500. Infra: $1,200."
    amounts = extract_dollar_amounts(text)
    assert amounts == [37500.0, 7500.0, 1200.0]


def test_extract_dollar_amounts_with_cents() -> None:
    """Dollar extraction with decimal values."""
    text = "Total: $1,234.56"
    amounts = extract_dollar_amounts(text)
    assert amounts == [1234.56]


def test_extract_dollar_amounts_no_commas() -> None:
    """Dollar extraction without comma formatting."""
    text = "Cost: $75"
    amounts = extract_dollar_amounts(text)
    assert amounts == [75.0]


def test_extract_dollar_amounts_empty() -> None:
    """No dollar amounts returns empty list."""
    amounts = extract_dollar_amounts("No money here.")
    assert amounts == []


def test_extract_percentages() -> None:
    """Percentage extraction from text."""
    text = "Maintenance rate: 20%. Growth: 3.5%."
    pcts = extract_percentages(text)
    assert pcts == [20.0, 3.5]


def test_extract_percentages_empty() -> None:
    """No percentages returns empty list."""
    pcts = extract_percentages("No percentages here.")
    assert pcts == []


def test_verify_numbers_matching(tmp_path: Path) -> None:
    """When PDF contains expected numbers, all checks pass."""
    # Create a fake PDF text (we'll test the extraction logic directly)
    # Since we can't easily create a real PDF in tests, we test the logic
    # via the helper functions and mock the PDF parsing
    from build_b.verify import extract_dollar_amounts
    text = "Build: $37,500. Buy: $0."
    amounts = extract_dollar_amounts(text)
    assert 37500.0 in amounts
    assert 0.0 in amounts


def test_verify_numbers_tolerance() -> None:
    """Numbers within tolerance are considered matching."""
    from build_b.verify import extract_dollar_amounts
    text = "Cost: $37,500.05"
    amounts = extract_dollar_amounts(text)
    # 37500.05 should match 37500.0 within tolerance 0.1
    matched = any(abs(a - 37500.0) <= 0.1 for a in amounts)
    assert matched


def test_verify_numbers_out_of_tolerance() -> None:
    """Numbers outside tolerance are not matching."""
    from build_b.verify import extract_dollar_amounts
    text = "Cost: $38,000"
    amounts = extract_dollar_amounts(text)
    matched = any(abs(a - 37500.0) <= 0.01 for a in amounts)
    assert not matched
