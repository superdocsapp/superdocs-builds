"""The conflict memo, and the objection letter that follows from it.

The card asks for a memo that quotes **both sides on each contested point**, and for silence to be
reported as a finding distinct from a conflict. Those two requirements drive everything here.

Why silence gets its own section rather than a row in the conflicts table: a reader skimming a
"conflicts" list and finding warranty absent from it will reasonably conclude warranty is agreed.
It is not agreed — nobody said anything. Putting the two in one list makes the more dangerous
finding look like the safer one.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain.clause import ClauseArea, Party, Verdict
from app.domain.register import RegisterEntry
from app.governing import GoverningAnalysis


class MemoSection(BaseModel):
    """One clause area as it appears in the memo."""

    model_config = ConfigDict(frozen=True)

    area: ClauseArea
    verdict: Verdict
    heading: str = Field(min_length=1)
    buyer_says: tuple[str, ...] = ()
    supplier_says: tuple[str, ...] = ()
    silent_party: Party | None = None
    comment: str = Field(min_length=1)

    @property
    def is_contested(self) -> bool:
        return self.verdict is Verdict.CONFLICT


class ConflictMemo(BaseModel):
    model_config = ConfigDict(frozen=True)

    buyer_document: str
    supplier_document: str
    conflicts: tuple[MemoSection, ...]
    silences: tuple[MemoSection, ...]
    agreements: tuple[MemoSection, ...]
    unaddressed: tuple[ClauseArea, ...]
    governing: GoverningAnalysis | None = None

    @property
    def has_findings(self) -> bool:
        return bool(self.conflicts or self.silences)

    def summary_line(self) -> str:
        """Counts, never adjectives — and silence counted separately from conflict."""
        return (
            f"{len(self.conflicts)} contested point(s), "
            f"{len(self.silences)} point(s) where one document is silent, "
            f"{len(self.agreements)} agreed, "
            f"{len(self.unaddressed)} addressed by neither."
        )


def build_memo(
    *,
    buyer_document: str,
    supplier_document: str,
    entries: Sequence[RegisterEntry],
    unaddressed: Sequence[ClauseArea],
    governing: GoverningAnalysis | None = None,
) -> ConflictMemo:
    conflicts: list[MemoSection] = []
    silences: list[MemoSection] = []
    agreements: list[MemoSection] = []

    for entry in sorted(entries, key=lambda e: e.area):
        section = _section_for(entry)
        if entry.verdict is Verdict.CONFLICT:
            conflicts.append(section)
        elif entry.verdict is Verdict.SILENCE:
            silences.append(section)
        else:
            agreements.append(section)

    return ConflictMemo(
        buyer_document=buyer_document,
        supplier_document=supplier_document,
        conflicts=tuple(conflicts),
        silences=tuple(silences),
        agreements=tuple(agreements),
        unaddressed=tuple(sorted(unaddressed)),
        governing=governing,
    )


def _section_for(entry: RegisterEntry) -> MemoSection:
    buyer_quotes = _quotes(entry, Party.BUYER)
    supplier_quotes = _quotes(entry, Party.SUPPLIER)

    if entry.verdict is Verdict.SILENCE:
        silent = entry.silent_party
        speaking = Party.BUYER if silent is Party.SUPPLIER else Party.SUPPLIER
        comment = (
            f"The {speaking} document states a position on {entry.area.label.lower()}; the "
            f"{silent} document does not address it at all. Nothing has been agreed here — this "
            f"is an open point, not an accepted term."
        )
    elif entry.verdict is Verdict.CONFLICT:
        comment = entry.rationale
    else:
        comment = entry.rationale
        if not entry.confident:
            comment += (
                " This was reached by finding no contradiction rather than by establishing "
                "agreement, so it still warrants a read."
            )

    return MemoSection(
        area=entry.area,
        verdict=entry.verdict,
        heading=entry.area.label,
        buyer_says=buyer_quotes,
        supplier_says=supplier_quotes,
        silent_party=entry.silent_party,
        comment=comment,
    )


def _quotes(entry: RegisterEntry, party: Party) -> tuple[str, ...]:
    position = entry.buyer_position if party is Party.BUYER else entry.supplier_position
    if position is None:
        return ()
    return tuple(citation.quote for citation in position.citations)


# --------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------


def memo_to_html(memo: ConflictMemo) -> str:
    """The memo as a document. Sent to SuperDocs as the base for the drafted letter."""
    parts = [
        "<h1>Terms conflict memo</h1>",
        f"<p><strong>Buyer document:</strong> {_esc(memo.buyer_document)}<br>",
        f"<strong>Supplier document:</strong> {_esc(memo.supplier_document)}</p>",
        f"<p>{_esc(memo.summary_line())}</p>",
    ]

    if memo.governing is not None:
        parts.append("<h2>Which document is likely to govern</h2>")
        parts.append(f"<pre>{_esc(memo.governing.as_prose())}</pre>")

    parts.append("<h2>Contested points</h2>")
    if memo.conflicts:
        for section in memo.conflicts:
            parts.append(_contested_html(section))
    else:
        parts.append("<p>No contested points were found between these two documents.</p>")

    # Deliberately its own heading. A silence buried among conflicts reads as an agreement.
    parts.append("<h2>Points where one document is silent</h2>")
    if memo.silences:
        parts.append(
            "<p>Nothing has been agreed on the following. One side stated a position and the "
            "other did not respond to it.</p>"
        )
        for section in memo.silences:
            parts.append(_silence_html(section))
    else:
        parts.append("<p>Both documents address every clause area the other raises.</p>")

    if memo.unaddressed:
        names = ", ".join(area.label for area in memo.unaddressed)
        parts.append("<h2>Addressed by neither document</h2>")
        parts.append(
            f"<p>{_esc(names)}. These are gaps in the paperwork rather than disagreements "
            f"within it.</p>"
        )

    return "\n".join(parts)


def _contested_html(section: MemoSection) -> str:
    return "\n".join(
        [
            f"<h3>{_esc(section.heading)}</h3>",
            f"<p>{_esc(section.comment)}</p>",
            "<p><strong>The buyer's document says:</strong></p>",
            _quote_list(section.buyer_says),
            "<p><strong>The supplier's document says:</strong></p>",
            _quote_list(section.supplier_says),
        ]
    )


def _silence_html(section: MemoSection) -> str:
    speaking = section.buyer_says or section.supplier_says
    who = "buyer" if section.buyer_says else "supplier"
    return "\n".join(
        [
            f"<h3>{_esc(section.heading)}</h3>",
            f"<p>{_esc(section.comment)}</p>",
            f"<p><strong>The {who}'s document says:</strong></p>",
            _quote_list(speaking),
            f"<p><strong>The {section.silent_party} document:</strong> "
            f"no provision on this topic.</p>",
        ]
    )


def _quote_list(quotes: Sequence[str]) -> str:
    if not quotes:
        return "<p><em>No provision.</em></p>"
    items = "".join(f"<li>{_esc(quote)}</li>" for quote in quotes)
    return f"<ul>{items}</ul>"


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
