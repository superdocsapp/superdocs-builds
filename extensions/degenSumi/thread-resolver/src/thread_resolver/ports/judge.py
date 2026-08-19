"""The seam for language judgement about a thread.

A judge answers one question and holds no authority beyond it: given what the
participants said, did they converge on an outcome or not. It receives a
transcript, never the document, and it cannot change anything.

Keeping judgement separate from editing is deliberate. Comment text is written
by other people and arrives untrusted, and the component that reads it should
not be the component able to rewrite the document.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Verdict(StrEnum):
    AGREED = "agreed"
    """Participants converged on one outcome."""

    DISAGREED = "disagreed"
    """Participants want incompatible outcomes."""

    UNSURE = "unsure"
    """No confident reading. Treated the same as having no judge at all."""


@dataclass(frozen=True, slots=True)
class Judgement:
    verdict: Verdict
    reason: str
    """Short justification, carried into the review gate so a person sees why."""


@runtime_checkable
class Judge(Protocol):
    def assess(self, transcript: str) -> Judgement:
        """Read a thread transcript and report whether it converged.

        Implementations must not raise for ordinary failures. An unreachable
        model returns UNSURE, which routes the thread to a person rather than
        stopping the run.
        """
        ...
