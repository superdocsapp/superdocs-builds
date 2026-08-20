"""Shared fakes so tests never touch the network or need a SuperDocs key."""

from __future__ import annotations

from app.superdocs import ProposedChange


class FakeSuperDocs:
    """Records calls and returns canned data mirroring the polling shape."""

    def __init__(self, changes=None, fail=False):
        self.calls: list[tuple] = []
        self._changes = changes if changes is not None else [
            ProposedChange("c1", "edit", "Insert renewal terms", "<p>old</p>", "<p>new</p>"),
            ProposedChange("c2", "edit", "Update pricing", "<p>$10</p>", "<p>$12</p>"),
        ]
        self._fail = fail

    def upload_document(self, session_id, filename, content):
        self.calls.append(("upload", session_id, filename))
        return {"session_id": session_id, "document_id": "doc1"}

    def chat_edit(self, session_id, message, document_html=None):
        self.calls.append(("chat_edit", session_id, message))
        return "job1"

    def poll_job(self, job_id, **kw):
        self.calls.append(("poll", job_id))
        if self._fail:
            return {"status": "failed", "error": "boom"}
        return {"status": "awaiting_approval",
                "metadata": {"pending_changes": [c.__dict__ | {
                    "ai_explanation": c.summary} for c in self._changes]}}

    def pending_changes(self, job):
        return list(self._changes)

    def approve_changes(self, session_id, job_id, decisions):
        self.calls.append(("approve", session_id, job_id, decisions))
        return {"applied": [d for d in decisions if d["approved"]]}

    def export_document(self, session_id, fmt="docx"):
        self.calls.append(("export", session_id, fmt))
        return b"PK\x03\x04fake-docx"

    def download_url(self, session_id, fmt="docx"):
        self.calls.append(("download", session_id, fmt))
        return {"download_url": f"https://signed.example/{session_id}.{fmt}",
                "filename": f"{session_id}.{fmt}", "expires_in_seconds": 900}

    def session_documents(self, session_id):
        self.calls.append(("roster", session_id))
        return [{"document_id": "doc_primary", "durable_document_id": f"dur-{session_id}",
                 "title": "Doc", "focused": True}]

    def focused_durable_id(self, session_id):
        self.calls.append(("durable", session_id))
        return f"dur-{session_id}"

    def open_documents(self, session_id, document_ids):
        self.calls.append(("open_docs", session_id, tuple(document_ids)))
        return {"session_id": session_id, "opened": list(document_ids),
                "documents": [{"title": "Doc", "focused": True}]}
