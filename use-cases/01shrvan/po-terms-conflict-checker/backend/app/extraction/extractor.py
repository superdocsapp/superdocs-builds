"""Turning a document's text into cited positions, one per clause area it addresses.

The extractor splits a document into sentence-ish spans, decides which clause areas each span
belongs to, and emits a `Position` per area with the spans as citations. Because citations are cut
from the source with `Citation.into`, every position that leaves here is quotable.

What this deliberately does *not* do: guess. A document with no span matching an area produces no
position for that area, and the reconciler turns that absence into `SILENCE`. Inventing a
weakly-worded position to avoid an empty result would destroy the distinction the whole system
exists to preserve.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from app.domain.citation import Citation
from app.domain.clause import ClauseArea, Party
from app.domain.position import Position
from app.extraction.patterns import areas_for, instruction_phrases_in

# Split on sentence enders and newlines, keeping offsets. Clause text is full of "Cl. 7.2" and
# "No. 3", so a naive split on "." alone would shred it; requiring whitespace after the stop and a
# following capital or digit-with-space keeps numbered references intact.
#
# A lone newline is NOT a boundary. Contract text is hard-wrapped, so splitting on every line break
# cut sentences in half: "...until payment has been received in" / "full, notwithstanding delivery
# and the passing of risk." That second fragment mentions delivery and nothing else, so it filed
# under Delivery and the memo quoted half a retention-of-title clause under a delivery heading.
# Only a sentence ending, or a blank line, closes a span.
_BOUNDARY = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9])|\n\s*\n")


class Span(NamedTuple):
    """A slice of a document, with the offsets it came from."""

    start: int
    end: int
    text: str


def split_spans(text: str, *, min_length: int = 12) -> list[Span]:
    """Break text into spans, preserving exact offsets into the original."""
    spans: list[Span] = []
    cursor = 0
    for piece in _BOUNDARY.split(text):
        if piece is None:
            continue
        start = text.find(piece, cursor)
        if start == -1:
            continue
        end = start + len(piece)
        cursor = end
        stripped = piece.strip()
        if len(stripped) < min_length:
            continue
        # Trim leading/trailing whitespace out of the recorded offsets so a citation never quotes
        # a ragged edge.
        lead = len(piece) - len(piece.lstrip())
        spans.append(Span(start + lead, start + lead + len(stripped), stripped))
    return spans


def extract_positions(
    *,
    document_id: str,
    text: str,
    party: Party,
) -> dict[ClauseArea, Position]:
    """Every clause area this document actually addresses, with citations.

    Areas the document does not address are simply absent from the result. That absence is the
    input to `SILENCE`, so it must never be padded with an empty placeholder.
    """
    by_area: dict[ClauseArea, list[Span]] = {}

    for span in split_spans(text):
        for area in areas_for(span.text):
            by_area.setdefault(area, []).append(span)

    positions: dict[ClauseArea, Position] = {}
    for area, spans in by_area.items():
        citations = tuple(
            Citation.into(document_id, text, span.start, span.end) for span in spans
        )
        positions[area] = Position(
            party=party,
            document_id=document_id,
            area=area,
            # A neutral restatement. The citations carry the actual words; the summary exists so a
            # reviewer can scan, and is never the thing a verdict is based on.
            summary=_summarise(area, spans),
            citations=citations,
        )
    return positions


def _summarise(area: ClauseArea, spans: list[Span]) -> str:
    lead = spans[0].text
    if len(lead) > 160:
        lead = lead[:157].rstrip() + "..."
    suffix = f" (+{len(spans) - 1} further span{'s' if len(spans) > 2 else ''})" if len(spans) > 1 else ""
    return f"{area.label}: {lead}{suffix}"


def find_instruction_attempts(*, document_id: str, text: str) -> list[tuple[Citation, str]]:
    """Spans where the document tries to instruct the system.

    Returned as citations so they can be reported with the same evidence discipline as any other
    claim. Nothing here is ever executed — see INVARIANTS.md I4.
    """
    attempts: list[tuple[Citation, str]] = []
    for span in split_spans(text, min_length=1):
        for phrase in instruction_phrases_in(span.text):
            attempts.append(
                (Citation.into(document_id, text, span.start, span.end), phrase)
            )
    return attempts
