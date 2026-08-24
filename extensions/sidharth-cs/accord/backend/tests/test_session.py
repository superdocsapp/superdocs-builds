"""MeetingSession tests — the Draft Engine wiring provider -> batcher ->
classifier -> SuperDocs client -> integrity check -> published state.
Against a fake SuperDocs client (no network, no key), same discipline as
the rest of this suite."""

import asyncio

import httpx

from app.drafting.session import STATUS_BLOCKED, STATUS_COMPLETED, STATUS_ERROR, MeetingSession
from app.superdocs.schemas import (
    ChatAsyncResponse,
    ChunkDiff,
    DocumentChanges,
    ExportResult,
    JobMetadata,
    JobResult,
    JobStatusResponse,
    PendingChange,
    UploadResponse,
)
from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.rtms_provider import RTMSTranscriptProvider

STARTER_HTML = "<h1>Meeting Draft</h1><p>Drafting begins as the conversation is captured.</p>"


class FakeSuperDocsClient:
    """Stands in for app.superdocs.client.SuperDocsClient. Each test
    configures `next_updated_html` / `next_changes` for what the
    "SuperDocs edit" should appear to have done. Nests document_changes
    under `result`, matching the real wire shape confirmed live (see
    schemas.py's JobResult) — not the flatter shape this originally guessed.

    Each method awaits `asyncio.sleep(0)` before returning — a real
    suspension point, like real network I/O has and a bare `return` doesn't.
    Without it these fakes can mask a task self-cancelling itself (a real
    bug once lived in Batcher._flush, invisible to this whole suite until a
    live call exposed it, because only a genuine await gives the loop a
    chance to deliver a pending cancellation)."""

    def __init__(self) -> None:
        self.chat_messages: list[str] = []
        self.upload_calls = 0
        self.next_updated_html = STARTER_HTML
        self.next_changes: list[dict] = [{"operation": "update", "chunk_id": "c1"}]
        self.next_status = "completed"
        self._job_counter = 0
        # Milestone 5 — deliberately no approve() method exists on this fake
        # (session.py's own gate never calls SuperDocsClient.approve(), see
        # its module comment) — an accidental call would fail loudly with
        # AttributeError, not silently pass.
        self.export_calls: list[dict] = []
        self.export_should_fail = False
        self.next_export_warnings: list[str] = []

    async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
        await asyncio.sleep(0)
        self.upload_calls += 1
        return UploadResponse(session_id=session_id, html=STARTER_HTML)

    async def chat_async(self, *, message, session_id, approval_mode="auto", model_tier=None, thinking_depth=None):
        await asyncio.sleep(0)
        self.chat_messages.append(message)
        if model_tier is not None or thinking_depth is not None:
            self.model_params = {"model_tier": model_tier, "thinking_depth": thinking_depth}
        self._job_counter += 1
        return ChatAsyncResponse(job_id=f"job{self._job_counter}", session_id=session_id)

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        return JobStatusResponse(
            job_id=job_id,
            status=self.next_status,
            result=JobResult(
                document_changes=DocumentChanges(
                    updated_html=self.next_updated_html,
                    changes=[ChunkDiff(**d) for d in self.next_changes],
                )
            ),
        )

    async def export(self, *, session_id, format="docx"):
        await asyncio.sleep(0)
        self.export_calls.append({"session_id": session_id, "format": format})
        if self.export_should_fail:
            raise RuntimeError("simulated SuperDocs export failure")
        return ExportResult(
            content=b"fake-docx-bytes",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            warnings=self.next_export_warnings,
        )


def _session(client: FakeSuperDocsClient) -> tuple[MeetingSession, ManualTranscriptProvider]:
    provider = ManualTranscriptProvider()
    session = MeetingSession(
        "test-meeting-uuid",
        client,
        provider,
        manual_provider=provider,
        silence_gap_seconds=0.05,
        size_ceiling_chars=10_000,
        max_wait_seconds=10,
        poll_interval_seconds=0.01,
    )
    return session, provider


def test_manual_submission_produces_a_completed_draft_update():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>The client is Acme Corp.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_COMPLETED
    assert "Acme Corp" in session.current_draft_html
    assert len(session.activity) == 1
    assert client.upload_calls == 1  # lazy document init, exactly once
    assert "Acme Corp" in client.chat_messages[0]


def test_batch_message_contains_section_targets_and_constraints():
    # The structured instruction layer must reach SuperDocs: the chat
    # message carries section targets plus structural constraints, so the
    # downstream LLM edits a constrained space instead of guessing. Uses a
    # fake whose upload returns a heading-bearing starter (the same trick
    # as test_initialize_document_uses_active_template), because the
    # section router parses headings from the live draft.
    class HeadingsClient(FakeSuperDocsClient):
        async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
            await asyncio.sleep(0)
            self.upload_calls += 1
            html = (
                "<h1>Statement of Work</h1>"
                "<h2>Timeline &amp; Milestones</h2><p></p>"
                "<h2>Budget / Commercial Terms</h2><p></p>"
            )
            return UploadResponse(session_id=session_id, html=html)

    client = HeadingsClient()
    client.next_updated_html = STARTER_HTML + "<p>September 15th recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        # First batch initializes the document; the second carries the
        # structured instruction built against the heading-bearing draft.
        await provider.submit("Init the document.")
        await asyncio.sleep(0.2)
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.2)
        return session

    asyncio.run(run())
    assert len(client.chat_messages) >= 2
    message = client.chat_messages[1]
    assert "[Target: Timeline & Milestones]" in message
    assert "NEVER modify" in message
    assert "section headings" in message


# ---------------------------------------------------------------------------
# Section-by-section orchestration — one batch may drive N sequential
# bounded SuperDocs operations, but stays ONE logical draft update.
# ---------------------------------------------------------------------------

HEADINGS_HTML = (
    "<h1>Statement of Work</h1>"
    # Nested empty paragraphs, matching templates.py's real starter shape —
    # a flat <p></p> would be stripped by _strip_empty_sections on the first
    # operation and trip the heading-count integrity signal.
    "<h2>Timeline &amp; Milestones</h2><p><p></p></p>"
    "<h2>Budget / Commercial Terms</h2><p><p></p></p>"
)

# Content placed WITHIN each section's own body (not tacked onto the end of
# the string) — the placement-integrity check cares which heading's
# boundary content lands inside, so these mirror where a real SuperDocs
# edit actually lands rather than faking placement via concatenation.
HEADINGS_HTML_TIMELINE_ONLY = HEADINGS_HTML.replace(
    "<h2>Timeline &amp; Milestones</h2><p><p></p></p>",
    "<h2>Timeline &amp; Milestones</h2><p>Timeline: September 15th.</p>",
)
HEADINGS_HTML_TIMELINE_AND_BUDGET = HEADINGS_HTML_TIMELINE_ONLY.replace(
    "<h2>Budget / Commercial Terms</h2><p><p></p></p>",
    "<h2>Budget / Commercial Terms</h2><p>Budget: $45,000.</p>",
)


class HeadingsUploadMixin:
    async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
        await asyncio.sleep(0)
        self.upload_calls += 1
        return UploadResponse(session_id=session_id, html=HEADINGS_HTML)


class SequencedClient(HeadingsUploadMixin, FakeSuperDocsClient):
    """Fake whose get_job returns one pre-arranged updated_html per call,
    in order — lets a test stage the output of each section operation."""

    def __init__(self, htmls):
        FakeSuperDocsClient.__init__(self)
        self.htmls = list(htmls)

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        html = self.htmls.pop(0) if self.htmls else self.next_updated_html
        return JobStatusResponse(
            job_id=job_id,
            status=self.next_status,
            result=JobResult(
                document_changes=DocumentChanges(
                    updated_html=html,
                    changes=[ChunkDiff(operation="update", chunk_id="c1")],
                )
            ),
        )


def test_two_section_batch_makes_two_chat_calls():
    client = SequencedClient([
        HEADINGS_HTML_TIMELINE_ONLY,
        HEADINGS_HTML_TIMELINE_AND_BUDGET,
    ])

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is $45,000.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert len(client.chat_messages) == 2
    assert "[Target: Timeline & Milestones]" in client.chat_messages[0]
    assert "[Target: Budget / Commercial Terms]" in client.chat_messages[1]


def test_two_section_batch_increments_draft_version_once():
    client = SequencedClient([
        HEADINGS_HTML_TIMELINE_ONLY,
        HEADINGS_HTML_TIMELINE_AND_BUDGET,
    ])

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is $45,000.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.draft_version == 1
    assert len(session.activity) == 1


def test_two_section_batch_publishes_one_draft_updated():
    client = SequencedClient([
        HEADINGS_HTML_TIMELINE_ONLY,
        HEADINGS_HTML_TIMELINE_AND_BUDGET,
    ])
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is $45,000.")
        await asyncio.sleep(0.2)
        drain_task.cancel()

    asyncio.run(run())
    draft_updates = [e for e in events if e["type"] == "draft_updated"]
    # One for the init (version 0), one for the batch (version 1) — never
    # one per section operation.
    assert len(draft_updates) == 2
    assert [e["draft_version"] for e in draft_updates] == [0, 1]


def test_second_section_op_is_sequential_on_first_op_output():
    # The second operation's returned HTML carries the first operation's
    # content forward — the final draft contains both sections' facts,
    # proving operations layer on each other rather than overwriting.
    client = SequencedClient([
        HEADINGS_HTML_TIMELINE_ONLY,
        HEADINGS_HTML_TIMELINE_AND_BUDGET,
    ])

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is $45,000.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert "Timeline: September 15th" in session.current_draft_html
    assert "Budget: $45,000" in session.current_draft_html


def test_section_failure_keeps_the_operations_that_succeeded():
    class FailingClient(HeadingsUploadMixin, FakeSuperDocsClient):
        def __init__(self):
            FakeSuperDocsClient.__init__(self)
            self.chat_count = 0

        async def chat_async(self, *, message, session_id, approval_mode="auto", model_tier=None, thinking_depth=None):
            await asyncio.sleep(0)
            self.chat_count += 1
            self.chat_messages.append(message)
            if self.chat_count >= 2:
                # Fails on every retry of the second section operation —
                # the rollback must happen only after all 3 attempts exhaust.
                raise RuntimeError("simulated SuperDocs chat failure")
            self._job_counter += 1
            return ChatAsyncResponse(job_id=f"job{self._job_counter}", session_id=session_id)

    client = FailingClient()
    client.next_updated_html = HEADINGS_HTML + "<p>Timeline: September 15th.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th. Our total budget is $45,000.")
        # Long enough for 3 batch attempts × 3 retry attempts on the
        # failing operation (1s + 2s backoff each) to exhaust.
        await asyncio.sleep(22)
        return session

    session = asyncio.run(run())
    # Operation 1 (Timeline) succeeded, operation 2 (Budget) failed.
    #
    # This test previously asserted that the whole batch rolled back to the
    # initialized template. That contract was the bug: live, a batch whose
    # first operation logged "landed=True" still produced a COMPLETELY EMPTY
    # document, because one later failure discarded every operation that had
    # already succeeded. An operation is now the unit of commit.
    #
    # So Timeline's content survives, Budget's does not, and the failure is
    # still surfaced — a missing section must never be reported as success.
    assert "Timeline: September 15th." in session.current_draft_html
    assert "$45,000" not in session.current_draft_html
    assert session.error and "could not be added" in session.error
    assert session.draft_version == 1


def test_single_section_batch_makes_one_chat_call():
    client = SequencedClient([HEADINGS_HTML_TIMELINE_ONLY])

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert len(client.chat_messages) == 1
    assert session.draft_version == 1


def test_transcript_always_reaches_superdocs_even_when_misclassified():
    # Design property: classification only affects framing, never whether
    # content is forwarded. A batch with a correction-shaped phrase but no
    # value overlap classifies as ADDITION (see test_classifier.py) — this
    # confirms the text still reaches the chat message either way.
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("No, let's also add a confidentiality clause.")
        await asyncio.sleep(0.2)
        return session

    asyncio.run(run())
    assert len(client.chat_messages) == 1
    assert "confidentiality clause" in client.chat_messages[0]


def test_integrity_failure_blocks_the_draft_instead_of_applying_it():
    client = FakeSuperDocsClient()
    # Simulates the documented silent-content-loss failure mode.
    client.next_updated_html = "<h1>Meeting Draft</h1>"
    client.next_changes = [{"operation": "update", "chunk_id": "c1"}]

    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("The engagement fee is confirmed at USD 48,000.")
        await asyncio.sleep(0.2)
        drain_task.cancel()
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_BLOCKED
    assert session.current_draft_html == STARTER_HTML  # not advanced
    assert any(e["type"] == "blocking_card" for e in events)

    # NEVER: leave a pending block reachable only through the live event
    # stream. A panel that reloads, reconnects, or joins late rebuilds
    # itself from state_snapshot() alone — and when the card was missing
    # from it, the server sat on job_status="blocked" with error=None while
    # the panel rendered a healthy session and SuperDocs held an edit
    # nobody was ever asked about.
    snapshot = session.state_snapshot()
    assert snapshot["blocking_card"] is not None
    assert snapshot["blocking_card"]["reason"]
    # Polled continuously — the card carries its reason, never two full
    # copies of the document.
    assert "html_after" not in snapshot["blocking_card"]

    asyncio.run(session.resolve_blocking_card(action="discard"))
    assert session.state_snapshot()["blocking_card"] is None


def test_subscribers_receive_the_expected_event_sequence():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>New scope item.</p>"
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("Add a new scope item.")
        await asyncio.sleep(0.2)
        drain_task.cancel()

    asyncio.run(run())
    event_types = [e["type"] for e in events]
    assert "transcript_received" in event_types
    assert "draft_updated" in event_types
    assert "activity" in event_types
    assert event_types.count("job_status") >= 2  # at least sending + completed


def test_state_snapshot_reflects_current_state():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    snapshot = session.state_snapshot()
    assert snapshot["job_status"] == STATUS_COMPLETED
    assert snapshot["current_draft_html"] == session.current_draft_html
    assert len(snapshot["transcript_history"]) == 1
    assert len(snapshot["activity"]) == 1


def test_two_batches_in_quick_succession_both_get_processed_not_dropped():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Both items recorded.</p>"

    async def run():
        # size_ceiling small enough that each submit flushes on its own.
        provider = ManualTranscriptProvider()
        session = MeetingSession(
            "test-meeting-uuid-2",
            client,
            provider,
            manual_provider=provider,
            silence_gap_seconds=10,
            size_ceiling_chars=5,
            max_wait_seconds=10,
            poll_interval_seconds=0.01,
        )
        await session.start()
        await provider.submit("Record the first item.")
        await provider.submit("Record the second item.")
        await asyncio.sleep(0.3)
        return session

    session = asyncio.run(run())
    assert len(client.chat_messages) == 2  # neither batch silently dropped
    assert len(session.activity) == 2


# ---- Milestone 4: same pipeline, fed through RTMSTranscriptProvider.submit()
# instead of Manual's — proves the batcher/classifier/SuperDocs/integrity
# pipeline is provider-agnostic by test, not just by claim. No websocket
# involved: submit() is RTMS's own fallback-input path (see its module
# docstring), exercised here exactly like Manual's submit() above.


def _rtms_session(client: FakeSuperDocsClient) -> tuple[MeetingSession, RTMSTranscriptProvider]:
    provider = RTMSTranscriptProvider("cid", "csecret")
    session = MeetingSession(
        "test-meeting-uuid-rtms",
        client,
        provider,
        manual_provider=provider,
        silence_gap_seconds=0.05,
        size_ceiling_chars=10_000,
        max_wait_seconds=10,
        poll_interval_seconds=0.01,
    )
    return session, provider


def test_rtms_provider_submit_drives_the_same_pipeline_as_manual():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>The client is Acme Corp.</p>"

    async def run():
        session, provider = _rtms_session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_COMPLETED
    assert "Acme Corp" in session.current_draft_html
    assert len(session.activity) == 1
    assert "Acme Corp" in client.chat_messages[0]


def test_rtms_provider_integrity_failure_blocks_the_draft_same_as_manual():
    client = FakeSuperDocsClient()
    client.next_updated_html = "<h1>Meeting Draft</h1>"  # simulated content loss

    async def run():
        session, provider = _rtms_session(client)
        await session.start()
        await provider.submit("The engagement fee is confirmed at USD 48,000.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_BLOCKED
    assert session.current_draft_html == STARTER_HTML  # not advanced


# ---- Milestone 5: review checkpoint + export gate --------------------------
# A pure in-house state machine on MeetingSession — never calls
# SuperDocsClient.approve() (PROGRESS.md M1 found it unreliable; every batch
# here already runs approval_mode="auto"). FakeSuperDocsClient has no
# approve() method at all, so an accidental call would fail loudly.


def test_new_session_has_no_approved_draft_and_export_is_not_ready():
    client = FakeSuperDocsClient()
    session, _provider = _session(client)
    assert session.draft_version == 0
    assert session.approved_draft_version is None
    assert session.export_ready is False


def test_a_completed_batch_increments_draft_version_and_leaves_export_unready():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>New scope item.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Add a new scope item.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.draft_version == 1
    assert session.export_ready is False


def test_export_draft_raises_when_nothing_is_approved():
    client = FakeSuperDocsClient()

    async def run():
        session, _provider = _session(client)
        try:
            await session.export_draft()
            return None
        except ValueError as exc:
            return str(exc)

    message = asyncio.run(run())
    assert message is not None
    assert client.export_calls == []  # never reached SuperDocs


# ---------------------------------------------------------------------------
# _empty_heading_texts and the export cleanup pass — export() pulls
# SuperDocs' own remote document, which never received the local
# _strip_empty_sections cleanup the panel already applies; confirmed live,
# an exported doc showed template-filler headings the panel never did.
# ---------------------------------------------------------------------------

def test_empty_heading_texts_identifies_only_truly_empty_sections():
    from app.drafting.session import _empty_heading_texts
    html = (
        "<h2>Scope of Work</h2><p>We build a website.</p>"
        "<h2>Executive Summary</h2><p><p></p></p>"
        "<h2>Objectives</h2>"
    )
    assert _empty_heading_texts(html) == ["Executive Summary", "Objectives"]


class CleanupFake(HeadingsUploadMixin, FakeSuperDocsClient):
    """job1 (populating Timeline) completes normally. Every later job (the
    export cleanup pass) pauses at awaiting_approval proposing to remove
    the still-empty Budget section, with `removal_new_html` controlling
    whether that proposal looks like a pure delete or a disguised rewrite."""

    def __init__(self, removal_new_html: str = "") -> None:
        FakeSuperDocsClient.__init__(self)
        self.removal_new_html = removal_new_html
        self.approval_calls: list[dict] = []
        self._approved: set[str] = set()
        self._denied: set[str] = set()

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        if job_id == "job1":
            return JobStatusResponse(
                job_id=job_id, status="completed",
                result=JobResult(document_changes=DocumentChanges(
                    updated_html=HEADINGS_HTML_TIMELINE_ONLY,
                    changes=[ChunkDiff(operation="update", chunk_id="c1")],
                )),
            )
        if job_id in self._denied:
            return JobStatusResponse(job_id=job_id, status="cancelled")
        if job_id in self._approved:
            return JobStatusResponse(job_id=job_id, status="completed", result=None)
        return JobStatusResponse(
            job_id=job_id, status="awaiting_approval",
            metadata=JobMetadata(pending_changes=[
                PendingChange(
                    change_id="rm1", operation="delete", chunk_id="budget-chunk",
                    old_html="<h2>Budget / Commercial Terms</h2><p><p></p></p>",
                    new_html=self.removal_new_html,
                    ai_explanation="removed empty section",
                ),
            ]),
        )

    async def approve_changes(self, *, session_id, job_id, approved, changes=None, feedback=None):
        await asyncio.sleep(0)
        self.approval_calls.append({"approved": approved, "changes": changes})
        (self._approved if approved else self._denied).add(job_id)
        return {"status": "ok"}


def test_export_cleanup_approves_a_pure_removal_proposal():
    client = CleanupFake(removal_new_html="")  # empty new_html — a real delete
    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        result = await session.export_draft()
        return session, result

    session, result = asyncio.run(run())
    assert client.approval_calls[-1]["approved"] is True
    assert len(client.chat_messages) == 2  # one to populate Timeline, one cleanup pass
    assert result.content == b"fake-docx-bytes"


def test_export_cleanup_denies_a_disguised_rewrite_and_exports_anyway():
    # SuperDocs proposes real new content instead of an actual deletion —
    # the narrowest-trust rule denies it; export must still succeed exactly
    # as it always has, since the cleanup pass is purely cosmetic.
    client = CleanupFake(removal_new_html="<p>Some new content SuperDocs tried to add.</p>")
    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        result = await session.export_draft()
        return session, result

    session, result = asyncio.run(run())
    assert client.approval_calls[-1]["approved"] is False
    assert result.content == b"fake-docx-bytes"


def test_approve_draft_with_current_version_succeeds():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        return session

    session = asyncio.run(run())
    assert session.approved_draft_version == 1
    assert session.export_ready is True


def test_approve_draft_with_stale_version_raises_and_does_not_approve():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        try:
            await session.approve_draft(draft_version=0)  # the version before this batch landed
            raised = False
        except ValueError:
            raised = True
        return session, raised

    session, raised = asyncio.run(run())
    assert raised is True
    assert session.approved_draft_version is None
    assert session.export_ready is False


def test_export_draft_succeeds_after_approval():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        result = await session.export_draft()
        return session, result

    session, result = asyncio.run(run())
    assert result.content == b"fake-docx-bytes"
    assert client.export_calls == [{"session_id": session.session_id, "format": "docx"}]


def test_a_new_batch_after_approval_invalidates_it():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>First.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the first correction.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        assert session.export_ready is True  # sanity, before the second batch

        client.next_updated_html = STARTER_HTML + "<p>First.</p><p>Second.</p>"
        await provider.submit("Record the second correction.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.draft_version == 2
    assert session.approved_draft_version == 1  # unchanged by the new batch
    assert session.export_ready is False


def test_export_draft_raises_after_a_post_approval_change():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>First.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the first correction.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)

        client.next_updated_html = STARTER_HTML + "<p>First.</p><p>Second.</p>"
        await provider.submit("Record the second correction.")
        await asyncio.sleep(0.2)

        try:
            await session.export_draft()
            return True
        except ValueError:
            return False

    exported = asyncio.run(run())
    assert exported is False
    assert len(client.export_calls) == 0  # blocked before ever reaching SuperDocs


def test_re_approving_the_new_version_makes_export_ready_again():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>First.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the first correction.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)

        client.next_updated_html = STARTER_HTML + "<p>First.</p><p>Second.</p>"
        await provider.submit("Record the second correction.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        return await session.export_draft()

    result = asyncio.run(run())
    assert result.content == b"fake-docx-bytes"
    assert len(client.export_calls) == 1


def test_exporting_twice_after_one_approval_succeeds_both_times():
    # Also proves export doesn't end the session: a third transcript, sent
    # after two exports, still runs the normal pipeline to completion.
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)

        first = await session.export_draft()
        second = await session.export_draft()  # same approved version, no re-approval

        client.next_updated_html = STARTER_HTML + "<p>Recorded.</p><p>Extra.</p>"
        await provider.submit("One more thing, still live.")
        await asyncio.sleep(0.2)
        return session, first, second

    session, first, second = asyncio.run(run())
    assert first.content == b"fake-docx-bytes"
    assert second.content == b"fake-docx-bytes"
    assert len(client.export_calls) == 2
    assert session.draft_version == 2  # the meeting kept drafting after export
    assert session.job_status == STATUS_COMPLETED


def test_export_draft_failure_publishes_error_and_reraises_without_mutating_approval():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"
    client.export_should_fail = True
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)

        raised = False
        try:
            await session.export_draft()
        except RuntimeError:
            raised = True
        await asyncio.sleep(0.05)
        drain_task.cancel()
        return session, raised

    session, raised = asyncio.run(run())
    assert raised is True
    # Approval survives a failed export — a failure must not silently look
    # like "nothing was ever approved," and export_ready reflects the truth
    # (the approved version genuinely wasn't exported, not that it's unreviewed).
    assert session.approved_draft_version == 1
    assert session.export_ready is True
    error_events = [e for e in events if e["type"] == "error"]
    assert any("export failed" in e["message"] for e in error_events)


def test_changes_since_approval_slices_the_activity_list_correctly():
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        for text in ("Log the first item.", "Log the second item."):
            await provider.submit(text)
            await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)  # approve at version 2
        await provider.submit("Log the third item.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.changes_since_approval() == session.activity[2:3]
    assert len(session.changes_since_approval()) == 1


def test_changes_since_approval_with_no_prior_approval_returns_everything():
    client = FakeSuperDocsClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Log the first item.")
        await asyncio.sleep(0.2)
        await provider.submit("Log the second item.")
        await asyncio.sleep(0.2)
        return session

    session = asyncio.run(run())
    assert session.changes_since_approval() == session.activity
    assert len(session.changes_since_approval()) == 2


def test_approve_draft_publishes_draft_approved_event():
    client = FakeSuperDocsClient()
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        await asyncio.sleep(0.05)
        drain_task.cancel()

    asyncio.run(run())
    approved_events = [e for e in events if e["type"] == "draft_approved"]
    assert approved_events == [{"type": "draft_approved", "draft_version": 1, "approved_by": None}]


def test_draft_updated_event_carries_the_new_draft_version():
    client = FakeSuperDocsClient()
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        drain_task.cancel()

    asyncio.run(run())
    draft_updates = [e for e in events if e["type"] == "draft_updated"]
    # First is the blank-starter init (draft_version 0), second is the real batch (1).
    assert [e["draft_version"] for e in draft_updates] == [0, 1]


# ---- M5 follow-up fix: export result caching, for the real "download it
# again" link — a plain GET, not a one-shot JS Blob the Zoom webview may not
# visibly honor.


def test_export_draft_caches_the_result_as_last_export():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        result = await session.export_draft()
        return session, result

    session, result = asyncio.run(run())
    assert session.last_export is result
    assert session.last_export_at is not None


def test_state_snapshot_includes_last_export_metadata_but_never_the_bytes():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)

        before_export = session.state_snapshot()

        await session.approve_draft(draft_version=session.draft_version)
        await session.export_draft()
        after_export = session.state_snapshot()
        return before_export, after_export

    before_export, after_export = asyncio.run(run())
    assert before_export["last_export"] is None
    assert after_export["last_export"]["size"] == len(b"fake-docx-bytes")
    assert after_export["last_export"]["content_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert after_export["last_export"]["exported_at"] is not None
    assert "content" not in after_export["last_export"]  # metadata only, never the bytes


def test_export_draft_publishes_export_completed_event():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"
    events = []

    async def run():
        session, provider = _session(client)
        queue = session.subscribe()

        async def drain():
            while True:
                events.append(await queue.get())

        drain_task = asyncio.create_task(drain())
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        await session.export_draft()
        await asyncio.sleep(0.05)
        drain_task.cancel()

    asyncio.run(run())
    completed = [e for e in events if e["type"] == "export_completed"]
    assert len(completed) == 1
    assert completed[0]["size"] == len(b"fake-docx-bytes")
    assert completed[0]["content_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert completed[0]["exported_at"] is not None


def test_export_draft_failure_does_not_touch_last_export():
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.approve_draft(draft_version=session.draft_version)
        await session.export_draft()  # succeeds, populates last_export

        client.export_should_fail = True
        try:
            await session.export_draft()
        except RuntimeError:
            pass
        return session

    session = asyncio.run(run())
    # The failed second attempt must not clobber the last genuinely
    # successful export with nothing.
    assert session.last_export is not None
    assert session.last_export.content == b"fake-docx-bytes"


# ---- Phase 1 regression: Clear Meeting Data ---------------------------------


def test_clear_preserves_provider():
    """Clear must NOT null the provider — Audio Fetcher controls must survive."""
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>Recorded.</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("Record the agreement.")
        await asyncio.sleep(0.2)
        await session.reset()
        snapshot = session.state_snapshot()
        return snapshot

    snapshot = asyncio.run(run())
    assert snapshot.get("provider") is not None
    assert snapshot["provider"]["name"] == "manual"


def test_clear_preserves_template_key():
    """Reset must preserve the active template key, not hardcode SOW."""
    client = FakeSuperDocsClient()
    from app.drafting.templates import PROPOSAL

    async def run():
        session, provider = _session(client)
        await session.start()
        await session.set_active_template(key=PROPOSAL)
        await session.reset()
        return session._active_doc.template_key

    key = asyncio.run(run())
    assert key == PROPOSAL


def test_empty_sections_are_stripped():
    """_strip_empty_sections must remove headings with empty paragraphs."""
    from app.drafting.session import _strip_empty_sections
    html = "<h1>Doc</h1><h2>Has Content</h2><p>real text</p><h2>Empty</h2><p></p><h2>Also Empty</h2><p>  </p>"
    result = _strip_empty_sections(html)
    assert "Has Content" in result
    assert "Empty" not in result
    assert "Also Empty" not in result


# ---- Phase 2 regression: Template isolation + doc pinning --------------------


def test_initialize_document_uses_active_template():
    """_initialize_document must upload the active doc's template, not SOW."""
    class TemplateClient(FakeSuperDocsClient):
        upload_html = None

        async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
            import base64
            self.upload_html = base64.b64decode(file_base64).decode()
            self.upload_calls += 1
            return type('R', (), {'html': self.upload_html})()

    client = TemplateClient()
    client.next_updated_html = STARTER_HTML + "<p>text</p>"
    from app.drafting.templates import MINUTES

    async def run():
        session, provider = _session(client)
        await session.start()
        await session.set_active_template(key=MINUTES)
        await provider.submit("test")
        await asyncio.sleep(0.2)
        return client.upload_html

    html = asyncio.run(run())
    assert "Meeting Minutes" in html


def test_batch_pins_document_on_tab_switch():
    """An in-flight batch must commit to its pinned doc, not the active doc."""
    client = FakeSuperDocsClient()
    client.next_updated_html = STARTER_HTML + "<p>batch content</p>"

    async def run():
        session, provider = _session(client)
        await session.start()
        # Submit to doc 1
        await provider.submit("Record the first batch.")
        await asyncio.sleep(0.2)
        doc1_id = session._active_doc.doc_id
        doc1_version = session._active_doc.draft_version
        # Create doc 2 and switch to it
        await session.create_document(template_key="meeting_minutes")
        doc2_id = session._active_doc.doc_id
        # Submit to doc 2 while doc 1's version should be unchanged
        assert doc1_id != doc2_id
        assert session._active_doc.doc_id == doc2_id
        # doc1 should still have its batch content
        assert doc1_version == 1
        return True

    result = asyncio.run(run())
    assert result is True


# ---- Phase 4 regression: Stop/Start reuse -----------------------------------


def test_begin_listening_reuses_bot_for_same_meeting():
    """Stop then Start on same meeting must reuse bot, not spawn new one."""
    import asyncio as _asyncio
    from app.transcript.vexa_provider import VexaTranscriptProvider
    from app.transcript.provider import STATUS_NOT_STARTED, STATUS_STOPPED

    provider = VexaTranscriptProvider("https://x.example", "k")
    provider._status = STATUS_STOPPED
    provider._bot_spawned = True
    provider._native_meeting_id = "84194315528"
    provider._meeting_url = "https://zoom.us/j/84194315528"

    spawn_count = 0
    async def fake_spawn():
        nonlocal spawn_count
        spawn_count += 1
    provider._spawn_bot = fake_spawn

    async def run():
        await provider.begin_listening(meeting_number="84194315528")
        return spawn_count

    count = _asyncio.run(run())
    assert count == 0  # reused, not re-spawned


# ---------------------------------------------------------------------------
# SuperDocs 409-conflict wedge (P0) — bounded retries, terminal state, no
# death spiral. A 409 means the remote session rejects the call; retrying it
# is guaranteed to fail again, so the fix is fail-fast + terminal error +
# refusing to process later batches until explicit recovery.
# ---------------------------------------------------------------------------

def _raise_409():
    req = httpx.Request("POST", "https://api.superdocs.app/v1/chat/async")
    resp = httpx.Response(409, request=req)
    raise httpx.HTTPStatusError("409 Conflict", request=req, response=resp)


class ConflictClient(FakeSuperDocsClient):
    """chat_async always 409s — the persistent-conflict case."""

    def __init__(self):
        super().__init__()
        self.chat_calls = 0

    async def chat_async(self, **kwargs):
        self.chat_calls += 1
        await asyncio.sleep(0)
        _raise_409()


def test_chat_409_fails_fast_terminal_error_no_spiral():
    client = ConflictClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        await asyncio.sleep(0.3)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_ERROR
    assert session._unrecoverable is True
    # Exactly ONE chat attempt — a 409 is NOT retried at the op or batch
    # level (no 3×3 spiral), and no partial content reached the draft.
    assert client.chat_calls == 1
    assert "Acme Corp" not in session.current_draft_html


def test_chat_409_blocks_later_batches_until_explicit_recovery():
    client = ConflictClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        await asyncio.sleep(0.3)
        # A later batch must NOT be processed while unrecoverable.
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.3)
        return session

    session = asyncio.run(run())
    assert client.chat_calls == 1  # second batch dropped at the terminal gate
    assert session.job_status == STATUS_ERROR
    # Explicit recovery re-runs the failed batch (the gate is lifted for the
    # attempt), even though this still-conflicting client 409s again.
    asyncio.run(session.retry_last_batch())
    assert client.chat_calls == 2  # retry re-opened processing


class TransientThenSuccessClient(FakeSuperDocsClient):
    """chat_async fails with a NON-409 exception twice, then succeeds."""

    def __init__(self):
        super().__init__()
        self.chat_calls = 0

    async def chat_async(self, **kwargs):
        self.chat_calls += 1
        await asyncio.sleep(0)
        if self.chat_calls < 3:
            raise RuntimeError("transient network blip")
        return await super().chat_async(**kwargs)


def test_transient_non_409_chat_failure_still_recovers_with_op_retry():
    client = TransientThenSuccessClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        # Outlast the two op-level backoff sleeps (1s + 2s) so the third
        # attempt completes and the batch commits.
        await asyncio.sleep(4.5)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_COMPLETED  # transient retry still works
    assert client.chat_calls == 3  # op-level retry consumed the two blips
    assert session._unrecoverable is False


class PostApprovalSettleFailClient(FakeSuperDocsClient):
    """Gate passes and approve_changes succeeds, but the post-approval job
    never settles as completed — the exact batch-4 smoke-test trigger. After
    approval the remote session is in an unknown state, so a fresh chat on
    the same session is what 409s."""

    def __init__(self):
        super().__init__()
        self.next_status = "awaiting_approval"
        self.approve_history: list[bool] = []

    async def approve_changes(self, *, session_id, job_id, approved, changes=None, feedback=None):
        await asyncio.sleep(0)
        self.approve_history.append(approved)
        if approved:
            self.next_status = "failed"  # post-approval poll → non-completed terminal

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        return JobStatusResponse(
            job_id=job_id,
            status=self.next_status,
            metadata=JobMetadata(pending_changes=[
                PendingChange(
                    change_id="c1", operation="create", chunk_id="new",
                    old_html="", new_html="<p>The client is Acme Corp.</p>",
                )
            ]),
        )


def test_post_approval_settlement_failure_is_terminal_and_blocks_later_batches():
    client = PostApprovalSettleFailClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("The client is Acme Corp.")
        await asyncio.sleep(0.3)
        assert session.job_status == STATUS_ERROR
        assert session._unrecoverable is True
        # Later batch must NOT run: no second chat, no status overwrite.
        await provider.submit("The project starts September 15th.")
        await asyncio.sleep(0.3)
        return session

    session = asyncio.run(run())
    assert session.job_status == STATUS_ERROR
    assert session._unrecoverable is True
    # approve happened exactly once, and NO later batch submitted a chat.
    assert client.approve_history == [True]
    assert len(client.chat_messages) == 1
    assert "Acme Corp" not in session.current_draft_html  # no partial commit


# ---------------------------------------------------------------------------
# Denial lifecycle (targeted fix): a gate-denied job must be polled to its
# terminal state before the next chat_async, or the still-open job makes that
# chat 409 (the denial wedge from the 58s benchmark). This fake models the
# real behavior: approve_changes(False) is accepted (200) but does NOT
# terminalize the job — only a subsequent get_job reveals it settled. A
# chat_async issued while any prior job is non-terminal raises 409, exactly
# like the real API. Without the deny-settlement fix, the second chat 409s.
# ---------------------------------------------------------------------------

_TERMINAL = ("completed", "failed", "cancelled")


class DenyLifecycleClient(FakeSuperDocsClient):
    def __init__(self):
        super().__init__()
        self.job_states: dict[str, str] = {}
        self.deny_pending: set[str] = set()
        self.chat_calls = 0
        self.approve_history: list[bool] = []
        self.next_updated_html = STARTER_HTML + "<p>We need a modern responsive website for Northstar.</p>"
        self.valid_html = "<p>We need a modern responsive website for Northstar.</p>"

    async def chat_async(self, **kwargs):
        await asyncio.sleep(0)
        self.chat_calls += 1
        # SuperDocs 409s a chat while any prior job is still non-terminal.
        for _jid, status in self.job_states.items():
            if status not in _TERMINAL:
                _raise_409()
        self._job_counter += 1
        jid = f"job{self._job_counter}"
        self.job_states[jid] = "awaiting_approval"
        # First chat produces the rejected proposal; later chats (op-level
        # retry after the denied job settles) produce a valid one.
        if self.chat_calls == 1:
            self.reject_job = jid
        else:
            self.valid_job = jid
        return ChatAsyncResponse(job_id=jid, session_id=kwargs.get("session_id"))

    async def get_job(self, job_id):
        await asyncio.sleep(0)
        if job_id in self.deny_pending:
            # The deny has now taken effect: the job settled to cancelled.
            self.job_states[job_id] = "cancelled"
        status = self.job_states.get(job_id, "awaiting_approval")
        if status == "completed":
            return JobStatusResponse(
                job_id=job_id,
                status="completed",
                result=JobResult(document_changes=DocumentChanges(
                    updated_html=self.next_updated_html,
                    changes=[ChunkDiff(**d) for d in self.next_changes],
                )),
            )
        if job_id == self.reject_job:
            # Rejected job's proposal: valid markup but missing the fact
            # anchors ('modern','need','northstar','responsive','website') —
            # a clean non-structural rejection, so the deny path (not the
            # structural fail) is what the test exercises.
            pending = [
                PendingChange(change_id="c1", operation="create", chunk_id="new",
                              old_html="", new_html="<p>Acme Corp ships widgets quarterly.</p>")
            ]
        else:
            pending = [
                PendingChange(change_id="c2", operation="create", chunk_id="new",
                              old_html="", new_html=self.valid_html)
            ]
        return JobStatusResponse(
            job_id=job_id,
            status=status,
            metadata=JobMetadata(pending_changes=pending),
        )

    async def approve_changes(self, *, session_id, job_id, approved, changes=None, feedback=None):
        await asyncio.sleep(0)
        self.approve_history.append(approved)
        if approved:
            self.job_states[job_id] = "completed"
        else:
            # Accepted (200) but the job is not yet terminal — it settles
            # asynchronously; only a poll reveals the cancelled state.
            self.deny_pending.add(job_id)


def test_gate_rejection_settles_then_next_chat_succeeds():
    client = DenyLifecycleClient()

    async def run():
        session, provider = _session(client)
        await session.start()
        await provider.submit("We need a modern responsive website for Northstar.")
        # Outlast one op-level retry backoff (1s) after the deny-settlement poll.
        await asyncio.sleep(3.0)
        return session

    session = asyncio.run(run())
    # The rejected proposal was NOT committed.
    assert "Acme Corp ships widgets quarterly" not in session.current_draft_html
    # The next operation proceeded and committed its valid content.
    assert "We need a modern responsive website for Northstar" in session.current_draft_html
    assert session.draft_version == 1
    # Exactly one deny (job1) then one approve (job2) — gate semantics unchanged.
    assert client.approve_history == [False, True]
    # Two chats: the initial rejected proposal + the retry after the denied
    # job settled. No 409 storm (the fake 409s if a prior job were still open).
    assert client.chat_calls == 2
    assert client.chat_calls == 2 and session._unrecoverable is False
    assert session.job_status == STATUS_COMPLETED


# --- _verify_structure: local may legitimately diverge from remote ----------
#
# What this must never do:
#   1. fail a batch just because we stripped an empty template section locally
#      (the regression: fixing _strip_empty_sections' regex made the stripper
#      real, and an equal-length heading comparison then failed every batch)
#   2. pass when SuperDocs invents a heading of its own
#   3. pass when SuperDocs deletes or renames one of ours

class _StructureClient:
    def __init__(self, remote_headings):
        self._remote = remote_headings

    async def get_document_detail(self, *, document_id):
        return {"structure": {"headings": [{"text": h} for h in self._remote]}}


def _verify(remote_headings, local_html, template_key="statement_of_work"):
    client = _StructureClient(remote_headings)
    session, _ = _session(client)
    session._durable_document_id = "doc-1"
    doc = session._active_doc
    doc.current_draft_html = local_html
    doc.template_key = template_key
    return asyncio.run(session._verify_structure(doc))


_FULL_REMOTE = [
    "Statement of Work", "Project Details", "Scope of Work", "Deliverables",
    "Timeline & Milestones", "Budget / Commercial Terms",
    "Assumptions & Dependencies", "Out of Scope", "Next Steps",
]


def test_structure_allows_locally_stripped_empty_sections():
    """The regression. Remote keeps every seeded heading until export
    reconciles; local drops the empty ones as each batch lands."""
    local = (
        "<h1>Statement of Work</h1>"
        "<h2>Project Details</h2><p>Client: North Star Goods</p>"
        "<h2>Scope of Work</h2><p>A responsive website.</p>"
    )
    ok, reason = _verify(_FULL_REMOTE, local)
    assert ok, reason


def test_structure_rejects_a_heading_superdocs_invented():
    remote = _FULL_REMOTE + ["Appendix A"]
    local = "<h1>Statement of Work</h1><h2>Project Details</h2><p>x</p>"
    ok, reason = _verify(remote, local)
    assert not ok and "Appendix A" in reason


def test_structure_rejects_a_heading_deleted_remotely():
    local = (
        "<h1>Statement of Work</h1>"
        "<h2>Project Details</h2><p>x</p>"
        "<h2>Scope of Work</h2><p>y</p>"
    )
    ok, reason = _verify(["Statement of Work", "Project Details"], local)
    assert not ok and "Scope of Work" in reason


def test_structure_rejects_a_heading_renamed_remotely():
    remote = ["Project Brief"] + _FULL_REMOTE[1:]
    local = "<h1>Statement of Work</h1><h2>Project Details</h2><p>x</p>"
    ok, reason = _verify(remote, local)
    assert not ok


def test_structure_rejects_reordering_of_our_own_headings():
    local = (
        "<h1>Statement of Work</h1>"
        "<h2>Scope of Work</h2><p>y</p>"
        "<h2>Project Details</h2><p>x</p>"
    )
    ok, reason = _verify(_FULL_REMOTE, local)
    assert not ok


# --- rollback must not blank the panel when the remote was not rewound -----
#
# What this must never do: show the reviewer an empty document while the
# remote still holds content. Observed live — revert_session returned 409,
# rollback restored the local draft anyway, and the panel reported nothing
# drafted for a document that had several landed sections in it.

class _RevertClient(_StructureClient):
    def __init__(self, revert_ok):
        super().__init__([])
        self.revert_ok = revert_ok
        self.reverted = False

    async def revert_session(self, *, session_id, turn_index):
        if not self.revert_ok:
            raise RuntimeError("Client error '409 Conflict' for url .../revert")
        self.reverted = True


def _rollback(revert_ok):
    client = _RevertClient(revert_ok)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1><h2>Scope of Work</h2><p>Landed content.</p>"
    ok = asyncio.run(
        session._rollback_batch(doc, 0, "<h1>SOW</h1>", "batch", "a reason")
    )
    return ok, doc.current_draft_html, session.error


def test_failed_remote_revert_keeps_the_verified_local_draft():
    ok, html, error = _rollback(revert_ok=False)
    assert ok is False
    assert "Landed content." in html, "content that landed was thrown away"
    assert error, "the failure must still be surfaced to the reviewer"


def test_retained_content_is_approvable():
    """Content kept after a failed remote revert must carry a draft version.
    Without one the panel shows a populated document that can never be
    approved or exported — visible work the reviewer cannot act on."""
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1><h2>Scope of Work</h2><p>Landed.</p>"
    before = doc.draft_version
    asyncio.run(session._rollback_batch(doc, 0, "<h1>SOW</h1>", "batch", "a reason"))
    assert doc.draft_version > before, "retained content has no approvable version"


def test_successful_revert_does_not_invent_a_version():
    client = _RevertClient(revert_ok=True)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1><h2>Scope of Work</h2><p>Landed.</p>"
    before = doc.draft_version
    asyncio.run(session._rollback_batch(doc, 0, "<h1>SOW</h1>", "batch", "a reason"))
    assert doc.draft_version == before, "a clean rollback must not bump the version"


def test_successful_remote_revert_restores_the_pre_batch_draft():
    ok, html, error = _rollback(revert_ok=True)
    assert ok is True
    assert html == "<h1>SOW</h1>"
    assert error


def test_defective_retained_content_is_not_published_as_approvable():
    """Retaining content is only safe when the content is clean.

    SuperDocs sometimes applies a rejected proposal itself rather than
    offering it for approval, so a gate-refused edit can already be in the
    remote document. Live, three placeholder rejections still left
    "Please fill: October [Day], 2026" in Timeline & Milestones — and
    retaining it published the very text the gate refused as an approvable,
    exportable draft version. The empty document is the safer answer.
    """
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = (
        "<h1>SOW</h1><h2>Timeline &amp; Milestones</h2>"
        "<p>Delivery set for Please fill: October [Day], 2026.</p>"
    )
    before = doc.draft_version
    asyncio.run(session._rollback_batch(doc, 0, "<h1>SOW</h1>", "batch", "a reason"))
    assert "Please fill" not in doc.current_draft_html
    assert doc.draft_version == before, "filler must never become approvable"
    assert session.error


def test_clean_retained_content_is_still_kept():
    """The guard must not undo the fix it protects."""
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = (
        "<h1>SOW</h1><h2>Scope of Work</h2><p>A responsive website.</p>"
    )
    before = doc.draft_version
    asyncio.run(session._rollback_batch(doc, 0, "<h1>SOW</h1>", "batch", "a reason"))
    assert "responsive website" in doc.current_draft_html
    assert doc.draft_version > before


# --- cross-batch content loss, and recovering from it ----------------------
#
# What this must never do: let content that reached the document disappear
# without anything noticing. The per-batch preservation check only knew the
# CURRENT batch's facts, so once a batch committed its content was never
# checked again — live, Timeline & Milestones logged "landed=True" and was
# absent from the finished document, and no check anywhere had failed.

def test_a_fact_survives_paraphrase_but_not_deletion():
    from app.drafting.session import _fact_still_present, _norm_text
    fact = ("The project should start on September 15th, and the final "
            "website should be delivered by October 30th.")
    kept = _norm_text(
        "<p>The project begins on September 15th with delivery by October 30th.</p>"
    )
    gone = _norm_text("<p>Our total budget is $45,000.</p>")
    assert _fact_still_present(fact, kept), "a paraphrase is not a deletion"
    assert not _fact_still_present(fact, gone)


def test_filler_is_never_treated_as_lost_content():
    """Filler has no anchors; re-driving it would add noise to the document."""
    from app.drafting.session import _fact_still_present
    assert _fact_still_present("Hi.", "")
    assert _fact_still_present("Um, so.", "")


def _reconcile_session(ledger, html, unrecoverable=False, pending=None, unlanded=None):
    client = _StructureClient([])
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = html
    doc.fact_ledger = list(ledger)
    doc.unlanded_facts = list(unlanded or [])
    session._unrecoverable = unrecoverable
    session._pending_batches = pending or []
    calls = []
    async def fake_op(op, draft_html, d, classification, captured, *a, **k):
        calls.append(op.section)
        return None, False
    session._run_gated_operation = fake_op
    asyncio.run(session._reconcile_missing_facts(doc))
    return calls, doc


def test_reconciliation_redrives_only_what_actually_vanished():
    calls, _ = _reconcile_session(
        [("Timeline & Milestones", "The project starts on September 15th."),
         ("Budget / Commercial Terms", "The total budget is $45,000.")],
        "<h2>Budget / Commercial Terms</h2><p>The total budget is $45,000.</p>",
    )
    assert calls == ["Timeline & Milestones"], calls


def test_reconciliation_does_nothing_when_the_document_is_intact():
    calls, _ = _reconcile_session(
        [("Budget / Commercial Terms", "The total budget is $45,000.")],
        "<h2>Budget / Commercial Terms</h2><p>The total budget is $45,000.</p>",
    )
    assert calls == []


def test_reconciliation_redrives_content_that_never_landed_at_all():
    """NEVER: recover only content that landed and later vanished.

    fact_ledger holds what was verified PRESENT, so a section whose
    operation failed outright was never in it and nothing watched for it.
    Live: SuperDocs' Timeline edit deleted the Scope paragraph it had just
    written, the preservation check correctly refused it, the revert that
    should have undone it returned 400 Bad Request, and the batch kept
    Scope and dropped Timeline — permanently, because a fact that never
    arrived cannot go missing from a ledger of what arrived.
    """
    calls, _ = _reconcile_session(
        [("Scope of Work", "Star Goods is a small e-commerce company.")],
        "<h2>Scope of Work</h2><p>Star Goods is a small e-commerce company.</p>",
        unlanded=[("Timeline & Milestones", "The project starts on September 15th.")],
    )
    assert calls == ["Timeline & Milestones"], calls


def test_owed_content_obeys_the_same_bounds_as_the_ledger():
    """Owed facts take the ordinary recovery path, never a privileged one:
    prose without a date or an amount is still left alone, because an
    anchor our tolerance happens to miss would duplicate a paragraph that
    is already there."""
    calls, _ = _reconcile_session(
        [], "<h1>SOW</h1>",
        unlanded=[("Assumptions & Dependencies", "We expect weekly progress.")],
    )
    assert calls == []

    # ...and a wedged session is still given no work at all.
    calls, _ = _reconcile_session(
        [], "<h1>SOW</h1>", unrecoverable=True,
        unlanded=[("Timeline & Milestones", "The project starts on September 15th.")],
    )
    assert calls == []


def test_reconciliation_never_runs_on_a_wedged_session():
    """A 409-wedged session must not be given more work to 409 on."""
    calls, _ = _reconcile_session(
        [("Timeline & Milestones", "The project starts on September 15th.")],
        "<h1>SOW</h1>", unrecoverable=True,
    )
    assert calls == []


def test_reconciliation_waits_for_the_queue_to_drain():
    """Later batches may legitimately still be re-adding content."""
    calls, _ = _reconcile_session(
        [("Timeline & Milestones", "The project starts on September 15th.")],
        "<h1>SOW</h1>", pending=[["a batch"]],
    )
    assert calls == []


def test_reconciliation_tries_each_fact_only_once():
    """A fact the platform simply refuses to write must not loop forever."""
    ledger = [("Timeline & Milestones", "The project starts on September 15th.")]
    client = _StructureClient([])
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1>"
    doc.fact_ledger = list(ledger)
    calls = []
    async def fake_op(op, draft_html, d, classification, captured, *a, **k):
        calls.append(op.section)
        return None, False
    session._run_gated_operation = fake_op
    asyncio.run(session._reconcile_missing_facts(doc))
    asyncio.run(session._reconcile_missing_facts(doc))
    asyncio.run(session._reconcile_missing_facts(doc))
    assert len(calls) == 1, f"retried {len(calls)} times"


def test_reconciliation_is_bounded_per_pass():
    ledger = [(f"Section {i}", f"Milestone {i} is due on September {i + 1}th.")
              for i in range(10)]
    calls, _ = _reconcile_session(ledger, "<h1>SOW</h1>")
    assert len(calls) == 3, f"issued {len(calls)} edits in one pass"


def test_reconciliation_ignores_prose_it_cannot_be_sure_about():
    """The platform paraphrases prose freely.

    An anchor our tolerance happens to miss would have recovery "restore"
    text that is already in the document, duplicating a paragraph to fix a
    gap that was never there. Only dates and amounts are unambiguous enough
    to act on; everything else is logged and left alone.
    """
    # The section EXISTS and holds a reworded version of the fact. That is
    # the case this rule is for, and the fixture has to show it: with no
    # Scope of Work heading at all there would be nothing to duplicate, and
    # the test would be asserting the opposite of its own reasoning.
    calls, _ = _reconcile_session(
        [("Scope of Work", "We need a modern responsive website for browsing.")],
        "<h1>SOW</h1><h2>Scope of Work</h2>"
        "<p>The project requires a contemporary, adaptive site for viewing goods.</p>",
    )
    assert calls == [], "acted on evidence too weak to be sure of"


def test_reconciliation_restores_a_section_that_vanished_whole():
    """NEVER: leave verified content unrecovered because it is not a date.

    Live, a revert issued to undo ONE operation removed a section a
    PREVIOUS operation had already committed. "Scope of Work" logged
    landed=True and the finished remote document had 7 of its 9 headings —
    the section was gone entirely, not reworded. Prose is normally too weak
    to act on because a missed anchor would duplicate a paragraph that is
    already there; when the heading itself is absent there is no paragraph
    to duplicate, so the usual caution does not apply.
    """
    calls, _ = _reconcile_session(
        [("Scope of Work", "We need a modern responsive website where customers "
                           "can browse products and complete payments online.")],
        "<h1>SOW</h1><h2>Deliverables</h2><p>The website.</p>",
    )
    assert calls == ["Scope of Work"], calls

    # Owed content gets no such promotion: it never landed, so an absent
    # heading is simply the section nobody has spoken to yet.
    calls, _ = _reconcile_session(
        [], "<h1>SOW</h1><h2>Deliverables</h2><p>The website.</p>",
        unlanded=[("Scope of Work", "We need a modern responsive website where "
                                    "customers can browse products online.")],
    )
    assert calls == [], calls


def test_reconciliation_leaves_the_session_status_as_it_found_it():
    """Recovery ran after a batch reported completed and left the session
    showing "polling" — a finished document that looked permanently busy."""
    client = _StructureClient([])
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1>"
    doc.fact_ledger = [("Timeline & Milestones", "Delivery is due October 30th.")]
    session.job_status = STATUS_COMPLETED
    async def fake_op(op, draft_html, d, classification, captured, *a, **k):
        session.job_status = "polling"
        return None, False
    session._run_gated_operation = fake_op
    asyncio.run(session._reconcile_missing_facts(doc))
    assert session.job_status == STATUS_COMPLETED


def test_a_failing_reconciliation_never_breaks_the_session():
    """Recovery must never turn a thin document into a broken one."""
    client = _StructureClient([])
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>SOW</h1><h2>Scope</h2><p>Kept.</p>"
    doc.fact_ledger = [("Timeline & Milestones", "The project starts September 15th.")]
    async def boom(*a, **k):
        raise RuntimeError("SuperDocs exploded")
    session._run_gated_operation = boom
    asyncio.run(session._reconcile_missing_facts(doc))   # must not raise
    assert "Kept." in doc.current_draft_html
    assert session.error is None


def test_retained_draft_with_an_invented_heading_is_rejected():
    """The platform invents headings, not just placeholders.

    Live, a failed batch left "## Scope of Work. The project is for Star
    Goods, a small e-commerce company..." appended as its own heading, and
    the retention guard kept it — publishing a mangled document as reviewable
    work. structural_defect does not cover headings; _verify_structure does,
    but only for batches that succeed.
    """
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.template_key = "statement_of_work"
    doc.current_draft_html = (
        "<h1>Statement of Work</h1>"
        "<h2>Scope of Work</h2><p>A responsive website.</p>"
        "<h2>Scope of Work. The project is for Star Goods, a small "
        "e-commerce company.</h2><p>Invented.</p>"
    )
    before = doc.draft_version
    asyncio.run(session._rollback_batch(
        doc, 0, "<h1>Statement of Work</h1>", "batch", "a reason"))
    assert "Star Goods" not in doc.current_draft_html
    assert doc.draft_version == before


def test_retained_draft_with_only_template_headings_is_kept():
    """The guard must not reject legitimate retained content."""
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.template_key = "statement_of_work"
    doc.current_draft_html = (
        "<h1>Statement of Work</h1>"
        "<h2>Scope of Work</h2><p>A responsive website.</p>"
    )
    before = doc.draft_version
    asyncio.run(session._rollback_batch(
        doc, 0, "<h1>Statement of Work</h1>", "batch", "a reason"))
    assert "responsive website" in doc.current_draft_html
    assert doc.draft_version > before


# --- recovery must never resurrect a corrected value ----------------------
#
# The ledger retires a superseded fact when the correcting batch commits. A
# correction batch that FAILS never reaches that code, so the old figure stays
# on the ledger, reads as missing, and gets restored. Live:
#   RECONCILE restored 'Our total budget is $45,000.' to Budget
#   RECONCILE restored '$55,000.' to Budget
# leaving the document holding both figures — the duplicate the reviewer saw.

SUPERSEDED_HTML = (
    "<h1>Statement of Work</h1>"
    "<h2>Budget / Commercial Terms</h2><p>The project budget is $55,000.</p>"
    "<h2>Timeline &amp; Milestones</h2><p></p>"
)


def test_a_corrected_value_is_never_restored():
    from app.drafting.session import _superseded_in_document
    assert _superseded_in_document(
        "Our total budget is $45,000.", "Budget / Commercial Terms", SUPERSEDED_HTML)


def test_genuinely_lost_content_is_still_restored():
    """The guard must not disable recovery for content nothing replaced."""
    from app.drafting.session import _superseded_in_document
    assert not _superseded_in_document(
        "The project starts September 15th.", "Timeline & Milestones", SUPERSEDED_HTML)


def test_reconciliation_skips_the_superseded_figure():
    """End to end: the old budget is on the ledger and must not be re-driven."""
    calls, _ = _reconcile_session(
        [("Budget / Commercial Terms", "Our total budget is $45,000."),
         ("Timeline & Milestones", "The project starts September 15th.")],
        SUPERSEDED_HTML,
    )
    assert calls == ["Timeline & Milestones"], calls


def test_no_version_bump_when_nothing_was_actually_retained():
    """A batch that fails before anything lands must not publish a version.

    Live: the panel showed draft_version 2 over a template with every section
    empty — an approvable, exportable version of nothing.
    """
    client = _RevertClient(revert_ok=False)
    session, _ = _session(client)
    doc = session._active_doc
    doc.template_key = "statement_of_work"
    skeleton = "<h1>Statement of Work</h1><h2>Scope of Work</h2><p></p>"
    doc.current_draft_html = skeleton
    before = doc.draft_version
    asyncio.run(session._rollback_batch(doc, 0, skeleton, "batch", "a reason"))
    assert doc.draft_version == before
    assert session.error


# --- a failing operation must not destroy the ones that succeeded ---------
#
# What this must never do:
#   1. lose an operation that already committed, because a later one failed
#   2. retry an operation whose edit the remote kept (that duplicates it)
#   3. keep going on a wedged session
#   4. report success when nothing actually landed
#
# Live evidence for why this matters: "PLACEMENT op='Scope of Work'
# landed=True" was followed three operations later by a preservation failure,
# and the finished document was COMPLETELY EMPTY. The batch took its own
# successful work down with it, and the reviewer saw a blank template.

class _ScriptedClient(_StructureClient):
    """Fails the operations named in `fail_on`, succeeds on the rest."""

    def __init__(self, fail_on):
        super().__init__([])
        self.fail_on = set(fail_on)
        self.reverted_turns = []

    async def revert_session(self, *, session_id, turn_index):
        self.reverted_turns.append(turn_index)


def _ops_session(fail_on, sections):
    from app.drafting.classifier import SectionOperation
    client = _ScriptedClient(fail_on)
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>Statement of Work</h1>"
    doc.template_key = "statement_of_work"

    ops = [SectionOperation(instruction="x", section=s, facts=[f"Fact for {s}."])
           for s in sections]

    async def fake_gated(op, draft_html, d, classification, captured, *a, **k):
        if op.section in client.fail_on:
            session._failed_batch_holder = f"scripted failure for {op.section}"
            return None, False
        return draft_html + f"<h2>{op.section}</h2><p>Fact for {op.section}.</p>", False

    session._run_gated_operation = fake_gated
    result = asyncio.run(
        session._run_batch_ops(ops, [], "addition", "text", doc, ["batch"])
    )
    return result, doc, session


def test_content_deleted_by_another_operation_is_redriven_when_revert_fails():
    """NEVER: lose committed content because the platform has no working undo.

    This is the run-to-run failure. One batch carries both Scope of Work
    and Timeline & Milestones; Scope commits; SuperDocs' Timeline edit
    deletes Scope's paragraph; the revert that should undo it answers 400,
    then 404 on the next run. Scope was lost on every single run.

    Re-adding is safe here for a reason that does NOT hold generally:
    facts_preserved_in_html has just proved the content is absent from the
    HTML SuperDocs itself returned. Absence is established, not assumed —
    assuming it is what put two Project Details tables in a live document.
    """
    from app.drafting.classifier import SectionOperation

    class _NoRevert(_ScriptedClient):
        async def revert_session(self, *, session_id, turn_index):
            raise RuntimeError("Client error '404 Not Found'")

    session, _ = _session(_NoRevert([]))
    doc = session._active_doc
    doc.template_key = "statement_of_work"
    scope_fact = ("We need a modern responsive website where customers can "
                  "browse products and complete payments online.")
    doc.current_draft_html = "<h1>Statement of Work</h1>"

    scope_html = ("<h1>Statement of Work</h1>"
                  f"<h2>Scope of Work</h2><p>{scope_fact}</p>")
    # SuperDocs' Timeline edit comes back having deleted Scope's paragraph.
    timeline_html = ("<h1>Statement of Work</h1>"
                     "<h2>Timeline &amp; Milestones</h2><p>Delivery by October 30th.</p>")

    calls = []

    async def gated(op, draft_html, d, classification, captured, *a, **k):
        calls.append(op.section)
        if op.section == "Scope of Work":
            # First call commits it; the re-drive call restores it.
            return scope_html if len(calls) == 1 else (timeline_html + f"<h2>Scope of Work</h2><p>{scope_fact}</p>"), False
        return timeline_html, False

    session._run_gated_operation = gated
    ops = [
        SectionOperation(instruction="x", section="Scope of Work", facts=[scope_fact]),
        SectionOperation(instruction="y", section="Timeline & Milestones",
                         facts=["Delivery by October 30th."]),
    ]
    result = asyncio.run(session._run_batch_ops(
        ops, [], "addition", "text", doc, ["batch"]
    ))

    assert calls.count("Scope of Work") == 2, f"never re-drove the deleted section: {calls}"
    assert result and scope_fact[:30] in result, "Scope of Work was not restored"
    # The Timeline edit itself is still in the document, so it must not be
    # queued for re-driving as well.
    assert not any(sec == "Timeline & Milestones" for sec, _ in doc.unlanded_facts), \
        doc.unlanded_facts


def test_an_edit_the_remote_kept_is_never_recorded_as_owed():
    """NEVER: re-drive content the document is still holding.

    An operation that APPLIED and was then rejected by a post-hoc check is
    only "owed" if the revert actually removed it. Live, SuperDocs' revert
    returned 400 three times, the edit stayed, and recording it as owed had
    reconciliation write it again — the finished document carried two
    Project Details tables. Owed means "asked for and never arrived"; an
    edit the remote still holds has arrived.
    """
    from app.drafting.classifier import SectionOperation

    class _RevertFails(_ScriptedClient):
        async def revert_session(self, *, session_id, turn_index):
            raise RuntimeError("Client error '400 Bad Request'")

    client = _RevertFails([])
    session, _ = _session(client)
    doc = session._active_doc
    doc.current_draft_html = "<h1>Statement of Work</h1>"
    doc.template_key = "statement_of_work"

    op = SectionOperation(instruction="x", section="Scope of Work",
                          facts=["Fact for Scope of Work."])

    async def applied_then_rejected(o, draft_html, d, classification, captured, *a, **k):
        # Applied remotely, but the returned HTML drops content committed
        # earlier — which is what makes the post-hoc check reject it.
        return "<h1>Statement of Work</h1>", False

    session._run_gated_operation = applied_then_rejected
    doc.fact_ledger = [("Deliverables", "Something committed earlier.")]
    asyncio.run(session._run_batch_ops(
        [op], [], "addition", "text", doc, ["batch"]
    ))
    assert doc.unlanded_facts == [], (
        "recorded an edit the remote kept as owed — reconciliation will duplicate it"
    )


def test_a_failing_operation_keeps_the_successful_ones():
    result, doc, _ = _ops_session(
        fail_on={"Deliverables"},
        sections=["Scope of Work", "Deliverables", "Next Steps"],
    )
    assert result is not None, "batch returned nothing despite two operations succeeding"
    assert "Scope of Work" in result, "work committed BEFORE the failure was lost"
    assert "Next Steps" in result, "operations AFTER the failure never ran"
    assert "Deliverables" not in result


def test_every_operation_failing_returns_nothing():
    """Nothing landed, so there is nothing to publish."""
    result, doc, session = _ops_session(
        fail_on={"Scope of Work", "Deliverables"},
        sections=["Scope of Work", "Deliverables"],
    )
    assert result is None
    assert session.error


def test_all_operations_succeeding_is_unchanged():
    result, _, _ = _ops_session(fail_on=set(), sections=["Scope of Work", "Next Steps"])
    assert "Scope of Work" in result and "Next Steps" in result
