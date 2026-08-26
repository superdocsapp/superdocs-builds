"""Old-vs-new rate-card comparison.

Pure function over already-extracted `RateEntry` facts (see
`extraction/rate_tables.py`) — no I/O, no model reasoning. Joins old and new
rate cards on `destination` and produces one `ProposedRateChange` per
destination present in the new card, citing both source rows.
"""

from __future__ import annotations

from src.domain.models import ExtractionMethod, ProposedRateChange, RateEntry, SourceCitation


def diff_rate_cards(
    document_id: str,
    old_entries: list[RateEntry],
    new_entries: list[RateEntry],
) -> list[ProposedRateChange]:
    """Compare old and new rate-card entries by destination.

    `document_id` is the contract this proposed change set applies to (not
    the rate-card document itself) so the resulting `ProposedRateChange`
    list can be attached directly to an `AmendmentCase`.
    """

    old_by_destination = {entry.destination: entry for entry in old_entries if entry.destination}

    changes: list[ProposedRateChange] = []
    for new_entry in new_entries:
        if not new_entry.destination:
            continue
        old_entry = old_by_destination.get(new_entry.destination)
        old_rate = old_entry.rate_usd_per_min if old_entry else None
        new_rate = new_entry.rate_usd_per_min

        change_pct: float | None = None
        if old_rate is not None and new_rate is not None and old_rate != 0:
            change_pct = round((new_rate - old_rate) / old_rate * 100, 2)

        source_span = (
            f"old: {old_entry.citation.source_span if old_entry else 'no matching old entry'}; "
            f"new: {new_entry.citation.source_span}"
        )
        citation = SourceCitation(
            document_id=document_id,
            source_span=source_span,
            confidence=1.0 if (old_entry is not None and new_rate is not None) else 0.5,
            extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
            section=new_entry.destination,
        )

        changes.append(
            ProposedRateChange(
                document_id=document_id,
                destination=new_entry.destination,
                old_rate_usd_per_min=old_rate,
                new_rate_usd_per_min=new_rate,
                change_pct=change_pct,
                citation=citation,
            )
        )

    return changes
