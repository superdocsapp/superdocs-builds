"""Repayment statement extractor.

Extracts payment rows from repayment statements. Each row produces a fact
group containing: payment_date, amount_paid, late_fee_charged,
outstanding_balance, and row_index.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from src.pipeline.extractors.base import ExtractedFact, SourceSpan


# Common date formats encountered in microfinance documents
_DATE_FORMATS = [
    "%Y-%m-%d",       # 2024-01-15
    "%m/%d/%Y",       # 01/15/2024
    "%d/%m/%Y",       # 15/01/2024
    "%d-%m-%Y",       # 15-01-2024
    "%m-%d-%Y",       # 01-15-2024
    "%b %d, %Y",     # Jan 15, 2024
    "%B %d, %Y",     # January 15, 2024
    "%d %b %Y",      # 15 Jan 2024
    "%d %B %Y",      # 15 January 2024
]

# Pattern to strip currency symbols and thousand separators from monetary values
_CURRENCY_STRIP_RE = re.compile(r"[^\d.\-]")

# Pattern to detect if a value is numeric after stripping
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _normalize_date(raw: str) -> tuple[str, float]:
    """Normalize a date string to ISO 8601 (YYYY-MM-DD).

    Returns:
        Tuple of (normalized_value, confidence).
        On failure: ("unparseable", 0.0).
    """
    cleaned = raw.strip()
    if not cleaned:
        return "unparseable", 0.0

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d"), 0.9
        except ValueError:
            continue

    return "unparseable", 0.0


def _normalize_monetary(raw: str) -> tuple[str, float]:
    """Normalize a monetary value to 2 decimal places.

    Strips currency symbols, commas, and whitespace.

    Returns:
        Tuple of (normalized_value, confidence).
        On failure (blank/non-numeric): ("not_found", 0.0).
    """
    cleaned = raw.strip()
    if not cleaned or cleaned in ("-", "N/A", "n/a", "NA", "--", "—"):
        return "not_found", 0.0

    # Strip currency symbols and thousand separators
    numeric_str = _CURRENCY_STRIP_RE.sub("", cleaned)

    # Handle multiple dots (e.g., malformed) — keep only last dot as decimal
    parts = numeric_str.split(".")
    if len(parts) > 2:
        numeric_str = "".join(parts[:-1]) + "." + parts[-1]

    if not numeric_str or not _NUMERIC_RE.match(numeric_str):
        return "not_found", 0.0

    try:
        value = float(numeric_str)
        return f"{value:.2f}", 0.85
    except (ValueError, OverflowError):
        return "not_found", 0.0


def _split_row_cells(row: str) -> list[str]:
    """Split a table row into cells.

    Supports pipe-delimited and tab/multi-space separated rows.
    """
    # Try pipe delimiter first
    if "|" in row:
        cells = [c.strip() for c in row.split("|")]
        # Remove empty leading/trailing cells from pipe tables
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        return cells

    # Try tab delimiter
    if "\t" in row:
        return [c.strip() for c in row.split("\t")]

    # Fall back to multi-space splitting (2+ spaces)
    return [c.strip() for c in re.split(r"  +", row)]


def _is_header_row(cells: list[str]) -> bool:
    """Check if a row looks like a table header.

    Uses word-boundary matching to avoid false positives from substrings
    (e.g., 'not-a-date' should not match 'date' as a header keyword).
    """
    header_keywords = [
        r"\bdate\b", r"\bpayment\b", r"\bamount\b", r"\bpaid\b",
        r"\bfee\b", r"\blate\b", r"\boutstanding\b", r"\bbalance\b",
        r"\bsr\b", r"\bno\b", r"\bsl\b",
    ]
    text = " ".join(cells).lower()
    matches = sum(1 for kw in header_keywords if re.search(kw, text))
    return matches >= 2


def _is_separator_row(row: str) -> bool:
    """Check if a row is a separator (e.g., dashes or equals)."""
    stripped = row.strip()
    if not stripped:
        return True
    # Row made entirely of dashes, equals, pipes, spaces, or plus signs
    return bool(re.match(r"^[\-=|+ ]+$", stripped))


class RepaymentExtractor:
    """Extracts payment rows from repayment statements.

    Each row produces a fact group: payment_date, amount_paid,
    late_fee_charged, outstanding_balance, row_index
    """

    async def extract(self, text: str, chunks: list[dict]) -> list[ExtractedFact]:
        """Extract payment rows with 1-based row_index.

        Normalizes dates to ISO 8601 (YYYY-MM-DD).
        Records unparseable dates as value="unparseable", confidence=0.0.
        Records blank/non-numeric monetary fields as value="not_found", confidence=0.0.
        """
        facts: list[ExtractedFact] = []
        lines = text.split("\n")

        # Track position in original text for source spans
        row_index = 0
        current_offset = 0

        for line in lines:
            line_start = text.find(line, current_offset)
            line_end = line_start + len(line)
            current_offset = line_end

            # Skip empty lines and separators
            if _is_separator_row(line):
                continue

            cells = _split_row_cells(line)

            # Skip header rows
            if _is_header_row(cells):
                continue

            # We need at least 4 cells for a valid payment row
            # (date, amount_paid, late_fee, outstanding_balance)
            if len(cells) < 4:
                continue

            # Determine cell positions: we expect
            # [payment_date, amount_paid, late_fee_charged, outstanding_balance]
            # Some tables may have a leading serial number column
            date_cell_idx = 0
            if len(cells) >= 5:
                # Check if first cell looks like a serial number
                first_stripped = cells[0].strip()
                if first_stripped.isdigit() and len(first_stripped) <= 4:
                    date_cell_idx = 1

            date_raw = cells[date_cell_idx]
            amount_raw = cells[date_cell_idx + 1]
            late_fee_raw = cells[date_cell_idx + 2]
            balance_raw = cells[date_cell_idx + 3]

            # Validate this looks like a data row (date cell should have some
            # date-like content or a numeric-looking first cell)
            if not date_raw.strip():
                continue

            row_index += 1
            group_id = f"row_{row_index}"

            # Calculate source spans for each cell
            def _find_cell_span(cell_text: str, search_start: int) -> SourceSpan:
                """Find the character span of a cell within the line."""
                idx = text.find(cell_text, search_start)
                if idx == -1 or idx > line_end:
                    # Fallback to line span
                    return SourceSpan(start_offset=line_start, end_offset=line_end)
                return SourceSpan(
                    start_offset=idx,
                    end_offset=idx + len(cell_text),
                )

            # Extract payment_date
            date_value, date_conf = _normalize_date(date_raw)
            facts.append(ExtractedFact(
                field_name="payment_date",
                value=date_value,
                confidence=date_conf,
                source_span=_find_cell_span(date_raw, line_start),
                fact_group_id=group_id,
            ))

            # Extract amount_paid
            amount_value, amount_conf = _normalize_monetary(amount_raw)
            facts.append(ExtractedFact(
                field_name="amount_paid",
                value=amount_value,
                confidence=amount_conf,
                source_span=_find_cell_span(amount_raw, line_start),
                fact_group_id=group_id,
            ))

            # Extract late_fee_charged
            fee_value, fee_conf = _normalize_monetary(late_fee_raw)
            facts.append(ExtractedFact(
                field_name="late_fee_charged",
                value=fee_value,
                confidence=fee_conf,
                source_span=_find_cell_span(late_fee_raw, line_start),
                fact_group_id=group_id,
            ))

            # Extract outstanding_balance
            bal_value, bal_conf = _normalize_monetary(balance_raw)
            facts.append(ExtractedFact(
                field_name="outstanding_balance",
                value=bal_value,
                confidence=bal_conf,
                source_span=_find_cell_span(balance_raw, line_start),
                fact_group_id=group_id,
            ))

            # Extract row_index
            facts.append(ExtractedFact(
                field_name="row_index",
                value=str(row_index),
                confidence=1.0,
                source_span=SourceSpan(
                    start_offset=line_start,
                    end_offset=line_end,
                ),
                fact_group_id=group_id,
            ))

        return facts
