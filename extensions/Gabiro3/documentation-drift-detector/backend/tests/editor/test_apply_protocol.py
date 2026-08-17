import pytest

from agents.editor.editor import (
    ApplyOutcome,
    Editor,
    parse_pending_changes,
)
from core.superdocs_client import MockSuperDocsClient


class TestParsePendingChanges:
    """pending_changes is an object when polling but a JSON string over SSE —
    a documented trap that silently yields zero changes if unhandled."""

    def test_reads_plain_list(self):
        md = {"pending_changes": [{"change_id": "x", "chunk_id": "c1"}]}
        assert parse_pending_changes(md)[0]["change_id"] == "x"

    def test_parses_json_string_form(self):
        md = {"pending_changes": '[{"change_id": "x", "chunk_id": "c1"}]'}
        assert parse_pending_changes(md)[0]["chunk_id"] == "c1"

    def test_unwraps_object_with_changes_key(self):
        md = {"pending_changes": {"changes": [{"change_id": "y"}]}}
        assert parse_pending_changes(md)[0]["change_id"] == "y"

    def test_missing_key_is_empty(self):
        assert parse_pending_changes({}) == []

    def test_malformed_json_is_empty_not_an_exception(self):
        assert parse_pending_changes({"pending_changes": "{not json"}) == []


class FakeSD(MockSuperDocsClient):
    """Drives the apply protocol without network access."""

    def __init__(self, pre_chunks, post_chunks, pending, **kw):
        super().__init__(**kw)
        self._pre, self._post = pre_chunks, post_chunks
        self._pending = pending
        self.fetches = 0
        self.approvals: list[tuple] = []

    async def get_document_chunks(self, doc_id):
        self.fetches += 1
        return self._pre if self.fetches == 1 else self._post

    async def chat_async(self, message, approval_mode="ask_every_time",
                         model_tier="max", document_id=None):
        self.last_message = message
        return "job-1"

    async def get_job(self, job_id):
        if self.approvals:  # settled once a decision has been submitted
            return {"job_id": job_id, "status": "completed", "metadata": {}}
        return {"job_id": job_id, "status": "awaiting_approval",
                "metadata": {"awaiting_kind": "change",
                             "pending_changes": self._pending}}

    async def approve_change(self, job_id, change_id, approved=True, feedback=None):
        self.approvals.append((change_id, approved, feedback))
        return {"status": "ok"}


def chunk(cid, html):
    import hashlib
    return {"chunk_id": cid, "html": html,
            "content_hash": hashlib.sha256(html.encode()).hexdigest()}


class TestApplyProtocol:
    PRE = [chunk("c1", "<p>npm install</p>"), chunk("c2", "<p>untouched</p>")]

    @pytest.mark.asyncio
    async def test_happy_path_applies_and_verifies(self):
        post = [chunk("c1", "<p>pnpm install</p>"), chunk("c2", "<p>untouched</p>")]
        sd = FakeSD(self.PRE, post, [{"change_id": "ch1", "chunk_id": "c1"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c1", "npm install", "pnpm install")
        assert out["status"] == ApplyOutcome.APPLIED
        assert out["target_chunk_changed"] is True
        assert sd.approvals == [("ch1", True, None)]

    @pytest.mark.asyncio
    async def test_phase_a_blocks_stray_chunk_before_applying(self):
        """A batch touching an unapproved chunk must never be approved."""
        sd = FakeSD(self.PRE, self.PRE, [{"change_id": "ch1", "chunk_id": "c2"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c1", "npm install", "pnpm install")
        assert out["status"] == ApplyOutcome.NEEDS_ESCALATION
        assert out["phase"] == "A"
        # It was actively denied, not merely skipped.
        assert sd.approvals and sd.approvals[0][1] is False

    @pytest.mark.asyncio
    async def test_phase_b_alarms_when_another_chunk_changed(self):
        post = [chunk("c1", "<p>pnpm install</p>"), chunk("c2", "<p>MUTATED</p>")]
        sd = FakeSD(self.PRE, post, [{"change_id": "ch1", "chunk_id": "c1"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c1", "npm install", "pnpm install")
        assert out["status"] == ApplyOutcome.ALARM
        assert out["phase"] == "B"
        assert "c2" in out["reason"]

    @pytest.mark.asyncio
    async def test_unknown_target_chunk_is_refused_upfront(self):
        sd = FakeSD(self.PRE, self.PRE, [{"change_id": "ch1", "chunk_id": "c9"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c9", "a", "b")
        assert out["status"] == ApplyOutcome.FAILED
        assert "not present" in out["reason"]

    @pytest.mark.asyncio
    async def test_no_proposed_changes_is_not_treated_as_success(self):
        sd = FakeSD(self.PRE, self.PRE, [])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c1", "npm install", "pnpm install")
        assert out["status"] == ApplyOutcome.FAILED
        assert "no changes proposed" in out["reason"]

    @pytest.mark.asyncio
    async def test_instruction_names_the_chunk_and_both_sides(self):
        post = [chunk("c1", "<p>pnpm install</p>"), chunk("c2", "<p>untouched</p>")]
        sd = FakeSD(self.PRE, post, [{"change_id": "ch1", "chunk_id": "c1"}])
        await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix("doc", "c1", "npm install", "pnpm install")
        assert "c1" in sd.last_message
        assert "npm install" in sd.last_message and "pnpm install" in sd.last_message
        assert "nothing else" in sd.last_message.lower()
