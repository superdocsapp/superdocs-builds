"""HITL validation gate tests — SuperDocs proposes, our validator decides.

Two layers: validator unit tests (pure rules, no network) and session
integration tests (a HITL-aware fake drives the full gated pipeline).
"""

import asyncio

from app.drafting.classifier import ADDITION, CORRECTION, SectionOperation, build_section_operations
from app.drafting.session import STATUS_BLOCKED, STATUS_COMPLETED, STATUS_ERROR, MeetingSession
from app.drafting.validator import validate_correction, validate_proposal
from app.superdocs.schemas import (
    ChatAsyncResponse,
    ChunkDiff,
    DocumentChanges,
    JobMetadata,
    JobResult,
    JobStatusResponse,
    PendingChange,
    UploadResponse,
)
from app.transcript.manual_provider import ManualTranscriptProvider

from test_session import FakeSuperDocsClient, _session

# Template with chunk-id-bearing section bodies so the validator can map
# chunk ids to section boundaries.
GATE_HEADINGS = (
    "<h1>Statement of Work</h1>"
    "<h2>Timeline &amp; Milestones</h2>"
    '<div data-chunk-id="ch-timeline"><p></p></div>'
    "<h2>Budget / Commercial Terms</h2>"
    '<div data-chunk-id="ch-budget"><p></p></div>'
    "<h2>Out of Scope</h2>"
    '<div data-chunk-id="ch-oos"><p></p></div>'
)


def _place(html: str, chunk_id: str, content: str) -> str:
    """Test helper: insert `content` inside the named chunk's own div,
    replacing its empty placeholder — mirrors where a real SuperDocs edit
    actually lands (within the target section), rather than the shortcut
    of tacking new content onto the end of the whole document string. The
    placement-integrity check (`content_landed_in_section`) cares which
    heading's boundary content falls inside, so a fixture that fakes
    placement by concatenation would trip it on a section swap that never
    really happened."""
    return html.replace(
        f'<div data-chunk-id="{chunk_id}"><p></p></div>',
        f'<div data-chunk-id="{chunk_id}">{content}</div>',
        1,
    )


def _op(text, draft=GATE_HEADINGS, classification=ADDITION):
    ops = build_section_operations(classification, text, draft, "statement_of_work")
    return ops[0]


def _change(**kw):
    defaults = {
        "change_id": "c1",
        "operation": "create",
        "chunk_id": "new",
        "old_html": None,
        "new_html": "<p>content</p>",
        "ai_explanation": "added content",
    }
    defaults.update(kw)
    return PendingChange(**defaults)


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------

def test_valid_timeline_proposal_accepted():
    op = _op("The project starts September 15th and the final website should be delivered by October 30th.")
    change = _change(new_html="<p>Project starts September 15th, final website delivered by October 30th.</p>")
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert ok, fails


def test_proposal_missing_expected_fact_rejected():
    op = _op("The project starts September 15th and the final website should be delivered by October 30th.")
    change = _change(new_html="<p>The project starts September 15th.</p>")  # October missing
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert not ok
    assert any("missing expected content" in f for f in fails)


def test_heading_mutation_rejected():
    op = _op("The project starts September 15th.")
    change = _change(new_html="<h2>Timeline, September 15th, and the Final</h2><p>stuff</p>")
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert not ok
    assert any("heading" in f for f in fails)


def test_placeholder_rejected():
    op = _op("The project starts September 15th.")
    change = _change(new_html="<p>Start date September 15th. Please fill: delivery date</p>")
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert not ok
    assert any("placeholder" in f.lower() for f in fails)


def test_new_table_rejected():
    op = _op("The project starts September 15th.")
    change = _change(new_html="<table><tr><td>September 15th</td></tr></table>")
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert not ok
    assert any("table" in f for f in fails)


def test_chunk_outside_target_section_rejected():
    op = _op("The project starts September 15th.")  # targets Timeline
    change = _change(
        operation="edit",
        chunk_id="ch-budget",  # lives in the Budget section body, not Timeline
        old_html="<p>old</p>",
        new_html="<p>The project starts September 15th.</p>",
    )
    ok, fails = validate_proposal(op, change, GATE_HEADINGS)
    assert not ok
    assert any("outside section" in f for f in fails)


def test_foreign_fact_contamination_rejected():
    op = _op("The project starts September 15th.")
    change = _change(new_html="<p>Start September 15th. The budget is forty-five thousand dollars.</p>")
    ok, fails = validate_proposal(op, change, GATE_HEADINGS, foreign_tokens=["budget", "forty"])
    assert not ok
    assert any("another section" in f for f in fails)


def test_correction_valid_old_new_replacement_accepted():
    op = _op("Actually, the start date is September 20th, not September 15th.", classification=CORRECTION)
    change = _change(
        operation="edit",
        chunk_id="ch-timeline",
        old_html='<div data-chunk-id="ch-timeline"><p>Start on <strong>September 15th</strong>.</p></div>',
        new_html='<div data-chunk-id="ch-timeline"><p>Start on <strong>September 20th</strong>.</p></div>',
    )
    ok, fails = validate_correction(op, change, GATE_HEADINGS, "September 15th", "September 20th")
    assert ok, fails


def test_correction_old_value_not_in_old_html_rejected():
    op = _op("Actually, the start date is September 20th, not September 15th.", classification=CORRECTION)
    change = _change(
        operation="edit",
        chunk_id="ch-timeline",
        old_html="<p>Start on September 10th.</p>",
        new_html="<p>Start on September 20th.</p>",
    )
    ok, fails = validate_correction(op, change, GATE_HEADINGS, "September 15th", "September 20th")
    assert not ok
    assert any("old_html" in f for f in fails)


def test_correction_keeps_old_value_rejected():
    op = _op("Actually, the start date is September 20th, not September 15th.", classification=CORRECTION)
    change = _change(
        operation="edit",
        chunk_id="ch-timeline",
        old_html="<p>Start on September 15th.</p>",
        new_html="<p>Start on September 20th or September 15th.</p>",
    )
    ok, fails = validate_correction(op, change, GATE_HEADINGS, "September 15th", "September 20th")
    assert not ok
    assert any("keeps the old value" in f for f in fails)


# ---------------------------------------------------------------------------
# validate_table_fill — Project Details table-cell fill (Client)
# ---------------------------------------------------------------------------

from app.drafting.classifier import SectionOperation
from app.drafting.validator import validate_table_fill

TABLE_OLD = (
    '<table><tr><td><strong>Client</strong></td><td></td></tr>'
    '<tr><td><strong>Project</strong></td><td></td></tr>'
    '<tr><td><strong>Date</strong></td><td>August 13, 2026</td></tr>'
    '<tr><td><strong>Prepared by</strong></td><td></td></tr></table>'
)


def _table_op(field="Client", value="Northstar"):
    return SectionOperation(
        instruction="fill it in", section="Project Details", facts=[value],
        table_field=field, table_value=value,
    )


def test_table_fill_valid_single_cell_change_accepted():
    new_html = TABLE_OLD.replace(
        "<tr><td><strong>Client</strong></td><td></td></tr>",
        "<tr><td><strong>Client</strong></td><td>Northstar</td></tr>",
    )
    change = _change(chunk_id="tbl", old_html=TABLE_OLD, new_html=new_html)
    ok, fails = validate_table_fill(_table_op(), change)
    assert ok, fails


def test_table_fill_rejects_row_count_change():
    new_html = TABLE_OLD.replace(
        "</table>",
        "<tr><td><strong>Extra</strong></td><td>x</td></tr></table>",
    ).replace(
        "<tr><td><strong>Client</strong></td><td></td></tr>",
        "<tr><td><strong>Client</strong></td><td>Northstar</td></tr>",
    )
    change = _change(chunk_id="tbl", old_html=TABLE_OLD, new_html=new_html)
    ok, fails = validate_table_fill(_table_op(), change)
    assert not ok
    assert any("row count changed" in f for f in fails)


def test_table_fill_rejects_wrong_field_changed():
    # Project changed instead of Client.
    new_html = TABLE_OLD.replace(
        "<tr><td><strong>Project</strong></td><td></td></tr>",
        "<tr><td><strong>Project</strong></td><td>Website Revamp</td></tr>",
    )
    change = _change(chunk_id="tbl", old_html=TABLE_OLD, new_html=new_html)
    ok, fails = validate_table_fill(_table_op(field="Client", value="Northstar"), change)
    assert not ok
    assert any("wrong field changed" in f for f in fails)


def test_table_fill_rejects_wrong_value():
    new_html = TABLE_OLD.replace(
        "<tr><td><strong>Client</strong></td><td></td></tr>",
        "<tr><td><strong>Client</strong></td><td>Someone Else</td></tr>",
    )
    change = _change(chunk_id="tbl", old_html=TABLE_OLD, new_html=new_html)
    ok, fails = validate_table_fill(_table_op(field="Client", value="Northstar"), change)
    assert not ok
    assert any("expected value" in f for f in fails)


def test_table_fill_rejects_other_row_also_changed():
    new_html = TABLE_OLD.replace(
        "<tr><td><strong>Client</strong></td><td></td></tr>",
        "<tr><td><strong>Client</strong></td><td>Northstar</td></tr>",
    ).replace(
        "<tr><td><strong>Project</strong></td><td></td></tr>",
        "<tr><td><strong>Project</strong></td><td>Snuck In</td></tr>",
    )
    change = _change(chunk_id="tbl", old_html=TABLE_OLD, new_html=new_html)
    ok, fails = validate_table_fill(_table_op(), change)
    assert not ok
    assert any("exactly one changed cell" in f for f in fails)


# ---------------------------------------------------------------------------
# Session integration tests — the gated pipeline with a HITL-aware fake
# ---------------------------------------------------------------------------

class HITLFake(FakeSuperDocsClient):
    """Fake whose jobs pause at awaiting_approval with scripted proposal
    rounds, then complete with scripted updated HTML once approved."""

    def __init__(self, rounds=None, htmls=None):
        FakeSuperDocsClient.__init__(self)
        self.rounds: list[list[dict]] = rounds or []
        self.htmls: list[str] = htmls or []
        self.approval_calls: list[dict] = []
        self.revert_calls: list[dict] = []
        self.detail_calls = 0
        self.structure_override: list[str] | None = None
        self._awaiting = False
        self._round = 0
        self._job_html: dict[str, int] = {}
        self._html_count = 0
        self._job_rounds: dict[str, int] = {}
        # Jobs that were denied. Mirrors the live API: approve_changes(False)
        # is accepted but the job stays open until polled — at which point it
        # has settled to a terminal (cancelled) state, releasing the session
        # for the next chat. A fresh chat_async issued while a denied job is
        # still open is what the real API 409s on.
        self._denied: set[str] = set()

    async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
        await asyncio.sleep(0)
        self.upload_calls += 1
        return UploadResponse(session_id=session_id, html=GATE_HEADINGS)

    async def chat_async(self, *, message, session_id, approval_mode="auto", model_tier=None, thinking_depth=None):
        await asyncio.sleep(0)
        self.chat_messages.append(message)
        assert approval_mode == "ask_every_time", f"expected ask_every_time, got {approval_mode}"
        self._job_counter += 1
        self._awaiting = True
        self._round = 0
        self._job_html[f"job{self._job_counter}"] = self._html_count
        self._html_count += 1
        self._job_rounds[f"job{self._job_counter}"] = self._job_counter - 1
        return ChatAsyncResponse(job_id=f"job{self._job_counter}", session_id=session_id)

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        if job_id in self._denied:
            # A denied job has settled to terminal — the session is released.
            return JobStatusResponse(job_id=job_id, status="cancelled")
        base = self._job_rounds.get(job_id, 0)
        idx = base + self._round
        if self._awaiting and idx < len(self.rounds):
            changes = [PendingChange(**c) for c in self.rounds[idx]]
            return JobStatusResponse(
                job_id=job_id, status="awaiting_approval",
                metadata=JobMetadata(pending_changes=changes),
            )
        if self._awaiting:
            # Rounds exhausted — mimic the real API's deny completion: the
            # job finishes with no document changes.
            self._awaiting = False
            return JobStatusResponse(job_id=job_id, status="completed", result=None)
        idx = self._job_html.get(job_id, 0)
        if self.htmls:
            idx = min(idx, len(self.htmls) - 1)  # retries share the final html
            html = self.htmls[idx]
        else:
            html = self.next_updated_html
        return JobStatusResponse(
            job_id=job_id, status="completed",
            result=JobResult(document_changes=DocumentChanges(
                updated_html=html,
                changes=[ChunkDiff(operation="update", chunk_id="c1")],
            )),
        )

    async def approve_changes(self, *, session_id, job_id, approved, changes=None, feedback=None):
        await asyncio.sleep(0)
        self.approval_calls.append({"approved": approved, "changes": changes, "feedback": feedback})
        if approved:
            self._awaiting = False
        else:
            # Deny accepted; the job settles to cancelled (modeled in get_job).
            self._denied.add(job_id)
            self._round += 1
            base = self._job_rounds.get(job_id, 0)
            if base + self._round >= len(self.rounds):
                self._awaiting = False
        return {"status": "ok"}

    async def get_session_documents(self, *, session_id):
        await asyncio.sleep(0)
        return [{"document_id": "doc_primary", "durable_document_id": "dur-1"}]

    async def get_document_detail(self, *, document_id):
        await asyncio.sleep(0)
        self.detail_calls += 1
        if self.structure_override is not None:
            headings = self.structure_override
        else:
            from app.drafting.classifier import _draft_headings
            html = self.htmls[-1] if self.htmls else GATE_HEADINGS
            headings = _draft_headings(html)
        return {"structure": {"headings": [{"text": h} for h in headings]}}

    async def revert_session(self, *, session_id, turn_index):
        await asyncio.sleep(0)
        self.revert_calls.append({"session_id": session_id, "turn_index": turn_index})
        return {"reverted_to_turn": turn_index - 1}


def _gate_session(client) -> tuple[MeetingSession, ManualTranscriptProvider]:
    provider = ManualTranscriptProvider()
    session = MeetingSession(
        "test-gate-uuid",
        client,
        provider,
        manual_provider=provider,
        silence_gap_seconds=0.05,
        size_ceiling_chars=10_000,
        max_wait_seconds=10,
        poll_interval_seconds=0.01,
    )
    return session, provider


def test_valid_proposal_approved_and_applied():
    client = HITLFake(
        rounds=[[{"change_id": "c1", "operation": "create", "chunk_id": "new",
                  "new_html": "<p>The project starts on September 15th and the final website is delivered by October 30th.</p>",
                  "ai_explanation": "added to Timeline"}]],
        htmls=[_place(GATE_HEADINGS, "ch-timeline",
                       "<p>The project starts September 15th and the final website is delivered by October 30th.</p>")],
    )

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th and the final website should be delivered by October 30th.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_COMPLETED
    assert session.draft_version == 1
    assert client.approval_calls[-1]["approved"] is True
    assert "September 15th" in session.current_draft_html


def test_wrong_section_proposal_rejected_then_revised():
    # Round 1: targets the wrong chunk (Budget). Round 2: correct (Timeline).
    bad = {"change_id": "c1", "operation": "edit", "chunk_id": "ch-budget",
           "old_html": "<p>old</p>", "new_html": "<p>The project starts September 15th.</p>",
           "ai_explanation": "added to Budget"}
    good = {"change_id": "c2", "operation": "create", "chunk_id": "new",
            "new_html": "<p>The project starts September 15th and the final website is delivered by October 30th.</p>",
            "ai_explanation": "added to Timeline"}
    client = HITLFake(
        rounds=[[bad], [good]],
        htmls=[_place(GATE_HEADINGS, "ch-timeline",
                       "<p>The project starts September 15th and the final website is delivered by October 30th.</p>")],
    )

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th and the final website should be delivered by October 30th.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_COMPLETED
    assert client.approval_calls[0]["approved"] is False  # rejected
    assert "feedback" in client.approval_calls[0]
    assert client.approval_calls[1]["approved"] is True   # revised accepted
    assert session.draft_version == 1


def test_all_rounds_rejected_batch_fails_and_rolls_back():
    bad = {"change_id": "c1", "operation": "edit", "chunk_id": "ch-budget",
           "old_html": "<p>old</p>", "new_html": "<p>The project starts September 15th.</p>",
           "ai_explanation": "added to Budget"}
    client = HITLFake(rounds=[[bad], [bad], [bad]], htmls=[GATE_HEADINGS + "<p>bad</p>"])

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        # 3 batch attempts × 3 op attempts with backoff must exhaust
        await asyncio.sleep(1.5)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_ERROR
    assert session.draft_version == 0
    assert session.current_draft_html == GATE_HEADINGS  # no partial draft exposed
    # No revert assertion. Every round was DENIED, so nothing was ever applied
    # and there is nothing to rewind. Reverting a just-denied session returns
    # 409 and then wedges every later chat_async — observed killing a live
    # meeting on 2026-08-21, six batches queued behind a dead session. A revert
    # belongs only where an edit was applied and then failed a check.
    assert not client.revert_calls, "a denied proposal must not trigger a revert"


def test_multi_section_batch_sequential_ops_one_logical_update():
    text = ("The project starts September 15th. "
            "Our total budget is forty-five thousand dollars. "
            "Payment integration is not part of the scope.")
    timeline = {"change_id": "c1", "operation": "create", "chunk_id": "new",
                "new_html": "<p>The project starts September 15th.</p>", "ai_explanation": "Timeline"}
    budget = {"change_id": "c2", "operation": "create", "chunk_id": "new",
              "new_html": "<p>Total budget is forty-five thousand dollars.</p>", "ai_explanation": "Budget"}
    oos = {"change_id": "c3", "operation": "create", "chunk_id": "new",
           "new_html": "<p>Payment integration is excluded from the scope.</p>", "ai_explanation": "Out of Scope"}
    html_1 = _place(GATE_HEADINGS, "ch-timeline", "<p>The project starts September 15th.</p>")
    html_2 = _place(html_1, "ch-budget", "<p>Total budget is forty-five thousand dollars.</p>")
    html_3 = _place(html_2, "ch-oos", "<p>Payment integration is excluded from the scope.</p>")
    client = HITLFake(
        rounds=[[timeline], [budget], [oos]],
        htmls=[html_1, html_2, html_3],
    )

    async def run():
        session, provider = _gate_session(client)
        queue = session.subscribe()
        events = []

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit(text)
        await asyncio.sleep(0.3)
        drain_task.cancel()
        return session, events

    session, events = asyncio.run(run())
    assert len(client.chat_messages) == 3  # three sequential operations
    assert session.job_status == STATUS_COMPLETED
    assert session.draft_version == 1      # one logical batch → one version
    assert len(session.activity) == 1      # one activity entry
    assert "September 15th" in session.current_draft_html
    assert "forty-five thousand dollars" in session.current_draft_html
    assert "Payment integration" in session.current_draft_html
    draft_updates = [e for e in events if e["type"] == "draft_updated"]
    assert [e["draft_version"] for e in draft_updates] == [0, 1]  # init + one batch


def test_structure_verification_failure_rolls_back():
    client = HITLFake(
        rounds=[[{"change_id": "c1", "operation": "create", "chunk_id": "new",
                  "new_html": "<p>The project starts September 15th.</p>", "ai_explanation": "Timeline"}]],
        htmls=[_place(GATE_HEADINGS, "ch-timeline", "<p>The project starts September 15th.</p>")],
    )
    client.structure_override = ["Statement of Work", "Something Else"]  # heading lost

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        # 3 batch attempts × 3 transport attempts with backoff must exhaust
        await asyncio.sleep(30)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_ERROR
    assert session.draft_version == 0
    assert session.current_draft_html == GATE_HEADINGS
    assert client.detail_calls >= 1
    assert client.revert_calls, "structure failure must revert"


def test_later_operation_dropping_earlier_content_rolls_back():
    # Op 2's output silently drops op 1's committed content — the batch
    # must fail and roll back rather than present a partial document.
    timeline = {"change_id": "c1", "operation": "create", "chunk_id": "new",
                "new_html": "<p>The project starts September 15th.</p>", "ai_explanation": "Timeline"}
    budget = {"change_id": "c2", "operation": "create", "chunk_id": "new",
              "new_html": "<p>Total budget is forty-five thousand dollars.</p>", "ai_explanation": "Budget"}
    client = HITLFake(
        rounds=[[timeline], [budget]],
        htmls=[
            GATE_HEADINGS + "<p>The project starts September 15th.</p>",
            # BUG SIMULATION: op 2's html lost the timeline content
            GATE_HEADINGS + "<p>Total budget is forty-five thousand dollars.</p>",
        ],
    )

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is forty-five thousand dollars.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    # An operation is the unit of commit now. The first operation (Timeline)
    # succeeded and KEEPS its content; the second dropped it and is reverted
    # on its own. The old contract — roll the whole batch back — is what made
    # a single late failure produce a completely empty document live.
    assert "September 15th" in session.current_draft_html
    assert session.draft_version == 1
    assert session.error and "could not be added" in session.error
    # Deliberately NOT asserting a revert here. An operation the gate denied
    # was never applied, so there is nothing to rewind — and reverting anyway
    # 409s against the just-settled denial and wedges the whole session, which
    # is exactly how a live meeting died on 2026-08-21.


def test_structural_placeholder_rejection_gets_at_most_one_retry():
    # A structural defect (placeholder) must not burn the full 3-attempt
    # budget — one explicit-constraint retry, then the op fails and the
    # batch retry (fresh run) or error path takes over.
    bad = {"change_id": "c1", "operation": "create", "chunk_id": "new",
           "new_html": "<p>Start September 15th. Please fill: delivery date</p>",
           "ai_explanation": "Timeline"}
    client = HITLFake(
        rounds=[[bad], [bad], [bad], [bad], [bad], [bad]],
        htmls=[GATE_HEADINGS + "<p>never</p>"],
    )

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(1.0)
        return session, client

    session, client = asyncio.run(run())
    # 2 attempts on the operation (original + 1 structural retry). The outer
    # batch-level retry is gone: _run_gated_operation already retries each
    # operation, so replaying the whole batch on top of committed operations
    # was a second layer that produced duplicate paragraphs.
    assert len(client.chat_messages) == 2
    assert session.job_status == STATUS_ERROR
    assert session.draft_version == 0
    assert session.current_draft_html == GATE_HEADINGS


def test_repeated_structural_failure_never_commits_partial_batch():
    # Same structural defect twice on one op → immediate fail → batch retry
    # re-runs from a fresh state; atomicity preserved throughout.
    bad = {"change_id": "c1", "operation": "create", "chunk_id": "new",
           "new_html": "<p>September 15th.<table><tr><td>Please fill: x</td></tr></table></p>",
           "ai_explanation": "Timeline"}
    client = HITLFake(
        rounds=[[bad], [bad], [bad], [bad]],
        htmls=[GATE_HEADINGS + "<p>never</p>"],
    )

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(1.0)
        return session, client

    session, client = asyncio.run(run())
    assert session.draft_version == 0
    assert session.current_draft_html == GATE_HEADINGS  # no partial commit
    assert session.job_status == STATUS_ERROR


def test_function_words_are_not_required_anchors():
    # Phase 3 benchmark: "want"/"have"/"after" were wrongly required anchors.
    from app.drafting.validator import _fact_anchors
    anchors = _fact_anchors(
        "We want to have a kickoff meeting next week, finalize the requirements, "
        "and begin development immediately after approval."
    )
    for word in ("want", "have", "after", "immediately"):
        assert word not in anchors, f"{word!r} must not be a required anchor"
    for word in ("kickoff", "requirements", "development", "approval"):
        assert word in anchors, f"{word!r} must remain a content anchor"


def test_kickoff_paraphrase_accepted_without_function_words():
    # The exact structural shape from the Phase 3 benchmark: the model's
    # legitimate paraphrase drops "want" and "after" — must be accepted.
    draft = GATE_HEADINGS + '<h2>Next Steps</h2><div data-chunk-id="ch-next"><p></p></div>'
    fact = ("We want to have a kickoff meeting next week, finalize the requirements, "
            "and begin development immediately after approval.")
    ops = build_section_operations(ADDITION, fact, draft, "statement_of_work")
    assert len(ops) == 1 and ops[0].section == "Next Steps"
    change = _change(
        new_html="<p>We'd like to have a kickoff meeting next week, finalize the "
                 "requirements, and begin development following approval.</p>",
    )
    ok, fails = validate_proposal(ops[0], change, draft)
    assert ok, fails


def test_missing_meaningful_content_still_rejected():
    # A genuinely missing meaningful fact (the amount) must still fail.
    ops = build_section_operations(
        ADDITION, "The total budget is forty-five thousand dollars.", GATE_HEADINGS, "statement_of_work"
    )
    change = _change(new_html="<p>The project has a budget.</p>")  # amount missing
    ok, fails = validate_proposal(ops[0], change, GATE_HEADINGS)
    assert not ok
    assert any("missing expected content" in f for f in fails)


def test_date_and_money_anchors_still_protected():
    from app.drafting.validator import _fact_anchors
    assert "september 15th" in _fact_anchors("The project starts September 15th.")
    assert any("45,000" in a or "forty" in a for a in _fact_anchors("forty-five thousand dollars"))


def test_proper_noun_anchor_still_protected():
    # A proposal omitting the client entity must be rejected.
    ops = build_section_operations(
        ADDITION, "The client is Northstar Goods.", GATE_HEADINGS, "statement_of_work"
    )
    change = _change(new_html="<p>The client is an unnamed company.</p>")
    ok, fails = validate_proposal(ops[0], change, GATE_HEADINGS)
    assert not ok


def test_meta_verb_paraphrase_accepted():
    # D evidence (minimal_op): "discuss a project" → "the initiative
    # focuses on the project" drops the meta-verb but no fact. Anchors
    # must not require meta-verbs.
    fact = "Discuss a website development project for Northstar Goods, a small e-commerce company."
    ops = build_section_operations(ADDITION, fact, GATE_HEADINGS, "statement_of_work")
    change = _change(
        operation="edit", chunk_id="ch-timeline",
        old_html="<p>old</p>",
        new_html="<p>This initiative focuses on the website development project for "
                 "Northstar Goods, a small e-commerce company.</p>",
    )
    ok, fails = validate_proposal(ops[0], change, GATE_HEADINGS)
    assert ok, fails


def test_should_be_delivered_not_rejected_for_obligation_wording():
    # B evidence: the deliverables fact's "should include" is obligation
    # language; a clean proposal listing the deliverables must pass even
    # when it rephrases "should include".
    fact = ("The deliverables should include the website, payment integration, "
            "mobile responsive design, and basic analytics.")
    ops = build_section_operations(ADDITION, fact, GATE_HEADINGS, "statement_of_work")
    change = _change(
        new_html="<p>The deliverables are the website, payment integration, "
                 "mobile responsive design, and basic analytics.</p>",
    )
    ok, fails = validate_proposal(ops[0], change, GATE_HEADINGS)
    assert ok, fails


def test_transport_failure_rolls_back():
    class FailingTransport(HITLFake):
        async def chat_async(self, **kw):
            await asyncio.sleep(0)
            raise RuntimeError("simulated transport failure")

    client = FailingTransport(rounds=[[]], htmls=[GATE_HEADINGS])

    async def run():
        session, provider = _gate_session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        # 3 batch attempts × 3 transport attempts with backoff must exhaust
        await asyncio.sleep(30)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_ERROR
    assert session.draft_version == 0
    assert session.current_draft_html == GATE_HEADINGS


# --- table markup the platform actually returns -----------------------------

def test_table_rows_parse_real_superdocs_markup():
    """The template starts pristine, but once SuperDocs has edited the table
    the same row carries attributes and <p> wrappers. A parser pinned to the
    pristine shape reported "table has no recognizable rows", the gate denied
    the fill, and that denial wedged the session into a 409 that ended the
    run after one batch."""
    from app.drafting.validator import _table_rows

    pristine = (
        "<table><tbody>"
        "<tr><td><strong>Client</strong></td><td>Northstar Goods</td></tr>"
        "</tbody></table>"
    )
    real = (
        '<table class="docx-table" style="min-width:50px"><tbody>'
        '<tr><td colspan="1" rowspan="1"><p><strong>Client</strong></p></td>'
        '<td colspan="1" rowspan="1"><p>Northstar Goods</p></td></tr>'
        "</tbody></table>"
    )
    assert _table_rows(pristine) == [("Client", "Northstar Goods")]
    assert _table_rows(real) == [("Client", "Northstar Goods")]


def test_detail_cell_still_refillable_after_platform_rewrites_the_table():
    from app.drafting.classifier import _client_cell_is_empty, _project_cell_is_empty

    rewritten = (
        '<table class="docx-table"><tbody>'
        '<tr><td colspan="1" rowspan="1"><p><strong>Client</strong></p></td>'
        '<td colspan="1" rowspan="1"><p></p></td></tr>'
        '<tr><td colspan="1" rowspan="1"><p><strong>Project</strong></p></td>'
        '<td colspan="1" rowspan="1"><p>Website Development</p></td></tr>'
        "</tbody></table>"
    )
    # Still empty → still fillable. Previously the lookup found no row at
    # all, which read as "not empty" and made the cell permanently unfillable.
    assert _client_cell_is_empty(rewritten) is True
    assert _project_cell_is_empty(rewritten) == (False, "Project")


def test_first_write_into_an_empty_section_is_not_rejected():
    """An untouched section's body is "<p><p></p></p>" — a non-empty string
    carrying no chunk id. The old guard was `target_body and change_id not in
    target_body`, which is true for EVERY id when the section holds none, so
    the first write into any empty section was rejected whatever SuperDocs
    proposed. Live: Scope of Work denied four times running, while Timeline
    and Budget passed first try only because SuperDocs returned "new" there.
    Placement is still enforced after the edit by content_landed_in_section.
    """
    from app.drafting.classifier import SectionOperation
    from app.drafting.templates import render_template
    from app.drafting.validator import validate_proposal
    from app.superdocs.schemas import PendingChange

    draft = render_template("statement_of_work")
    op = SectionOperation(
        instruction="x",
        section="Scope of Work",
        facts=["Customers can browse products, add items to a cart, and complete payments online."],
    )
    change = PendingChange(
        change_id="c1",
        chunk_id="506f6f65-9651-4bbc-ad69-e4e3a680266a",  # a chunk elsewhere
        old_html="",
        new_html="<p>Customers can browse products, add items to a cart, "
                 "and complete payments online.</p>",
        ai_explanation="",
    )
    ok, failures = validate_proposal(op, change, draft)
    assert ok, failures


def test_wrong_chunk_still_rejected_once_the_section_owns_one():
    """The check keeps its teeth wherever it can actually be satisfied."""
    from app.drafting.classifier import SectionOperation
    from app.drafting.validator import validate_proposal
    from app.superdocs.schemas import PendingChange

    draft = (
        '<h2>Scope of Work</h2><div data-chunk-id="inside-1"><p>Existing scope text.</p></div>'
        '<h2>Deliverables</h2><div data-chunk-id="elsewhere-9"><p>Other.</p></div>'
    )
    op = SectionOperation(instruction="x", section="Scope of Work", facts=["analytics"])
    change = PendingChange(
        change_id="c1", chunk_id="elsewhere-9", old_html="",
        new_html="<p>Basic analytics.</p>", ai_explanation="",
    )
    ok, failures = validate_proposal(op, change, draft)
    assert not ok
    assert any("outside section" in f for f in failures)


def test_a_failed_table_fill_does_not_destroy_the_batch():
    """A details-table cell is metadata; the section prose is the product.

    SuperDocs regularly ignores the fill instruction — one live run answered
    "change the Client cell" with a bullet list of deliverables — and because
    a batch is atomic, that single cosmetic failure rolled back every
    section's prose with it: 9 transcripts in, 0 batches committed, an empty
    document. The cell is now skipped and the content survives.
    """
    import asyncio

    from app.drafting.classifier import ADDITION, SectionOperation

    client = FakeSuperDocsClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        ops = [
            SectionOperation(
                instruction="fill", section="Project Details", facts=["Acme"],
                table_field="Client", table_value="Acme",
            ),
            SectionOperation(
                instruction="body", section="Timeline & Milestones",
                facts=["The project starts September 15th."],
            ),
        ]
        # The table op fails; the body op succeeds.
        calls: list[str] = []
        original = session._run_gated_operation

        async def fake_op(op, html, doc, classification, captured, foreign, all_facts):
            calls.append(op.table_field or op.section)
            if op.table_field is not None:
                session._failed_batch_holder = "proposal's table has no recognizable rows"
                return None, False
            return html + "<p>The project starts September 15th.</p>", False

        session._run_gated_operation = fake_op
        result = await session._run_batch_ops(
            ops, ["Acme", "The project starts September 15th."],
            ADDITION, "text", session._active_doc, [],
        )
        session._run_gated_operation = original
        return result, calls

    result, calls = asyncio.run(run())
    # The batch survived and the body operation still ran.
    assert result is not None, "a failed table cell must not roll back the batch"
    assert "Timeline & Milestones" in calls
    assert "September 15th" in result


def test_placement_check_matches_whole_words_not_substrings():
    """"We'll provide the PRODUCT images" was rolled back whole because
    "product" also occurs inside "browse productS" in Scope of Work — a
    substring hit on a common noun, reported as content landing in the wrong
    section. The diagnostic caught it live:
        PLACEMENT op='Assumptions & Dependencies' landed=False missing=['product']
    """
    from app.drafting.validator import content_landed_in_section

    doc = (
        "<h2>Scope of Work</h2><p>Customers can browse products and complete payments.</p>"
        "<h2>Assumptions &amp; Dependencies</h2><p>We will provide the product images, "
        "descriptions, pricing, branding assets, and access to our existing domain.</p>"
    )
    fact = ("We'll provide the product images, descriptions, pricing, branding assets, "
            "and access to our existing domain.")
    landed, missing = content_landed_in_section(doc, "Assumptions & Dependencies", [fact])
    assert landed, missing


def test_a_real_relocation_is_still_caught():
    """The check must keep its teeth — a phrase moved wholesale shows up as
    several anchors in a foreign section, not one."""
    from app.drafting.validator import content_landed_in_section

    doc = (
        "<h2>Project Details</h2><p>A kick-off meeting is planned for next week "
        "to finalize requirements.</p><h2>Next Steps</h2>"
    )
    fact = ("We want to have a kick-off meeting next week, finalize the requirements, "
            "and begin development immediately after approval.")
    landed, missing = content_landed_in_section(doc, "Next Steps", [fact])
    assert not landed
    assert len(missing) >= 2


def test_addition_ops_in_a_correction_batch_use_the_addition_validator():
    """A batch is classified a correction when ANY sentence repairs a value,
    but the rest is split out into normal addition ops. Validation branched
    on the BATCH classification, so those additions were judged by
    validate_correction — which requires an "edit" operation and rejected a
    plain insertion three times over with "correction proposal is not an
    edit operation". Live cost: Deliverables, Out of Scope and Next Steps
    all empty from one batch.
    """
    from app.drafting.classifier import CORRECTION, build_section_operations

    draft = (
        "<h2>Deliverables</h2>"
        "<h2>Budget / Commercial Terms</h2><div><p>Our total budget is $45,000.</p></div>"
    )
    ops = build_section_operations(
        CORRECTION,
        "Actually, no, make it $55,000. The deliverables should include the website.",
        draft, "statement_of_work",
    )
    repair = [o for o in ops if o.is_correction]
    additions = [o for o in ops if not o.is_correction]
    assert len(repair) == 1
    assert additions and all(o.section for o in additions)
