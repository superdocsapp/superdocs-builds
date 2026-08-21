"""Clause areas and the verdicts a register entry can carry.

The verdict vocabulary is the load-bearing decision in this whole system, so it lives on its own and
is deliberately small. See INVARIANTS.md I1 for why `SILENCE` is not a flavour of `AGREE`.
"""

from __future__ import annotations

from enum import StrEnum


class ClauseArea(StrEnum):
    """The clause areas a procurement pile is compared across.

    Areas are identified by substance, not by the heading a document happens to use: a clause titled
    "Maximum Recoverable Amount" belongs to `LIABILITY` just as one titled "Limitation of Liability"
    does. The mapping from text to area is a model decision; this enum is only the vocabulary.
    """

    WARRANTY = "warranty"
    LIABILITY = "liability"
    DELIVERY = "delivery"
    TITLE_AND_RISK = "title_and_risk"
    PAYMENT = "payment"
    IP = "ip"
    GOVERNING_LAW = "governing_law"

    @property
    def label(self) -> str:
        """Human-readable name, for memos and the review UI."""
        return _LABELS[self]


_LABELS = {
    ClauseArea.WARRANTY: "Warranty",
    ClauseArea.LIABILITY: "Liability",
    ClauseArea.DELIVERY: "Delivery",
    ClauseArea.TITLE_AND_RISK: "Title and risk",
    ClauseArea.PAYMENT: "Payment",
    ClauseArea.IP: "Intellectual property",
    ClauseArea.GOVERNING_LAW: "Governing law",
}


class Verdict(StrEnum):
    """The outcome of comparing two documents on one clause area.

    `SILENCE` is a first-class outcome, not a variant of `AGREE`. One document addressed the topic
    and the other did not; nothing has been agreed, and the gap is the finding.
    """

    AGREE = "agree"
    CONFLICT = "conflict"
    SILENCE = "silence"

    @property
    def is_actionable(self) -> bool:
        """Whether this verdict needs a human to look at it.

        Both `CONFLICT` and `SILENCE` are actionable. Treating silence as nothing-to-see-here is the
        exact failure this system exists to prevent.
        """
        return self in (Verdict.CONFLICT, Verdict.SILENCE)


class Party(StrEnum):
    """Which side of the transaction a document speaks for."""

    BUYER = "buyer"
    SUPPLIER = "supplier"
