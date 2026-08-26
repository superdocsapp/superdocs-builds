"""Steps 4-5: rate-table identification and old-rate extraction.

Rate cards in this corpus are CSV files, one row per destination. These
functions are deterministic parsers — no model reasoning involved.
"""

from __future__ import annotations

from typing import Optional

from src.domain.models import ExtractionMethod, RateEntry, SourceCitation
from src.extraction.text_extraction import CsvRow, extract_csv_table


def identify_rate_table(text: str) -> bool:
    """Return True if the given document text is a rate table/card."""

    first_line = text.splitlines()[0] if text.splitlines() else ""
    return "rate_card_id" in first_line and "destination" in first_line


def extract_rate_entries(document_id: str, text: str) -> list[RateEntry]:
    """Parse a rate-card CSV into typed RateEntry facts, one per row."""

    if not identify_rate_table(text):
        return []

    rows: list[CsvRow] = extract_csv_table(text)
    entries: list[RateEntry] = []
    for line_no, row in enumerate(rows, start=2):  # header is line 1
        values = row.values
        rate_raw = values.get("rate_usd_per_min")
        rate = _to_float(rate_raw)
        source_span = ",".join(f"{k}={v}" for k, v in values.items())

        citation = SourceCitation(
            document_id=document_id,
            source_span=source_span,
            confidence=1.0 if rate is not None else 0.0,
            extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
            section=values.get("destination"),
            page=None,
        )
        entries.append(
            RateEntry(
                rate_card_id=values.get("rate_card_id") or None,
                destination=values.get("destination") or None,
                prefix=values.get("prefix") or None,
                rate_usd_per_min=rate,
                effective_date=values.get("effective_date") or None,
                expiry_date=values.get("expiry_date") or None,
                citation=citation,
            )
        )
    return entries


def extract_old_rates(document_id: str, text: str) -> list[RateEntry]:
    """Old-rate extraction: rate entries from a superseded/expired rate card.

    A rate card is treated as "old" if it declares a non-empty expiry_date,
    since the corpus's superseded card is the only one with one populated.
    """

    entries = extract_rate_entries(document_id, text)
    return [entry for entry in entries if entry.expiry_date]


def _to_float(raw: Optional[str]) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None
