"""A document that no longer exists is not a transient failure.

Applying a fix to a document ingested days earlier surfaced as:

    open failed: SuperDocs POST /v1/sessions/.../documents/open failed [404]:
    {"detail":"None of the requested documents were found."}

which reads like an outage. It was not. The id stored for those documents was
a `version_id` (the removed pre-resolution fallback), and separately the
documents themselves had been overwritten because every upload shared one
session. Retrying can never fix either, so the two cases are reported
distinctly and the remedy — re-ingest — is named.
"""

import hashlib

import pytest

from agents.editor import review_api
from agents.editor.editor import ApplyOutcome, Editor
from core.superdocs_client import MockSuperDocsClient, SuperDocsError

from tests.editor.test_apply_writeback import FakeDB, _finding_row


def chunk(cid, html):
    return {"chunk_id": cid, "html": html,
            "content_hash": hashlib.sha256(html.encode()).hexdigest()}


class GoneClient(MockSuperDocsClient):
    """Open 404s and the document genuinely is not retrievable."""

    async def open_documents(self, document_ids):
        raise SuperDocsError(
            "SuperDocs POST /v1/sessions/s/documents/open failed [404]: "
            '{"detail":"None of the requested documents were found."}'
        )

    async def document_exists(self, doc_id):
        return False


class FlakyClient(MockSuperDocsClient):
    """Open fails, but the document is still there — a real transient."""

    async def open_documents(self, document_ids):
        raise SuperDocsError("SuperDocs POST .../open failed [503]: upstream timeout")

    async def document_exists(self, doc_id):
        return True


class SessionRecorder(MockSuperDocsClient):
    """Records which session each editing call was issued against."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.used: list[str] = []

    async def open_documents(self, document_ids):
        self.used.append(self.session_id)
        return {"opened": document_ids}

    async def focus_document(self, document_id):
        self.used.append(self.session_id)
        return {"focused": document_id}

    async def get_document_chunks(self, doc_id):
        self.used.append(self.session_id)
        return [chunk("c1", "<p>npm install</p>")]

    async def chat_async(self, message, approval_mode="ask_every_time",
                         model_tier="max", document_id=None):
        self.used.append(self.session_id)
        return "job-1"

    async def get_job(self, job_id):
        return {"job_id": job_id, "status": "completed", "metadata": {}}


class TestMissingDocumentIsNamedAsSuch:
    @pytest.mark.asyncio
    async def test_reports_the_document_is_gone_not_a_generic_open_failure(self):
        out = await Editor(GoneClient(), poll_interval=0.001, poll_timeout=1).apply_fix(
            "gone-id", "c1", "a", "b"
        )
        assert out["status"] == ApplyOutcome.FAILED
        assert out["document_missing"] is True
        assert "no longer exists" in out["reason"]

    @pytest.mark.asyncio
    async def test_names_re_ingest_as_the_remedy(self):
        out = await Editor(GoneClient(), poll_interval=0.001, poll_timeout=1).apply_fix(
            "gone-id", "c1", "a", "b"
        )
        assert "re-ingest" in out["reason"].lower()

    @pytest.mark.asyncio
    async def test_a_transient_failure_is_not_mislabelled_as_missing(self):
        """A 503, or a 404 on a document that does still exist, must stay a
        retryable failure — calling it 'gone' would send people to re-ingest a
        document that is fine."""
        out = await Editor(FlakyClient(), poll_interval=0.001, poll_timeout=1).apply_fix(
            "live-id", "c1", "a", "b"
        )
        assert out["status"] == ApplyOutcome.FAILED
        assert not out.get("document_missing")
        assert "open failed" in out["reason"]


class TestApplyStatusForAMissingDocument:
    @pytest.mark.asyncio
    async def test_status_is_document_missing_not_failed(self, monkeypatch):
        """Different remedy, different state: 'failed' invites a retry that
        cannot succeed."""
        db = FakeDB(stored_chunks=[]).install(monkeypatch)

        class StubEditor:
            def __init__(self, *a, **kw):
                pass

            async def apply_fix(self, **kw):
                return {"status": ApplyOutcome.FAILED, "document_missing": True,
                        "reason": "This document no longer exists in SuperDocs"}

        monkeypatch.setattr("agents.editor.editor.Editor", StubEditor)

        await review_api._apply_one(_finding_row(), _finding_row()["run_id"])

        final = [u for u in db.updates if u[0] == "findings"][-1]
        assert final[2]["apply_status"] == review_api.ApplyStatus.DOCUMENT_MISSING

    @pytest.mark.asyncio
    async def test_an_empty_document_id_also_asks_for_re_ingest(self, monkeypatch):
        """An upload that never produced a durable id stores "", which no
        retry can turn into a document."""
        db = FakeDB().install(monkeypatch)
        row = _finding_row() | {"superdocs_doc_id": ""}

        out = await review_api._apply_one(row, row["run_id"])

        assert out["status"] == ApplyOutcome.FAILED
        assert db.updates[-1][2]["apply_status"] == review_api.ApplyStatus.DOCUMENT_MISSING
        assert "re-ingest" in db.updates[-1][2]["apply_reason"].lower()


class TestEditsUseTheDocumentsOwnSession:
    @pytest.mark.asyncio
    async def test_editing_targets_the_documents_session(self):
        """Every editing call is session-scoped. Issuing them against the
        global session would edit whatever document that session holds."""
        sd = SessionRecorder(session_id="global")
        await Editor(sd, poll_interval=0.001, poll_timeout=1).apply_fix(
            "doc-1", "c1", "npm install", "pnpm install", session_id="global-doc-abc"
        )
        assert sd.used, "no session-scoped call was made"
        assert set(sd.used) == {"global-doc-abc"}

    @pytest.mark.asyncio
    async def test_falls_back_to_the_global_session_when_none_is_recorded(self):
        sd = SessionRecorder(session_id="global")
        await Editor(sd, poll_interval=0.001, poll_timeout=1).apply_fix(
            "doc-1", "c1", "npm install", "pnpm install", session_id=None
        )
        assert set(sd.used) == {"global"}
