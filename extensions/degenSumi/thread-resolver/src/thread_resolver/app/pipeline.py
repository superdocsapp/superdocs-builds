"""The stage machine.

Stages run in order and each one is checkpointed as it completes, so a run that
is killed continues from the last completed stage. Work already paid for is
never repeated: drafting skips threads that already carry a proposal, which is
what stops a resumed run spending a second operation on the same thread.

Nothing is written to the document until a person has decided on every item, and
only approved items produce a change. A thread is closed only when its own edit
was approved.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from thread_resolver.adapters.docx_source import DocxThreadSource
from thread_resolver.adapters.docx_writer import (
    WriteBackError,
    apply_changes,
    html_to_text,
)
from thread_resolver.domain.classify import classify
from thread_resolver.domain.models import DocumentPayload, ReviewItem
from thread_resolver.domain.run import RunState, Stage
from thread_resolver.ports.editor import EditingError, EditingService, EditSession
from thread_resolver.ports.judge import Judge
from thread_resolver.ports.review import ReviewGate
from thread_resolver.ports.store import RunStore


@dataclass(frozen=True, slots=True)
class Limits:
    """Ceilings on what one run may do."""

    max_threads: int | None = None
    """Stop after this many open threads. Caps spend while trying things out."""

    concurrency: int = 4
    """Drafts in flight at once. Each edit can take minutes, so waits overlap."""

    dry_run: bool = False
    """Classify and report, contacting no editing service and writing no file."""


class Resolver:
    def __init__(
        self,
        *,
        source: DocxThreadSource,
        editor: EditingService,
        store: RunStore,
        gate: ReviewGate,
        judge: Judge | None = None,
        limits: Limits | None = None,
    ) -> None:
        self._source = source
        self._editor = editor
        self._store = store
        self._gate = gate
        self._judge = judge
        self._limits = limits or Limits()
        self._save_lock = asyncio.Lock()

    async def run(self, run_id: str) -> RunState:
        state = self._store.load(run_id) or RunState(run_id=run_id, document_name=self._source.name)

        state = await self._classify(state)
        state = await self._draft(state)
        state = self._review(state)
        state = self._apply_and_close(state)

        return state

    # -- stages -------------------------------------------------------------

    async def _classify(self, state: RunState) -> RunState:
        if _already_past(state, Stage.CLASSIFY):
            return state

        with self._timed(state, Stage.CLASSIFY) as timing:
            threads = self._source.read_threads()
            open_threads = [t for t in threads if t.is_open]
            if self._limits.max_threads is not None:
                open_threads = open_threads[: self._limits.max_threads]

            items = tuple(
                ReviewItem(thread=thread, classification=classify(thread, self._judge))
                for thread in open_threads
            )
            state = timing.finish(state.with_items(items).advance_to(Stage.DRAFT))

        self._store.save(state)
        return state

    async def _draft(self, state: RunState) -> RunState:
        if _already_past(state, Stage.DRAFT):
            return state
        if self._limits.dry_run:
            return self._checkpoint(state.advance_to(Stage.REVIEW))

        pending = state.needs_drafting
        if not pending:
            return self._checkpoint(state.advance_to(Stage.REVIEW))

        with self._timed(state, Stage.DRAFT) as timing:
            session = await self._open_session(state)
            state = state.with_session(session.session_id)

            before = await self._read_usage()

            semaphore = asyncio.Semaphore(self._limits.concurrency)
            results = await asyncio.gather(
                *(self._draft_one(session, item, semaphore) for item in pending)
            )
            for updated in results:
                state = state.replace_item(updated)
                # Saved as each lands, so a kill mid-stage keeps finished drafts.
                self._store.save(state)

            state = state.spending(await self._spend_since(before))
            state = timing.finish(state.advance_to(Stage.REVIEW))

        self._store.save(state)
        return state

    def _review(self, state: RunState) -> RunState:
        if _already_past(state, Stage.REVIEW):
            return state
        if self._limits.dry_run:
            # Nothing will be written, so there is nothing to decide.
            return self._checkpoint(state.advance_to(Stage.APPLY))

        with self._timed(state, Stage.REVIEW) as timing:
            decided = self._gate.present(state.items)
            missing = [item.thread_id for item in decided if not item.is_decided]
            if missing:
                raise ReviewIncomplete(
                    f"the review gate returned no decision for {missing}. "
                    "Every item must be decided before anything is written."
                )
            state = timing.finish(state.with_items(decided).advance_to(Stage.APPLY))

        self._store.save(state)
        return state

    def _apply_and_close(self, state: RunState) -> RunState:
        if _already_past(state, Stage.APPLY) or self._limits.dry_run:
            return self._checkpoint(state.advance_to(Stage.DONE))

        with self._timed(state, Stage.APPLY) as timing:
            self._write_output(state)
            state = timing.finish(state.advance_to(Stage.DONE))

        self._store.save(state)
        return state

    # -- work ---------------------------------------------------------------

    async def _read_usage(self) -> int | None:
        """Operations consumed on the account so far, if the service reports it.

        Failure to read is not failure to run, so an error here is swallowed and
        the run simply reports no spend rather than stopping over a statistic.
        """
        try:
            usage = await self._editor.usage()
        except EditingError:
            return None
        return None if usage is None else usage.used

    async def _spend_since(self, before: int | None) -> int:
        """What this stage cost, as the difference between two readings."""
        if before is None:
            return 0
        after = await self._read_usage()
        return 0 if after is None else max(0, after - before)

    async def _open_session(self, state: RunState) -> EditSession:
        if state.session_id is not None:
            return EditSession(session_id=state.session_id, document_name=self._source.name)
        return await self._editor.open_document(self._source.payload())

    async def _draft_one(
        self, session: EditSession, item: ReviewItem, semaphore: asyncio.Semaphore
    ) -> ReviewItem:
        instruction = item.classification.instruction
        if instruction is None:
            return item

        async with semaphore:
            try:
                proposal = await self._editor.propose_edit(session, instruction)
            except EditingError as error:
                # An outage is not a verdict on the thread. The item survives
                # undrafted and reaches the gate carrying the reason.
                return _annotate(item, f"No edit could be drafted: {error}")

        if proposal.is_empty:
            return _annotate(item, "The editing service proposed no change for this thread.")

        return ReviewItem(
            thread=item.thread,
            classification=item.classification,
            proposed_edits=proposal.edits,
            decision=item.decision,
            job_id=proposal.job_id,
            session_id=proposal.session_id,
            notes=item.notes,
        )

    def _write_output(self, state: RunState) -> None:
        """Write approved changes into the original file, then close their threads.

        Both steps rewrite one part of the package and copy the rest through, so
        threads and replies the run never touched are preserved exactly.
        """
        changes: dict[str, str] = {}
        for item in state.approved:
            for edit in item.proposed_edits:
                before = html_to_text(edit.old_html)
                after = html_to_text(edit.new_html)
                if before and before != after:
                    changes[before] = after

        data = self._source.payload().data
        if changes:
            data = apply_changes(data, changes)

        closing = [item.thread_id for item in state.closable]
        if closing:
            data = DocxThreadSource(data, self._source.name).close_threads(closing).data

        self._output = DocumentPayload(filename=self._source.name, data=data)

    @property
    def output(self) -> DocumentPayload | None:
        """The finished document, once a run has reached the end."""
        return getattr(self, "_output", None)

    # -- plumbing -----------------------------------------------------------

    def _checkpoint(self, state: RunState) -> RunState:
        self._store.save(state)
        return state

    @contextmanager
    def _timed(self, state: RunState, stage: Stage) -> Iterator[_Timing]:
        timing = _Timing(stage=stage, started=time.monotonic())
        yield timing


class ReviewIncomplete(Exception):
    """Raised when the gate returned items without decisions."""


class _Timing:
    __slots__ = ("stage", "started")

    def __init__(self, stage: Stage, started: float) -> None:
        self.stage = stage
        self.started = started

    def finish(self, state: RunState) -> RunState:
        return state.with_timing(self.stage, round(time.monotonic() - self.started, 3))


def _already_past(state: RunState, stage: Stage) -> bool:
    from thread_resolver.domain.run import STAGE_ORDER

    return STAGE_ORDER.index(state.stage) > STAGE_ORDER.index(stage)


def _annotate(item: ReviewItem, note: str) -> ReviewItem:
    return ReviewItem(
        thread=item.thread,
        classification=item.classification,
        proposed_edits=item.proposed_edits,
        decision=item.decision,
        job_id=item.job_id,
        session_id=item.session_id,
        notes=(*item.notes, note),
    )


__all__ = ["Limits", "Resolver", "ReviewIncomplete", "WriteBackError"]
