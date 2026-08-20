"""
fakes.py -- FakeSuperDocsClient, an in-memory stand-in for superdocs_client
.SuperDocsClient, used so the test suite never needs a live SUPERDOCS_API_KEY
or a real network call. Mirrors the exact method signatures main.py calls
(upload_document_base64, list_session_documents, get_document,
upload_image_base64, chat, chat_async, poll_job_until_done,
approve_changes_batch, export) with behavior good enough to exercise every
code path in main.py: uploading, an edit that proposes exactly one change
(so extract_pending_changes/approve/reject all have something real to work
with), and a synchronous image-embed edit.

Per the standing project rule: nothing in this suite talks to the real
SuperDocs API or a real LLM -- this fake is the only thing main.py's
SuperDocsClient dependency is ever swapped for in tests.
"""

from __future__ import annotations

import re
import uuid
from typing import Any


class FakeSuperDocsError(RuntimeError):
    pass


class FakeSuperDocsClient:
    def __init__(self):
        self._docs: dict[str, str] = {}          # durable_document_id -> html
        self._sessions: dict[str, list[str]] = {}  # session_id -> [durable_document_id]
        self._jobs: dict[str, dict] = {}
        self.fail_next_chat_async = False

    # -- upload -------------------------------------------------------- #

    def upload_document_base64(
        self,
        filename: str,
        html_or_bytes,
        session_id: str,
        return_html: bool = True,
        is_html_text: bool = True,
    ) -> dict:
        if isinstance(html_or_bytes, bytes):
            text = html_or_bytes.decode("utf-8", errors="ignore")
        else:
            text = str(html_or_bytes)

        if is_html_text:
            html = text
        else:
            # simulate SuperDocs converting a non-HTML upload (docx/txt/etc)
            html = f"<h1>{filename}</h1><p>{text or 'converted content'}</p>"

        durable_id = f"doc-{uuid.uuid4().hex[:8]}"
        self._docs[durable_id] = html
        self._sessions.setdefault(session_id, []).append(durable_id)
        return {"document_id": durable_id, "version_id": f"v-{uuid.uuid4().hex[:8]}"}

    def upload_image_base64(self, filename: str, image_bytes: bytes) -> dict:
        return {"url": f"https://fake-superdocs.test/images/{filename}"}

    def list_session_documents(self, session_id: str) -> dict:
        return {"documents": [{"durable_document_id": d} for d in self._sessions.get(session_id, [])]}

    def get_document(self, document_id: str, include_html: bool = False) -> dict:
        return {"id": document_id, "html": self._docs.get(document_id, "")}

    # -- chat (sync) ----------------------------------------------------- #

    def chat(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str | None = None,
        model_tier: str | None = None,
    ) -> dict:
        doc_html = document_html or ""
        img_match = re.search(r"<img[^>]*>", message)
        if img_match:
            img_tag = img_match.group(0)
            if "</h1>" in doc_html:
                updated = doc_html.replace("</h1>", "</h1>" + img_tag, 1)
            else:
                updated = img_tag + doc_html
        elif doc_html.strip() in ("", "<p></p>"):
            # Generative "create from scratch" request (e.g. the campaign-
            # level Assistant, which always starts from a blank draft doc).
            title_match = re.search(r'"([^"]{3,80})"', message)
            title = title_match.group(1) if title_match else "Generated Draft"
            updated = f"<h2>{title}</h2><p>{message}</p>"
        else:
            updated = doc_html
        return {
            "document_changes": {"updated_html": updated, "version_id": f"v-{uuid.uuid4().hex[:8]}"},
            "usage": {"was_billable": True},
        }

    # -- chat (async + HITL) --------------------------------------------- #

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
    ) -> dict:
        if self.fail_next_chat_async:
            self.fail_next_chat_async = False
            raise FakeSuperDocsError("simulated SuperDocs outage")

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        doc_html = document_html or ""

        # Simulate SuperDocs' real behavior for "add a new section" style
        # requests: this is an *insertion*, not a find/replace, so it comes
        # back with an empty old_html and a brand-new chunk in new_html --
        # exercises the insert path in main.py's _apply_pending_change.
        if re.search(r"\b(add|insert)\b.*\bsection\b", message, re.IGNORECASE):
            section_title = "Summary"
            title_match = re.search(r'"([^"]+)"|\'([^\']+)\'', message)
            if title_match:
                section_title = title_match.group(1) or title_match.group(2)
            old_html = ""
            new_html = f"<h2>{section_title}</h2><p>{message}</p>"
            operation = "insert"
        else:
            match = re.search(r"<p>.*?</p>", doc_html, re.DOTALL)
            if match:
                old_html = match.group(0)
                new_html = f"<p>{message}</p>"
            else:
                old_html = doc_html
                new_html = doc_html + f"<p>{message}</p>"
            operation = "edit"

        change = {
            "change_id": f"chg-{uuid.uuid4().hex[:8]}",
            "operation": operation,
            "chunk_id": "c1",
            "document_id": None,
            "old_html": old_html,
            "new_html": new_html,
            "ai_explanation": f"Applied: {message}",
        }
        self._jobs[job_id] = {
            "job_id": job_id,
            "session_id": session_id,
            "status": "awaiting_approval",
            "metadata": {"pending_changes": [change]},
        }
        return {"job_id": job_id, "session_id": session_id, "status": "pending"}

    def get_job(self, job_id: str) -> dict:
        return self._jobs[job_id]

    def poll_job_until_done(self, job_id: str, **kwargs) -> dict:
        return self._jobs[job_id]

    def approve_changes_batch(self, session_id: str, job_id: str, decisions: list[dict[str, Any]]) -> dict:
        return {"status": "ok", "job_id": job_id, "decisions": decisions}

    # -- export ------------------------------------------------------------ #

    def export(
        self,
        session_id: str | None = None,
        html: str | None = None,
        fmt: str = "docx",
        filename: str | None = None,
    ) -> bytes:
        return f"FAKE-{fmt.upper()}-EXPORT-CONTENT".encode("utf-8")
