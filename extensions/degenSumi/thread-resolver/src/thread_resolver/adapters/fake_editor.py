"""An editing service that answers from local rules instead of a network.

Used to exercise the whole pipeline without a key and without spending
operations. It is a working stand-in rather than a recording of expected calls:
it holds real state, applies decisions, and refuses the same things the real
service refuses, so a test that passes here is testing the pipeline rather than
the arrangement of a mock.

Failure can be requested deliberately, because how the pipeline behaves when the
service is unreachable is a behaviour worth testing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping

from thread_resolver.domain.models import DocumentPayload, ProposedEdit
from thread_resolver.ports.editor import (
    EditingService,
    EditingUnavailable,
    EditSession,
    Proposal,
    Usage,
)

_QUOTED_PASSAGE = re.compile(r'begins "(.*?)(?:\.\.\.)?"', re.DOTALL)
_NUMBER_WORDS = {
    "thirty": "fifteen",
    "sixty": "thirty",
    "twelve": "six",
    "ninety": "sixty",
}


class FakeEditingService(EditingService):
    """A deterministic editing service backed by an in-memory document."""

    def __init__(
        self,
        *,
        fail_after: int | None = None,
        latency: float = 0.0,
        propose_nothing: bool = False,
    ) -> None:
        self._sessions: dict[str, DocumentPayload] = {}
        self._proposals: dict[str, Proposal] = {}
        self._applied: dict[str, list[ProposedEdit]] = {}
        self._fail_after = fail_after
        self._latency = latency
        self._propose_nothing = propose_nothing
        self._counter = 0

        self.calls: list[str] = []
        """Ordered record of operations, for asserting what a run actually did."""

    # -- port ---------------------------------------------------------------

    async def open_document(self, payload: DocumentPayload) -> EditSession:
        await self._tick("open_document")
        session_id = f"fake-session-{len(self._sessions) + 1}"
        self._sessions[session_id] = payload
        self._applied[session_id] = []
        return EditSession(session_id=session_id, document_name=payload.filename)

    async def propose_edit(self, session: EditSession, instruction: str) -> Proposal:
        await self._tick("propose_edit")
        self._counter += 1
        job_id = f"fake-job-{self._counter}"

        edits: tuple[ProposedEdit, ...] = ()
        if not self._propose_nothing:
            passage = _passage_from(instruction)
            replacement = _rewrite(passage)
            if replacement is not None:
                edits = (
                    ProposedEdit(
                        change_id=f"ch_{self._counter}",
                        chunk_id=f"chunk_{self._counter}",
                        operation="edit",
                        old_html=f"<p>{passage}</p>",
                        new_html=f"<p>{replacement}</p>",
                        explanation="Applied the editorial note to the named passage.",
                    ),
                )

        proposal = Proposal(job_id=job_id, session_id=session.session_id, edits=edits)
        self._proposals[job_id] = proposal
        return proposal

    async def decide(self, proposal: Proposal, decisions: Mapping[str, bool]) -> None:
        await self._tick("decide")
        known = {edit.change_id for edit in proposal.edits}
        undecided = known - set(decisions)
        if undecided:
            raise ValueError(f"no decision given for {sorted(undecided)}")

        approved = [edit for edit in proposal.edits if decisions.get(edit.change_id)]
        self._applied.setdefault(proposal.session_id, []).extend(approved)

    async def export(self, session: EditSession, file_format: str = "docx") -> DocumentPayload:
        await self._tick("export")
        return self._sessions[session.session_id]

    async def usage(self) -> Usage | None:
        spent = sum(1 for call in self.calls if call == "propose_edit")
        return Usage(used=spent, limit=500, remaining=500 - spent)

    # -- inspection ---------------------------------------------------------

    def applied_edits(self, session_id: str) -> tuple[ProposedEdit, ...]:
        return tuple(self._applied.get(session_id, ()))

    @property
    def proposals_made(self) -> int:
        return sum(1 for call in self.calls if call == "propose_edit")

    # -- internals ----------------------------------------------------------

    async def _tick(self, name: str) -> None:
        self.calls.append(name)
        if self._fail_after is not None and len(self.calls) > self._fail_after:
            raise EditingUnavailable(
                f"the fake editing service was configured to fail after {self._fail_after} calls"
            )
        if self._latency:
            await asyncio.sleep(self._latency)


def _passage_from(instruction: str) -> str:
    """Recover the passage the instruction names, mirroring how it was composed."""
    match = _QUOTED_PASSAGE.search(instruction)
    return match.group(1) if match else ""


def _rewrite(passage: str) -> str | None:
    """A small deterministic edit, so a proposal has real before and after text."""
    for word, replacement in _NUMBER_WORDS.items():
        if word in passage.lower():
            return re.sub(word, replacement, passage, count=1, flags=re.IGNORECASE)
    return f"{passage.rstrip('.')} (revised)." if passage else None
