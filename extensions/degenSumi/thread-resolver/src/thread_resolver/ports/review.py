"""The seam where a person decides what happens.

Every item reaches this gate, including those carrying no proposed edit. A
contested thread is a decision to make, not a change to apply, and dropping it
before the gate would hide the disagreement the run exists to surface.

An implementation must return a decision for every item it was given. Silence is
not consent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from thread_resolver.domain.models import ReviewItem


@runtime_checkable
class ReviewGate(Protocol):
    def present(self, items: tuple[ReviewItem, ...]) -> tuple[ReviewItem, ...]:
        """Show each item and return them carrying decisions, in the same order."""
        ...
