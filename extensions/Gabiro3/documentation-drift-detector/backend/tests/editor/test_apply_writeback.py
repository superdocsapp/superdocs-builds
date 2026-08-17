"""An approved fix must reach the document — and be recorded.

Two failures these cover, both of which made an approval look successful while
the document stayed exactly as it was:

  * `_apply_one` called `update(...)` which was never imported at module
    level, so the edit landed in SuperDocs and the very next line raised
    NameError — no history row, no status, no sign anything had happened.
  * Nothing wrote the edit back to our stored `chunks`, so the document view
    and every download kept serving pre-edit content forever.
"""

import hashlib

import pytest

from agents.editor import review_api
from agents.editor.editor import ApplyOutcome, Editor
from core.superdocs_client import MockSuperDocsClient


def chunk(cid, html):
    return {"chunk_id": cid, "html": html,
            "content_hash": hashlib.sha256(html.encode()).hexdigest()}


class FakeSD(MockSuperDocsClient):
    """Drives one apply to completion without network access."""

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
        return "job-1"

    async def get_job(self, job_id):
        if self.approvals:
            return {"job_id": job_id, "status": "completed", "metadata": {}}
        return {"job_id": job_id, "status": "awaiting_approval",
                "metadata": {"awaiting_kind": "change",
                             "pending_changes": self._pending}}

    async def approve_change(self, job_id, change_id, approved=True, feedback=None):
        self.approvals.append((change_id, approved, feedback))
        return {"status": "ok"}


PRE = [chunk("c1", "<p>npm install</p>"), chunk("c2", "<p>untouched</p>")]
POST = [chunk("c1", "<p>pnpm install</p>"), chunk("c2", "<p>untouched</p>")]


class TestEditorReturnsEditedContent:
    """Phase B already re-fetches the document; the content it proves against
    is exactly what history and the write-back need."""

    @pytest.mark.asyncio
    async def test_returns_before_and_after_for_the_target_chunk(self):
        sd = FakeSD(PRE, POST, [{"change_id": "ch1", "chunk_id": "c1"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix(
            "doc", "c1", "npm install", "pnpm install"
        )
        assert out["status"] == ApplyOutcome.APPLIED
        assert out["before_html"] == "<p>npm install</p>"
        assert out["after_html"] == "<p>pnpm install</p>"
        assert out["before_hash"] != out["after_hash"]

    @pytest.mark.asyncio
    async def test_returns_post_chunks_for_write_back(self):
        sd = FakeSD(PRE, POST, [{"change_id": "ch1", "chunk_id": "c1"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix(
            "doc", "c1", "npm install", "pnpm install"
        )
        assert [c["chunk_id"] for c in out["post_chunks"]] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_blocked_apply_carries_no_content(self):
        """Nothing changed, so there is nothing to write back or record."""
        sd = FakeSD(PRE, PRE, [{"change_id": "ch1", "chunk_id": "c2"}])
        out = await Editor(sd, poll_interval=0.001, poll_timeout=2).apply_fix(
            "doc", "c1", "npm install", "pnpm install"
        )
        assert out["status"] == ApplyOutcome.NEEDS_ESCALATION
        assert "post_chunks" not in out


class FakeDB:
    """Records every write so tests can assert on what was persisted."""

    def __init__(self, stored_chunks=None, rows=None):
        self.stored = stored_chunks or []
        self.rows = rows or {}
        self.statements: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []
        self.updates: list[tuple[str, dict, dict]] = []

    async def exec(self, sql, values=None):
        self.statements.append((sql, values or {}))
        if "SELECT chunk_id, content_hash FROM chunks" in sql:
            return self.stored
        return []

    async def exec_one(self, sql, values=None):
        for key, value in self.rows.items():
            if key in sql:
                return value
        return None

    async def insert(self, table, data, returning="id"):
        self.inserts.append((table, data))
        return {"id": "new-id"}

    async def update(self, table, where, data):
        self.updates.append((table, where, data))

    def install(self, monkeypatch):
        monkeypatch.setattr(review_api, "exec", self.exec)
        monkeypatch.setattr(review_api, "exec_one", self.exec_one)
        monkeypatch.setattr(review_api, "insert", self.insert)
        monkeypatch.setattr(review_api, "update", self.update)
        return self


class TestSyncStoredChunks:
    @pytest.mark.asyncio
    async def test_updates_only_the_chunk_whose_content_changed(self, monkeypatch):
        db = FakeDB(stored_chunks=[
            {"chunk_id": "c1", "content_hash": PRE[0]["content_hash"]},
            {"chunk_id": "c2", "content_hash": PRE[1]["content_hash"]},
        ]).install(monkeypatch)

        changed = await review_api._sync_stored_chunks("doc-uuid", POST)

        assert changed == 1
        updates = [s for s in db.statements if s[0].startswith("UPDATE chunks")]
        assert len(updates) == 1
        assert updates[0][1]["cid"] == "c1"
        assert updates[0][1]["html"] == "<p>pnpm install</p>"

    @pytest.mark.asyncio
    async def test_drops_the_embedding_of_a_rewritten_chunk(self, monkeypatch):
        """A vector describing text the chunk no longer holds is worse than
        none: the embedder treats a present embedding as a cache hit and would
        never recompute it."""
        db = FakeDB(stored_chunks=[
            {"chunk_id": "c1", "content_hash": PRE[0]["content_hash"]},
        ]).install(monkeypatch)

        await review_api._sync_stored_chunks("doc-uuid", POST)

        sql = [s[0] for s in db.statements if s[0].startswith("UPDATE chunks")][0]
        assert "embedding = NULL" in sql

    @pytest.mark.asyncio
    async def test_ignores_chunks_we_do_not_track(self, monkeypatch):
        """A chunk appearing or vanishing is a structural change the byte Judge
        should have blocked, so it is not quietly reconciled here."""
        db = FakeDB(stored_chunks=[
            {"chunk_id": "c1", "content_hash": PRE[0]["content_hash"]},
        ]).install(monkeypatch)

        changed = await review_api._sync_stored_chunks(
            "doc-uuid", POST + [chunk("c99", "<p>new</p>")]
        )

        assert changed == 1
        assert all("c99" != s[1].get("cid") for s in db.statements)

    @pytest.mark.asyncio
    async def test_no_document_is_a_no_op(self, monkeypatch):
        db = FakeDB().install(monkeypatch)
        assert await review_api._sync_stored_chunks("", POST) == 0
        assert db.statements == []


def _finding_row():
    return {
        "id": "f-1",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "chunk_id": "c1",
        "evidence_chunk_id": "c1",
        "proposed_old": "npm install",
        "proposed_new": "pnpm install",
        "document_id": "d-1",
        "superdocs_doc_id": "sd-1",
    }


def _install_editor(monkeypatch, result):
    class StubEditor:
        def __init__(self, *a, **kw):
            pass

        async def apply_fix(self, **kw):
            return dict(result)

    monkeypatch.setattr("agents.editor.editor.Editor", StubEditor)


class TestApplyOneRecordsWhatHappened:
    @pytest.mark.asyncio
    async def test_successful_apply_does_not_raise_name_error(self, monkeypatch):
        """Regression: `update` was only imported inside approve/reject, so the
        success path of every apply died on NameError after the edit landed."""
        FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.APPLIED, "job_id": "job-1", "change_ids": ["ch1"],
            "before_html": "<p>npm install</p>", "after_html": "<p>pnpm install</p>",
            "before_hash": "aaa", "after_hash": "bbb", "post_chunks": POST,
        })

        out = await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        assert out["status"] == ApplyOutcome.APPLIED

    @pytest.mark.asyncio
    async def test_history_row_carries_before_and_after_content(self, monkeypatch):
        """Ids prove an edit happened; content is what makes history readable."""
        db = FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.APPLIED, "job_id": "job-1", "change_ids": ["ch1"],
            "before_html": "<p>npm install</p>", "after_html": "<p>pnpm install</p>",
            "before_hash": "aaa", "after_hash": "bbb", "post_chunks": POST,
        })

        await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        table, data = next(i for i in db.inserts if i[0] == "applied_edits")
        assert table == "applied_edits"
        assert data["before_html"] == "<p>npm install</p>"
        assert data["after_html"] == "<p>pnpm install</p>"
        assert data["chunk_id"] == "c1"
        assert data["document_id"] == "d-1"
        assert data["proposed_old"] == "npm install"

    @pytest.mark.asyncio
    async def test_marks_the_finding_applied(self, monkeypatch):
        db = FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.APPLIED, "job_id": "job-1", "change_ids": ["ch1"],
            "post_chunks": POST,
        })

        await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        final = [u for u in db.updates if u[0] == "findings"][-1]
        assert final[2]["apply_status"] == review_api.ApplyStatus.APPLIED
        assert final[2]["applied_at"] is not None

    @pytest.mark.asyncio
    async def test_blocked_apply_is_marked_blocked_not_applied(self, monkeypatch):
        db = FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.NEEDS_ESCALATION, "phase": "A",
            "reason": "change targets chunk c2",
        })

        await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        final = [u for u in db.updates if u[0] == "findings"][-1]
        assert final[2]["apply_status"] == review_api.ApplyStatus.BLOCKED
        # No edit landed, so no history row may claim one did.
        assert not [i for i in db.inserts if i[0] == "applied_edits"]

    @pytest.mark.asyncio
    async def test_failed_apply_is_visible_rather_than_silent(self, monkeypatch):
        db = FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.FAILED, "reason": "timed out awaiting approval",
        })

        await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        final = [u for u in db.updates if u[0] == "findings"][-1]
        assert final[2]["apply_status"] == review_api.ApplyStatus.FAILED
        assert "timed out" in final[2]["apply_reason"]

    @pytest.mark.asyncio
    async def test_missing_replacement_text_fails_loudly(self, monkeypatch):
        db = FakeDB().install(monkeypatch)
        row = _finding_row() | {"proposed_new": None}

        out = await review_api._apply_one(row, row["run_id"])

        assert out["status"] == ApplyOutcome.FAILED
        assert db.updates[-1][2]["apply_status"] == review_api.ApplyStatus.FAILED

    @pytest.mark.asyncio
    async def test_already_applied_finding_is_not_applied_twice(self, monkeypatch):
        db = FakeDB(rows={"FROM applied_edits": {"id": "existing"}}).install(monkeypatch)

        out = await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        assert out["status"] == "ALREADY_APPLIED"
        assert db.inserts == []

    @pytest.mark.asyncio
    async def test_response_does_not_carry_the_whole_document(self, monkeypatch):
        FakeDB(stored_chunks=[]).install(monkeypatch)
        _install_editor(monkeypatch, {
            "status": ApplyOutcome.APPLIED, "job_id": "job-1", "change_ids": ["ch1"],
            "post_chunks": POST,
        })

        out = await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        assert "post_chunks" not in out
        assert out["chunks_synced"] == 0
