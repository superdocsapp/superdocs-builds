import io
import json
import zipfile

import pytest

from redline.superdocs.client import JobTimeout, SuperDocsClient, wait_for_turnpoint
from redline.superdocs.fake import FakeSuperDocs
from redline.superdocs.models import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    ApprovalDecision,
    parse_pending_changes,
)
from redline.superdocs.transport import SuperDocsAPIError

CONTRACT_MD = """# Mutual Non-Disclosure Agreement

This Agreement is made between Acme Corp ("Vendor") and Globex Ltd ("Customer").

Section 1: Confidential Information. Each party may disclose business information.

Section 5: Term. This Agreement runs for two years from the Effective Date.

Section 8: Liability. Each party's aggregate liability arising out of this
Agreement is unlimited and without cap of any kind.
"""

CAP_INSTRUCTION = "Cap liability at $50k in the liability section"


def make_client() -> tuple[SuperDocsClient, FakeSuperDocs]:
    fake = FakeSuperDocs()
    return SuperDocsClient(fake), fake


async def upload_contract(client: SuperDocsClient, session_id="deal-1"):
    result = await client.upload_document("MSA_v1.md", CONTRACT_MD.encode(), session_id=session_id)
    return result


class TestSecondParse:
    def test_parses_object_list(self):
        value = [
            {
                "change_id": "ch_1",
                "operation": "edit",
                "old_html": "<p>a</p>",
                "new_html": "<p>b</p>",
            }
        ]
        changes = parse_pending_changes(value)
        assert len(changes) == 1
        assert changes[0].change_id == "ch_1"

    def test_parses_json_encoded_string(self):
        encoded = json.dumps(
            {
                "type": "single_approval",
                "changes": [
                    {
                        "change_id": "ch_1",
                        "operation": "delete",
                        "old_html": "<p>x</p>",
                        "ai_explanation": "drop",
                    }
                ],
            }
        )
        changes = parse_pending_changes(encoded)
        assert changes[0].operation == "delete"
        assert changes[0].ai_explanation == "drop"

    def test_parses_none(self):
        assert parse_pending_changes(None) == ()


class TestUpload:
    async def test_upload_creates_session_with_chunks(self):
        client, _ = make_client()
        result = await upload_contract(client)
        assert result.session_id == "deal-1"
        assert result.chunks_count == 5
        assert result.version_id == "v1"


class TestFullEditLoop:
    async def test_propose_approve_commit_export(self):
        client, fake = make_client()
        await upload_contract(client)

        job_id = await client.start_edit("deal-1", CAP_INSTRUCTION, approval_mode="ask_every_time")
        snapshot = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)

        assert snapshot.status == STATUS_AWAITING_APPROVAL
        assert snapshot.is_change_review
        liability_edits = [
            c for c in snapshot.pending_changes if "liability" in (c.old_html or "").lower()
        ]
        assert liability_edits, f"expected a liability edit in {snapshot.pending_changes}"
        edit = liability_edits[0]
        assert "unlimited" in edit.old_html.lower()
        assert "$50000" in edit.new_html or "50" in edit.new_html

        response = await client.submit_decisions(
            "deal-1",
            job_id,
            [ApprovalDecision(change_id=edit.change_id, approved=True)],
        )
        assert response["status"] == "ok"

        final = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        assert final.status == STATUS_COMPLETED
        texts = fake.block_texts("deal-1")
        assert any("$50" in t and "aggregate liability exceed" in t for t in texts)
        assert not any("without cap" in t and "unlimited" in t for t in texts)

        approve_calls = [
            p for method, path, p in fake.records if path.endswith("/approve")
        ]
        assert approve_calls and isinstance(approve_calls[-1]["approved"], bool)

        export = await client.export_document("deal-1", fmt="docx")
        content = export.content_bytes()
        assert content[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert "word/document.xml" in archive.namelist()

    async def test_reject_all_with_feedback_triggers_revision_round(self):
        client, fake = make_client()
        await upload_contract(client)
        job_id = await client.start_edit("deal-1", CAP_INSTRUCTION, approval_mode="ask_every_time")
        first = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        decisions = [
            ApprovalDecision(
                change_id=c.change_id, approved=False, feedback="Make the cap $75k instead"
            )
            for c in first.pending_changes
        ]
        await client.submit_decisions("deal-1", job_id, decisions)
        revised = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        assert revised.status == STATUS_AWAITING_APPROVAL
        assert all("[revised" in c.ai_explanation for c in revised.pending_changes)
        assert revised.raw["metadata"]["awaiting_kind"] != "continue_prompt"

    async def test_mixed_decisions_apply_only_approved(self):
        client, fake = make_client()
        await upload_contract(client, session_id="deal-2")

        instruction = "Delete the section on Term; add audit rights after liability"
        job_id = await client.start_edit("deal-2", instruction, approval_mode="ask_every_time")
        snapshot = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        changes = list(snapshot.pending_changes)
        assert len(changes) >= 2
        decisions = [
            ApprovalDecision(change_id=changes[0].change_id, approved=True),
            *[
                ApprovalDecision(change_id=c.change_id, approved=False)
                for c in changes[1:]
            ],
        ]
        before_texts = fake.block_texts("deal-2")
        await client.submit_decisions("deal-2", job_id, decisions)
        final = await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        assert final.status == STATUS_COMPLETED
        after_texts = fake.block_texts("deal-2")
        assert all("runs for two years" not in t for t in after_texts), (
            "approved deletion should have removed the Term block"
        )
        assert any("aggregate liability arising" in t for t in after_texts), (
            "rejected decisions must leave other blocks untouched"
        )
        assert len(after_texts) == len(before_texts) - 1


class TestErrorPaths:
    async def test_unknown_session_404(self):
        client, _ = make_client()
        with pytest.raises(SuperDocsAPIError) as excinfo:
            await client.start_edit("nope", "hello")
        assert excinfo.value.status_code == 404

    async def test_missing_top_level_approved_is_rejected(self):
        client, fake = make_client()
        await upload_contract(client)
        job_id = await client.start_edit("deal-1", CAP_INSTRUCTION, approval_mode="ask_every_time")
        await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        bad_payload = {"job_id": job_id, "changes": [{"change_id": "whatever"}]}
        with pytest.raises(SuperDocsAPIError) as excinfo:
            await fake.post("/v1/chat/deal-1/approve", bad_payload)
        assert excinfo.value.status_code == 422

    async def test_cancel_completed_job_conflicts(self):
        client, fake = make_client()
        await upload_contract(client)
        job_id = await client.start_edit("deal-1", CAP_INSTRUCTION, approval_mode="ask_every_time")
        await wait_for_turnpoint(client, job_id, interval_seconds=0.0)
        with pytest.raises(SuperDocsAPIError) as excinfo:
            await fake.post(f"/v1/jobs/{job_id}/cancel", {})
        assert excinfo.value.status_code == 409

    async def test_job_timeout_raises_informative_error(self):
        class StuckFake(FakeSuperDocs):
            def _advance(self, job):
                return

        stuck = StuckFake()
        client = SuperDocsClient(stuck)
        await upload_contract(client, session_id="s")
        job_id = await client.start_edit("s", CAP_INSTRUCTION, approval_mode="auto")
        with pytest.raises(JobTimeout):
            await wait_for_turnpoint(
                client,
                job_id,
                interval_seconds=0.0,
                max_wait_seconds=0.05,
            )


class TestSessionJobs:
    async def test_list_session_jobs_reports_statuses(self):
        client, _ = make_client()
        await upload_contract(client)
        await client.start_edit("deal-1", CAP_INSTRUCTION, approval_mode="auto")
        jobs = await client.list_session_jobs("deal-1")
        assert len(jobs) == 1
        assert jobs[0].status in {"pending", "in_progress", STATUS_COMPLETED}
