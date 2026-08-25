"""
A fake SuperDocsClient with the exact same public method signatures as the
real one, so DocumentWorkflow and the precedent-search AI-summary path can be
exercised in tests with zero network calls and no API key.

Updated after live Postman validation against the real API on 2026-08-12 to
match reality in two ways:

1. Field names now match the REAL response shape: change_id, operation,
   chunk_id, document_id, old_html, new_html, ai_explanation - not the
   originally-guessed summary/diff_html.

2. chat_async() now REPLICATES the real bug we found live: if document_html
   is not provided, the fake AI can't see the document either, and returns a
   completed job with no pending changes and a clarifying-question response -
   exactly what the real API did. This means the fix in workflow.py (always
   sending the cached latest HTML) is now actually tested: a regression that
   removes that fix would make test_workflow_with_mocked_superdocs.py fail
   loudly, instead of us needing to catch it by hand in Postman again.
"""
from __future__ import annotations

import base64
import itertools
import uuid

from app.superdocs.client import JobState, PendingChange

_job_counter = itertools.count(1)

CLARIFYING_QUESTION = (
    "I'd be happy to help with that. Could you please specify which "
    "document you are referring to, or provide the text you would like "
    "me to update?"
)


class FakeSession:
    def __init__(self, html: str):
        self.html = html
        self.pending_change: dict | None = None  # {job_id, change_id, new_html}


class FakeSuperDocsClient:
    def __init__(self):
        self.sessions: dict[str, FakeSession] = {}
        self.jobs: dict[str, dict] = {}
        # Test hooks / audit trail:
        self.uploaded_attachments: list[dict] = []
        self.upload_calls: list[dict] = []
        self.export_calls: list[dict] = []
        self.chat_calls: list[dict] = []  # audit trail for document_html checks
        # Test hook to simulate SuperDocs' documented propagation lag: "job
        # status can report completed before the session's actual document
        # content has been updated server-side". Set
        # stale_export_countdown[session_id] = N to make the next N calls to
        # export_document(session_id=...) (NOT html=... calls) return the
        # PRE-approval content instead of the current session content.
        self.stale_export_countdown: dict[str, int] = {}
        self._pre_approval_html: dict[str, str] = {}
        # Test hook to replicate a real behavior found live: approving a
        # change can come back with status="awaiting_approval" again and a
        # NEW pending change that was never part of the original propose_edit
        # response. Set surface_extra_change_on_approval[session_id] = a
        # pending-change dict (see the shape used in chat_async below) to
        # have the NEXT approve_changes_for_session() call on that session
        # surface it - consumed once, then cleared.
        self.surface_extra_change_on_approval: dict[str, dict] = {}
        # Test hook to replicate a real behavior found live: the approve
        # response can still list the change_id that was JUST decided in the
        # same call, as if it were still pending - an eventual-consistency
        # echo. Set echo_decided_change_back[session_id] = True to have the
        # NEXT approve_changes_for_session() call on that session include the
        # just-decided change in its returned pending_changes.
        self.echo_decided_change_back: dict[str, bool] = {}

    # ---------- 1. upload ----------

    def upload_document_base64(self, filename, file_base64, session_id, return_html=True):
        html = base64.b64decode(file_base64).decode("utf-8")
        self.sessions[session_id] = FakeSession(html=html)
        self.upload_calls.append({"filename": filename, "session_id": session_id})
        return {"session_id": session_id, "chunks_count": html.count("<h") + html.count("<p")}

    # ---------- 2. edit ----------

    def chat_async(
        self,
        session_id,
        message,
        document_html=None,
        approval_mode="ask_every_time",
        model_tier=None,
        response_mode="full",
    ):
        if session_id not in self.sessions:
            raise KeyError(f"No such session: {session_id}. Call upload_document_base64 first.")
        self.chat_calls.append(
            {"session_id": session_id, "document_html_provided": document_html is not None}
        )

        job_id = f"job-{next(_job_counter)}"
        session = self.sessions[session_id]

        if document_html is None:
            # Replicates the REAL bug found live: no document_html means the
            # AI can't see the document, so it asks a clarifying question
            # instead of proposing an edit. Job completes immediately, no
            # pending_changes - status="completed" with nothing to review.
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "completed",
                "session_id": session_id,
                "metadata": {"pending_changes": []},
                "result": {
                    "response": CLARIFYING_QUESTION,
                    "document_changes": {"updated_html": session.html},
                },
            }
            return job_id

        change_id = f"change-{uuid.uuid4().hex[:8]}"
        new_html = document_html + f'\n<p data-chunk-id="{change_id}">[AI-EDIT: {message}]</p>'
        session.pending_change = {
            "job_id": job_id,
            "change_id": change_id,
            "base_html": document_html,
            "new_html": new_html,
            "message": message,
        }
        self.jobs[job_id] = {
            "job_id": job_id,
            "status": "awaiting_approval",
            "session_id": session_id,
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": change_id,
                        "operation": "create",
                        "chunk_id": "new",
                        "document_id": "doc_primary",
                        "old_html": None,
                        "new_html": f'<p>[AI-EDIT: {message}]</p>',
                        "ai_explanation": f"I have made the requested change: {message}",
                    }
                ]
            },
            "result": None,
        }
        return job_id

    def get_job(self, job_id) -> JobState:
        job = self.jobs[job_id]
        pending = [
            PendingChange(
                change_id=c["change_id"],
                chunk_id=c.get("chunk_id"),
                operation=c.get("operation"),
                old_html=c.get("old_html"),
                new_html=c.get("new_html"),
                ai_explanation=c.get("ai_explanation"),
                document_id=c.get("document_id"),
                raw=c,
            )
            for c in job["metadata"]["pending_changes"]
        ]
        document_html = None
        if job.get("result") and isinstance(job["result"].get("document_changes"), dict):
            document_html = job["result"]["document_changes"].get("updated_html")
        elif job["status"] == "awaiting_approval":
            document_html = self.sessions[job["session_id"]].html

        return JobState(
            job_id=job_id,
            status=job["status"],
            pending_changes=pending,
            document_html=document_html,
            raw=job,
        )

    def poll_job(self, job_id, **kwargs) -> JobState:
        return self.get_job(job_id)

    # ---------- 3. approve ----------

    def approve_changes_for_session(self, session_id, job_id, decisions) -> JobState:
        session = self.sessions[session_id]
        job = self.jobs[job_id]
        pending = session.pending_change
        pre_approval_html = session.html
        decided_raw = list(job["metadata"]["pending_changes"])
        if pending and pending["job_id"] == job_id:
            for decision in decisions:
                if decision["change_id"] == pending["change_id"] and decision["approved"]:
                    session.html = pending["new_html"]
        if session.html != pre_approval_html:
            self._pre_approval_html[session_id] = pre_approval_html
        session.pending_change = None
        job["status"] = "completed"
        job["metadata"]["pending_changes"] = []
        job["result"] = {
            "response": "Change applied.",
            "document_changes": {"updated_html": session.html},
        }

        if self.echo_decided_change_back.pop(session_id, False):
            job["status"] = "awaiting_approval"
            job["metadata"]["pending_changes"] = decided_raw

        extra = self.surface_extra_change_on_approval.pop(session_id, None)
        if extra is not None:
            job["status"] = "awaiting_approval"
            job["metadata"]["pending_changes"] = [extra]
            session.pending_change = {
                "job_id": job_id,
                "change_id": extra["change_id"],
                "base_html": session.html,
                "new_html": session.html + f"\n{extra['new_html']}",
                "message": "(surfaced after approval)",
            }

        return self.get_job(job_id)

    # ---------- 4. export ----------

    def export_document(self, format="docx", html=None, session_id=None, options=None) -> bytes:
        self.export_calls.append({"format": format, "session_id": session_id})
        if html is not None:
            content = html
        elif session_id is not None and self.stale_export_countdown.get(session_id, 0) > 0:
            # Replicates the real "completed but not yet propagated" lag:
            # this export call lands before the session has caught up to the
            # approval it already reported as done.
            self.stale_export_countdown[session_id] -= 1
            content = self._pre_approval_html[session_id]
        else:
            content = self.sessions[session_id].html
        if format == "html":
            return content.encode("utf-8")
        return f"FAKE-{format.upper()}::{content}".encode("utf-8")

    # ---------- attachments ----------

    def upload_attachment_base64(self, filename, file_base64, session_id):
        content = base64.b64decode(file_base64).decode("utf-8")
        self.uploaded_attachments.append(
            {"filename": filename, "session_id": session_id, "content": content}
        )
        return f"attach-job-{next(_job_counter)}"
