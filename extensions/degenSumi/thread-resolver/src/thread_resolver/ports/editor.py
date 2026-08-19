"""The seam between the resolver and whatever service performs the edits.

The resolver never writes document prose. It says which passage to change and
what change is wanted, and an editing service produces the replacement text.
That text is held unapplied until a person decides on it.

Methods are asynchronous because a single edit can take minutes to come back,
and a document with many threads is unusable if those waits are serialised.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from thread_resolver.domain.models import DocumentPayload, ProposedEdit


@dataclass(frozen=True, slots=True)
class EditSession:
    """A document opened for editing."""

    session_id: str
    document_name: str


@dataclass(frozen=True, slots=True)
class Proposal:
    """Changes offered for one instruction, not yet applied."""

    job_id: str
    session_id: str
    edits: tuple[ProposedEdit, ...]

    @property
    def is_empty(self) -> bool:
        """True when the service found nothing to change.

        Reported as such rather than treated as success, so that a thread which
        produced no edit is never closed as though it had.
        """
        return not self.edits


@dataclass(frozen=True, slots=True)
class Usage:
    """Operations consumed on the account, as reported by the service.

    A running total for the billing period rather than for one run, so the cost
    of a run is the difference between two readings.
    """

    used: int
    limit: int
    remaining: int


class EditingError(Exception):
    """A failure that leaves the document unchanged."""


class EditingUnavailable(EditingError):
    """The service could not be reached or did not answer in time.

    Distinguished from a rejected request so that callers can degrade rather
    than treat an outage as a verdict on the document.
    """


@runtime_checkable
class EditingService(Protocol):
    async def open_document(self, payload: DocumentPayload) -> EditSession:
        """Upload a document and start a session for it."""
        ...

    async def propose_edit(self, session: EditSession, instruction: str) -> Proposal:
        """Request a change and wait for the proposed result.

        Returns once the service is holding changes for approval. Nothing is
        applied to the document by this call.
        """
        ...

    async def decide(self, proposal: Proposal, decisions: Mapping[str, bool]) -> None:
        """Apply approved changes and discard rejected ones.

        Every change in the proposal must appear in `decisions`. Deciding on a
        subset would leave the rest in an unstated state.
        """
        ...

    async def export(self, session: EditSession, file_format: str = "docx") -> DocumentPayload:
        """Render the document in its current state."""
        ...

    async def usage(self) -> Usage | None:
        """What has been spent so far, where the service reports it."""
        ...
