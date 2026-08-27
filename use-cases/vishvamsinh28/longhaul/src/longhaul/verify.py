"""Checking that a step actually did what it said.

A turn that proposes nothing is ambiguous. The document may already satisfy the
instruction — a real and common outcome, and the honest report of no findings the brief
asks for. Or the model may simply have missed it. Reporting both as success is a bluff,
and this module exists because a live run produced exactly the second case: a document
plainly containing "PagerDuty" came back with no proposed changes, and the step was
recorded as done.

The check is a plain string test against the document the server actually holds. It costs
nothing — reading a document is free — and it is deliberately not intelligent: its whole
value is that it cannot be talked out of what it sees.

It also distinguishes the two ways an expectation can go unmet, because they mean
opposite things. A reviewer who rejected the change *chose* this outcome. A step that
proposed nothing did not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .model import (
    UNCHECKED,
    UNMET_BY_CHOICE,
    UNMET_NO_CHANGES,
    UNMET_UNKNOWN,
    VERIFIED,
)

_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Expectation:
    absent: tuple[str, ...] = ()
    present: tuple[str, ...] = ()

    @staticmethod
    def load(raw: str | None) -> Expectation | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        exp = Expectation(
            absent=tuple(data.get("absent") or ()),
            present=tuple(data.get("present") or ()),
        )
        return exp if (exp.absent or exp.present) else None


def as_text(html: str) -> str:
    """Document text, tags removed. Chunk ids and attributes must not match a search."""
    return " ".join(_TAG.sub(" ", html or "").split())


def check(
    html: str,
    raw_expectation: str | None,
    *,
    proposed: int,
    rejected: int,
    recovered: bool = False,
) -> tuple[str, str | None]:
    """Return ``(verification, detail)`` for one finished step.

    ``recovered`` means this attempt adopted the step's work rather than performing it,
    so the local record of what was proposed and decided may not have survived.
    """
    expectation = Expectation.load(raw_expectation)
    if expectation is None:
        return UNCHECKED, None

    text = as_text(html)
    unmet: list[str] = []
    for needle in expectation.absent:
        if needle in text:
            unmet.append(f"{needle!r} is still in the document")
    for needle in expectation.present:
        if needle not in text:
            unmet.append(f"{needle!r} never appeared")

    if not unmet:
        return VERIFIED, None

    detail = "; ".join(unmet)
    if recovered and proposed == 0 and rejected == 0:
        # The turn happened on an earlier attempt whose ledger is gone. Whether a
        # reviewer rejected the change or the model missed it cannot be told apart from
        # here, and asserting either would be a guess dressed as a finding.
        return UNMET_UNKNOWN, f"{detail} — this step's decisions did not survive recovery"
    if rejected:
        # A person looked at this and said no. The document not matching is the
        # consequence of their decision, not a silent failure.
        return UNMET_BY_CHOICE, f"{detail} — {rejected} change(s) were rejected"
    if proposed == 0:
        # Nothing was ever offered, and the document does not match. The turn either
        # missed it or misread it, and either way the step did not do its job.
        return UNMET_NO_CHANGES, detail
    return UNMET_NO_CHANGES, f"{detail} — {proposed} change(s) were applied but did not achieve it"


def is_alarming(verification: str | None) -> bool:
    """Only the silent miss is alarming. A rejection is a decision, not a defect."""
    return verification == UNMET_NO_CHANGES
