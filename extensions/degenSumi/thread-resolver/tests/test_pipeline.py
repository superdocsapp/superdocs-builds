"""End-to-end behaviour of a run.

These are the claims the tool makes about itself: that it never edits what it
was not asked to, that it survives being stopped, that it does not pay twice,
that it keeps going when the editing service does not, and that nothing reaches
the document without a decision.
"""

from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from thread_resolver.adapters.cli_review import ReviewAborted
from thread_resolver.adapters.docx_source import DocxThreadSource
from thread_resolver.adapters.fake_editor import FakeEditingService
from thread_resolver.adapters.ooxml import COMMENTS_EXTENDED_PART, DOCUMENT_PART
from thread_resolver.adapters.scripted_review import ScriptedReviewGate, approve_drafted_edits
from thread_resolver.adapters.sqlite_store import SqliteRunStore
from thread_resolver.app.pipeline import Limits, Resolver
from thread_resolver.domain.models import Decision, Disposition, ReviewItem
from thread_resolver.domain.run import Stage
from thread_resolver.ports.review import ReviewGate
from thread_resolver.samples import catalogue
from thread_resolver.samples.builder import build_docx


@pytest.fixture
def store(tmp_path: Path) -> SqliteRunStore:
    return SqliteRunStore(tmp_path / "runs.db")


@pytest.fixture
def source() -> DocxThreadSource:
    return DocxThreadSource(build_docx(catalogue.MIXED_DOCUMENT), "contract.docx")


def build(
    source: DocxThreadSource,
    store: SqliteRunStore,
    gate: ReviewGate,
    editor: FakeEditingService | None = None,
    limits: Limits | None = None,
) -> tuple[Resolver, FakeEditingService]:
    editor = editor or FakeEditingService()
    resolver = Resolver(
        source=source,
        editor=editor,
        store=store,
        gate=gate,
        limits=limits or Limits(),
    )
    return resolver, editor


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


class TestAWholeRun:
    async def test_reaches_the_end(self, source: DocxThreadSource, store: SqliteRunStore) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert state.stage is Stage.DONE

    async def test_drafts_only_actionable_threads(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, editor = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert len(state.actionable) == 1
        assert editor.proposals_made == 1

    async def test_shows_every_item_to_the_gate(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """Contested and quarantined findings are the output, not an omission."""
        gate = ScriptedReviewGate(rule=approve_drafted_edits)
        resolver, _ = build(source, store, gate)
        state = await resolver.run("run-1")

        assert len(gate.seen) == len(state.items) == 4

    async def test_closes_only_the_approved_thread(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await resolver.run("run-1")

        assert resolver.output is not None
        threads = DocxThreadSource(resolver.output.data, "out.docx").read_threads()
        resolved = [t for t in threads if t.resolved]

        # One was already resolved before the run; one was approved during it.
        assert len(resolved) == 2

    async def test_preserves_replies_the_run_did_not_touch(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await resolver.run("run-1")

        assert resolver.output is not None
        threads = DocxThreadSource(resolver.output.data, "out.docx").read_threads()

        assert sum(len(t.replies) for t in threads) == 1

    async def test_touches_only_two_parts_of_the_package(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """The body and the resolution record. Everything else is copied through."""
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await resolver.run("run-1")

        assert resolver.output is not None
        before, after = parts(source.payload().data), parts(resolver.output.data)
        changed = {name for name in before if before[name] != after[name]}

        assert changed == {DOCUMENT_PART, COMMENTS_EXTENDED_PART}
        assert before.keys() == after.keys()


class TestRejection:
    async def test_rejecting_changes_nothing_in_the_body(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=lambda item: Decision.REJECT))
        await resolver.run("run-1")

        assert resolver.output is not None
        before, after = parts(source.payload().data), parts(resolver.output.data)

        assert before == after

    async def test_rejecting_one_does_not_discard_the_rest(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        gate = ScriptedReviewGate(rule=approve_drafted_edits)
        resolver, _ = build(source, store, gate)
        state = await resolver.run("run-1")

        approved = [i for i in state.items if i.decision is Decision.APPROVE]
        deferred = [i for i in state.items if i.decision is Decision.DEFER]

        assert len(approved) == 1
        assert len(deferred) == 3

    async def test_approving_a_finding_without_an_edit_closes_nothing(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """A contested thread cannot be closed by pressing approve."""
        gate = ScriptedReviewGate(rule=lambda item: Decision.APPROVE)
        resolver, _ = build(source, store, gate)
        state = await resolver.run("run-1")

        without_edits = [i for i in state.items if not i.proposed_edits]

        assert all(not item.closes_thread for item in without_edits)
        assert len(state.closable) == 1


class TestSurvivingBeingStopped:
    class AbortingGate:
        """Stands in for the process dying during review."""

        def present(self, items: tuple[ReviewItem, ...]) -> tuple[ReviewItem, ...]:
            raise ReviewAborted("stopped")

    async def test_state_is_kept_when_a_run_stops(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, self.AbortingGate())

        with pytest.raises(ReviewAborted):
            await resolver.run("run-1")

        saved = store.load("run-1")

        assert saved is not None
        assert saved.stage is Stage.REVIEW
        assert len(saved.items) == 4

    async def test_finished_drafts_survive(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, self.AbortingGate())
        with pytest.raises(ReviewAborted):
            await resolver.run("run-1")

        saved = store.load("run-1")

        assert saved is not None
        assert sum(len(item.proposed_edits) for item in saved.items) == 1

    async def test_resuming_does_not_pay_again(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """The claim that matters: a resumed run does not re-draft what it drafted."""
        first, _ = build(source, store, self.AbortingGate())
        with pytest.raises(ReviewAborted):
            await first.run("run-1")

        second, editor = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await second.run("run-1")

        assert editor.proposals_made == 0
        assert state.stage is Stage.DONE

    async def test_a_resumed_run_still_produces_the_right_output(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        first, _ = build(source, store, self.AbortingGate())
        with pytest.raises(ReviewAborted):
            await first.run("run-1")

        second, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await second.run("run-1")

        assert second.output is not None
        threads = DocxThreadSource(second.output.data, "out.docx").read_threads()

        assert sum(1 for t in threads if t.resolved) == 2

    async def test_running_a_finished_run_again_changes_nothing(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, editor = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await resolver.run("run-1")
        spent = editor.proposals_made

        again, editor_again = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await again.run("run-1")

        assert editor_again.proposals_made == 0
        assert spent == 1
        assert state.stage is Stage.DONE


class TestWhenTheServiceFails:
    async def test_a_run_completes_despite_an_outage(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """An unreachable service is not a verdict on the document."""
        editor = FakeEditingService(fail_after=1)
        resolver, _ = build(
            source, store, ScriptedReviewGate(rule=approve_drafted_edits), editor=editor
        )
        state = await resolver.run("run-1")

        assert state.stage is Stage.DONE

    async def test_the_reason_reaches_the_person_reviewing(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        editor = FakeEditingService(fail_after=1)
        resolver, _ = build(
            source, store, ScriptedReviewGate(rule=approve_drafted_edits), editor=editor
        )
        state = await resolver.run("run-1")

        notes = [note for item in state.items for note in item.notes]

        assert any("No edit could be drafted" in note for note in notes)

    async def test_nothing_is_closed_when_no_edit_was_produced(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        editor = FakeEditingService(fail_after=1)
        resolver, _ = build(
            source, store, ScriptedReviewGate(rule=approve_drafted_edits), editor=editor
        )
        state = await resolver.run("run-1")

        assert state.closable == ()

    async def test_a_service_proposing_nothing_closes_nothing(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        """Success from the service is not success on the thread."""
        editor = FakeEditingService(propose_nothing=True)
        resolver, _ = build(
            source, store, ScriptedReviewGate(rule=approve_drafted_edits), editor=editor
        )
        state = await resolver.run("run-1")

        assert state.closable == ()
        assert any("proposed no change" in note for item in state.items for note in item.notes)


class TestHostileContent:
    async def test_a_hostile_comment_never_reaches_the_editing_service(
        self, store: SqliteRunStore
    ) -> None:
        hostile = DocxThreadSource(build_docx(catalogue.INJECTION_COMMENT), "hostile.docx")
        resolver, editor = build(hostile, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert editor.proposals_made == 0
        assert state.items[0].classification.disposition is Disposition.QUARANTINED

    async def test_a_hostile_comment_still_reaches_the_person(self, store: SqliteRunStore) -> None:
        hostile = DocxThreadSource(build_docx(catalogue.INJECTION_COMMENT), "hostile.docx")
        gate = ScriptedReviewGate(rule=approve_drafted_edits)
        resolver, _ = build(hostile, store, gate)
        await resolver.run("run-1")

        assert len(gate.seen) == 1

    async def test_a_hostile_comment_changes_nothing(self, store: SqliteRunStore) -> None:
        hostile = DocxThreadSource(build_docx(catalogue.INJECTION_COMMENT), "hostile.docx")
        resolver, _ = build(hostile, store, ScriptedReviewGate(rule=lambda i: Decision.APPROVE))
        await resolver.run("run-1")

        assert resolver.output is not None
        assert parts(resolver.output.data) == parts(hostile.payload().data)


class TestLimits:
    async def test_max_threads_caps_what_is_looked_at(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(
            source,
            store,
            ScriptedReviewGate(rule=approve_drafted_edits),
            limits=Limits(max_threads=2),
        )
        state = await resolver.run("run-1")

        assert len(state.items) == 2

    async def test_dry_run_contacts_nothing_and_writes_nothing(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, editor = build(
            source,
            store,
            ScriptedReviewGate(rule=approve_drafted_edits),
            limits=Limits(dry_run=True),
        )
        state = await resolver.run("run-1")

        assert editor.calls == []
        assert resolver.output is None
        assert len(state.items) == 4


class TestConcurrentRuns:
    async def test_two_runs_on_one_document_stay_separate(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        first, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        second, _ = build(source, store, ScriptedReviewGate(rule=lambda item: Decision.REJECT))

        await asyncio.gather(first.run("run-a"), second.run("run-b"))

        a, b = store.load("run-a"), store.load("run-b")

        assert a is not None and b is not None
        assert len(a.approved) == 1
        assert len(b.approved) == 0

    async def test_two_documents_at_once_do_not_mix(self, store: SqliteRunStore) -> None:
        one = DocxThreadSource(build_docx(catalogue.MIXED_DOCUMENT), "one.docx")
        two = DocxThreadSource(build_docx(catalogue.SINGLE_ACTIONABLE), "two.docx")

        first, _ = build(one, store, ScriptedReviewGate(rule=approve_drafted_edits))
        second, _ = build(two, store, ScriptedReviewGate(rule=approve_drafted_edits))

        await asyncio.gather(first.run("run-a"), second.run("run-b"))

        a, b = store.load("run-a"), store.load("run-b")

        assert a is not None and b is not None
        assert (a.document_name, len(a.items)) == ("one.docx", 4)
        assert (b.document_name, len(b.items)) == ("two.docx", 1)

    async def test_every_run_is_listed(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        first, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        second, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await asyncio.gather(first.run("run-a"), second.run("run-b"))

        assert {state.run_id for state in store.list_runs()} == {"run-a", "run-b"}


class TestStoredState:
    async def test_state_survives_a_round_trip(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        reloaded = store.load("run-1")

        assert reloaded is not None
        assert reloaded.stage == state.stage
        assert [i.thread_id for i in reloaded.items] == [i.thread_id for i in state.items]
        assert [i.decision for i in reloaded.items] == [i.decision for i in state.items]
        assert [len(i.proposed_edits) for i in reloaded.items] == [
            len(i.proposed_edits) for i in state.items
        ]

    async def test_timings_are_recorded_per_stage(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert {t.stage for t in state.timings} >= {Stage.CLASSIFY, Stage.DRAFT, Stage.APPLY}
        assert state.total_seconds >= 0

    def test_an_unknown_run_is_absent_rather_than_invented(self, store: SqliteRunStore) -> None:
        assert store.load("never-happened") is None


class TestCost:
    """A run reports what it spent, not only how long it took."""

    async def test_operations_spent_are_counted(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, editor = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert state.operations_spent == editor.proposals_made == 1

    async def test_a_run_that_drafts_nothing_spends_nothing(self, store: SqliteRunStore) -> None:
        hostile = DocxThreadSource(build_docx(catalogue.INJECTION_COMMENT), "hostile.docx")
        resolver, _ = build(hostile, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await resolver.run("run-1")

        assert state.operations_spent == 0

    async def test_a_resumed_run_does_not_recount_what_it_already_paid(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        first, _ = build(source, store, TestSurvivingBeingStopped.AbortingGate())
        with pytest.raises(ReviewAborted):
            await first.run("run-1")
        spent = store.load("run-1")
        assert spent is not None

        second, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        state = await second.run("run-1")

        assert state.operations_spent == spent.operations_spent == 1

    async def test_spend_is_recorded_in_the_stored_run(
        self, source: DocxThreadSource, store: SqliteRunStore
    ) -> None:
        resolver, _ = build(source, store, ScriptedReviewGate(rule=approve_drafted_edits))
        await resolver.run("run-1")

        reloaded = store.load("run-1")

        assert reloaded is not None
        assert reloaded.operations_spent == 1
