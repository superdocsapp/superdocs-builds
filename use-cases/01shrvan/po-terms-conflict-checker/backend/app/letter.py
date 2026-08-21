"""The objection-or-confirmation letter.

The card asks for the letter "that preserves the buyer's position". Which letter that is depends on
what the memo found, so the choice is made from the findings rather than asked of the user:

  * anything contested, or anything the supplier is silent on  -> **objection**, reserving rights
  * nothing outstanding                                        -> **confirmation**

A confirmation sent while a conflict is open would waive the buyer's position, so the two are never
offered as an interchangeable pick. The letter type is a consequence of the analysis.

The body is drafted through SuperDocs from this skeleton, one paragraph per outstanding point. The
skeleton exists so the structure comes from the findings rather than from whatever the model felt
like producing — same reasoning as the per-code sections in the corrective-plan build.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.memo import ConflictMemo


class LetterKind(StrEnum):
    OBJECTION = "objection"
    CONFIRMATION = "confirmation"


class LetterPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    heading: str = Field(min_length=1)
    buyer_position: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)


class DraftLetter(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LetterKind
    to: str
    from_: str
    dated: date
    subject: str
    points: tuple[LetterPoint, ...]
    reservation: str

    @property
    def preserves_position(self) -> bool:
        """An objection is only protective if it actually reserves rights."""
        return self.kind is LetterKind.CONFIRMATION or bool(self.reservation)


RESERVATION = (
    "We do not accept the terms set out in your acknowledgement, and nothing in this letter, nor "
    "any performance by either party, should be treated as acceptance of them. All of our rights "
    "are expressly reserved."
)


def build_letter(
    memo: ConflictMemo,
    *,
    to: str,
    from_: str,
    dated: date,
    order_reference: str,
) -> DraftLetter:
    outstanding = list(memo.conflicts) + list(memo.silences)

    if not outstanding:
        return DraftLetter(
            kind=LetterKind.CONFIRMATION,
            to=to,
            from_=from_,
            dated=dated,
            subject=f"Confirmation of terms — {order_reference}",
            points=(),
            reservation="",
        )

    points = []
    for section in memo.conflicts:
        points.append(
            LetterPoint(
                heading=section.heading,
                buyer_position=(
                    f"Our order states: {section.buyer_says[0]}"
                    if section.buyer_says
                    else "Our order states our standard position on this point."
                ),
                why_it_matters=(
                    f"Your acknowledgement states a different position, and we do not accept it. "
                    f"{section.comment}"
                ),
            )
        )

    for section in memo.silences:
        # A silence is raised differently from a conflict: the ask is a response, not a retraction.
        speaking = section.buyer_says or section.supplier_says
        points.append(
            LetterPoint(
                heading=section.heading,
                buyer_position=(
                    f"Our order states: {speaking[0]}"
                    if speaking
                    else "Our order states our standard position on this point."
                ),
                why_it_matters=(
                    f"Your acknowledgement does not address {section.heading.lower()} at all. "
                    f"Please confirm in writing that you accept our provision. In the absence of "
                    f"that confirmation we do not treat this point as agreed."
                ),
            )
        )

    return DraftLetter(
        kind=LetterKind.OBJECTION,
        to=to,
        from_=from_,
        dated=dated,
        subject=f"Objection to terms and reservation of rights — {order_reference}",
        points=tuple(points),
        reservation=RESERVATION,
    )


def letter_to_html(letter: DraftLetter) -> str:
    """The skeleton SuperDocs fills. One numbered section per outstanding point."""
    parts = [
        f"<p>{_esc(letter.dated.isoformat())}</p>",
        f"<p>{_esc(letter.to)}</p>",
        f"<p><strong>{_esc(letter.subject)}</strong></p>",
    ]

    if letter.kind is LetterKind.CONFIRMATION:
        parts.append(
            "<p>We confirm that the terms of your acknowledgement correspond with those of our "
            "order, and that no points remain outstanding between us.</p>"
        )
    else:
        parts.append(
            "<p>We have compared your acknowledgement against our order. The following points are "
            "not agreed, and we write to object to them and to record our position.</p>"
        )
        for index, point in enumerate(letter.points, start=1):
            parts += [
                f"<h3>{index}. {_esc(point.heading)}</h3>",
                f"<p>{_esc(point.buyer_position)}</p>",
                f"<p>{_esc(point.why_it_matters)}</p>",
            ]
        parts.append(f"<p>{_esc(letter.reservation)}</p>")

    parts.append(f"<p>Yours faithfully,<br>{_esc(letter.from_)}</p>")
    return "\n".join(parts)


def _esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
