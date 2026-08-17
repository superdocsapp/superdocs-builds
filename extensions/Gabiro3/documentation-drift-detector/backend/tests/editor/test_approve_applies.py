"""Approving a finding must schedule the edit, not just record an opinion.

Approval used to write a `review_decisions` row and stop. The document was
only ever touched if someone separately pressed "Apply approved", so a fix a
human had explicitly accepted could sit unapplied indefinitely while the UI
reported success.
"""

import pytest
from fastapi import BackgroundTasks, HTTPException

from agents.editor import review_api

from tests.editor.test_apply_writeback import FakeDB


class TestApproveSchedulesTheApply:
    @pytest.mark.asyncio
    async def test_approve_queues_a_background_apply(self, monkeypatch):
        db = FakeDB(rows={"FROM findings WHERE id": {"id": "f-1", "run_id": "r-1"}}).install(monkeypatch)
        tasks = BackgroundTasks()

        out = await review_api.approve_finding(
            "11111111-1111-1111-1111-111111111111", tasks
        )

        assert out["apply_status"] == review_api.ApplyStatus.QUEUED
        assert len(tasks.tasks) == 1, "approval must schedule the apply"

    @pytest.mark.asyncio
    async def test_approve_marks_the_finding_queued(self, monkeypatch):
        db = FakeDB(rows={"FROM findings WHERE id": {"id": "f-1", "run_id": "r-1"}}).install(monkeypatch)

        await review_api.approve_finding(
            "11111111-1111-1111-1111-111111111111", BackgroundTasks()
        )

        queued = [u for u in db.updates if u[0] == "findings"]
        assert queued and queued[-1][2]["apply_status"] == review_api.ApplyStatus.QUEUED

    @pytest.mark.asyncio
    async def test_an_already_applied_finding_is_not_reapplied(self, monkeypatch):
        db = FakeDB(rows={
            "FROM findings WHERE id": {"id": "f-1", "run_id": "r-1"},
            "FROM applied_edits": {"id": "existing"},
        }).install(monkeypatch)
        tasks = BackgroundTasks()

        out = await review_api.approve_finding(
            "11111111-1111-1111-1111-111111111111", tasks
        )

        assert out["apply_status"] == review_api.ApplyStatus.APPLIED
        assert tasks.tasks == []

    @pytest.mark.asyncio
    async def test_unknown_finding_is_a_404(self, monkeypatch):
        FakeDB().install(monkeypatch)
        with pytest.raises(HTTPException) as exc:
            await review_api.approve_finding(
                "11111111-1111-1111-1111-111111111111", BackgroundTasks()
            )
        assert exc.value.status_code == 404


class TestBackgroundApplyOutcomes:
    @pytest.mark.asyncio
    async def test_a_rejection_that_lands_first_wins(self, monkeypatch):
        """Editing against the human's superseded instruction is worse than
        not editing at all, so the decision is re-read at apply time."""
        db = FakeDB(rows={
            "FROM findings f": {"id": "f-1", "run_id": "r-1", "chunk_id": "c1",
                                "evidence_chunk_id": "c1", "proposed_old": "a",
                                "proposed_new": "b", "document_id": "d-1",
                                "superdocs_doc_id": "sd-1"},
            "FROM review_decisions": {"decision": "rejected"},
        }).install(monkeypatch)

        called = []
        monkeypatch.setattr(
            review_api, "_apply_one",
            lambda *a, **kw: called.append(a) or {"status": "APPLIED"},
        )

        await review_api._apply_finding_in_background("f-1")

        assert called == [], "a rejected finding must not be applied"
        assert db.updates[-1][2]["apply_status"] is None

    @pytest.mark.asyncio
    async def test_an_unexpected_failure_is_recorded_not_swallowed(self, monkeypatch):
        """Nothing is watching a background task, so a crash that left no trace
        would be the original silent-drop bug in a new place."""
        db = FakeDB(rows={
            "FROM findings f": {"id": "f-1", "run_id": "r-1", "chunk_id": "c1",
                                "evidence_chunk_id": "c1", "proposed_old": "a",
                                "proposed_new": "b", "document_id": "d-1",
                                "superdocs_doc_id": "sd-1"},
            "FROM review_decisions": {"decision": "approved"},
        }).install(monkeypatch)

        async def boom(*a, **kw):
            raise RuntimeError("SuperDocs unreachable")

        monkeypatch.setattr(review_api, "_apply_one", boom)

        await review_api._apply_finding_in_background("f-1")

        last = db.updates[-1]
        assert last[0] == "findings"
        assert last[2]["apply_status"] == review_api.ApplyStatus.FAILED
        assert "SuperDocs unreachable" in last[2]["apply_reason"]

    @pytest.mark.asyncio
    async def test_applies_when_the_decision_still_stands(self, monkeypatch):
        FakeDB(rows={
            "FROM findings f": {"id": "f-1", "run_id": "r-1", "chunk_id": "c1",
                                "evidence_chunk_id": "c1", "proposed_old": "a",
                                "proposed_new": "b", "document_id": "d-1",
                                "superdocs_doc_id": "sd-1"},
            "FROM review_decisions": {"decision": "approved"},
        }).install(monkeypatch)

        called = []

        async def record(row, run_id):
            called.append(run_id)
            return {"status": "APPLIED"}

        monkeypatch.setattr(review_api, "_apply_one", record)

        await review_api._apply_finding_in_background("f-1")

        assert called == ["r-1"]
