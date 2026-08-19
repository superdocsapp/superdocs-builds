"""The seam between the resolver and wherever comment threads come from.

Implementations decide how threads are read and how resolution is recorded.
Nothing above this interface knows whether threads came out of a file or an API.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol, runtime_checkable

from thread_resolver.domain.models import DocumentPayload, Thread


@runtime_checkable
class ThreadSource(Protocol):
    """A document whose comment threads can be read and marked resolved."""

    @property
    def name(self) -> str:
        """Identifier of the document, used in reports and run state."""
        ...

    def read_threads(self) -> tuple[Thread, ...]:
        """Every thread in the document, resolved ones included.

        Resolved threads are returned rather than filtered so that a run can
        report what it skipped instead of silently ignoring it.
        """
        ...

    def payload(self) -> DocumentPayload:
        """The current document bytes, for handing to an editing service."""
        ...

    def close_threads(self, thread_ids: Collection[str]) -> DocumentPayload:
        """Return the document with exactly the given threads marked resolved.

        Threads outside `thread_ids` keep whatever state they already had, and
        no other part of the document is rewritten.
        """
        ...
