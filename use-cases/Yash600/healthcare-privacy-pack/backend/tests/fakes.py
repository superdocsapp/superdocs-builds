"""
fakes.py -- fake SuperDocsClient and LLMClient for testing main.py's
business logic without a live SuperDocs key or a live Groq key.
Mirrors the pattern already established in test_validator.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from superdocs_client import SuperDocsClient


class FakeSuperDocsClient:
    """
    Minimal stand-in for SuperDocsClient. Documents are tracked by a
    durable id the fake assigns on upload; `html[durable_id]` is mutable
    so a test can simulate "SuperDocs applied the edit" before the code
    under test re-fetches the document post-approval.
    """

    extract_pending_changes = staticmethod(SuperDocsClient.extract_pending_changes)

    def __init__(self):
        self.html: dict[str, str] = {}
        self.jobs: dict[str, dict] = {}
        self._next_job_result: dict | None = None
        self.templates: list[dict] = []
        self._next_chat_html: str | None = None

    # -- upload -------------------------------------------------------
    def upload_document_base64(self, filename, html_or_bytes, session_id, return_html=False, is_html_text=True):
        durable_id = f"doc-{uuid4()}"
        html = html_or_bytes.decode("utf-8") if isinstance(html_or_bytes, bytes) else html_or_bytes
        self.html[durable_id] = html
        self._last_session_to_doc = (session_id, durable_id)
        return {"version_id": "v1", "_durable_id": durable_id}

    def list_session_documents(self, session_id):
        session_id_used, durable_id = self._last_session_to_doc
        assert session_id_used == session_id
        return {"documents": [{"durable_document_id": durable_id}]}

    def get_document(self, document_id, include_html=False):
        out = {"document_id": document_id, "structure": {"headings": []}}
        if include_html:
            out["html"] = self.html.get(document_id, "")
        return out

    # -- templates --------------------------------------------------------
    def upload_template_base64(self, filename, html_or_bytes):
        template_id = f"tmpl-{uuid4()}"
        self.templates.append({"id": template_id, "filename": filename, "name": filename})
        return {"id": template_id, "filename": filename}

    def list_templates(self):
        return {"templates": list(self.templates)}

    def delete_template(self, template_id):
        self.templates = [t for t in self.templates if t["id"] != template_id]
        return {"status": "ok"}

    # -- chat (sync, used for "create a document from scratch") -----------
    def queue_chat_html(self, html: str) -> None:
        """Set the canned document HTML the NEXT chat() call returns."""
        self._next_chat_html = html

    def chat(self, session_id, message, document_html=None, approval_mode=None, model_tier=None):
        html = self._next_chat_html or f"<h1>{message[:60]}</h1><p>[drafted content]</p>"
        self._next_chat_html = None
        durable_id = f"doc-{uuid4()}"
        self.html[durable_id] = html
        self._last_session_to_doc = (session_id, durable_id)
        return {"session_id": session_id, "document_changes": {"updated_html": html}}

    # -- chat_async -------------------------------------------------------
    def chat_async(self, session_id, message, document_html=None, approval_mode="ask_every_time", model_tier=None):
        job_id = f"job-{uuid4()}"
        self.jobs[job_id] = self._next_job_result or {"status": "pending", "metadata": {}}
        self._next_job_result = None
        return {"job_id": job_id, "session_id": session_id, "status": "pending"}

    def get_job(self, job_id):
        return self.jobs[job_id]

    def approve_change(self, session_id, job_id, change_id=None, approved=True, feedback=None):
        return {"status": "ok"}

    def poll_job_until_done(self, job_id, **kwargs):
        return {"status": "completed", "result": {"document_changes": {"version_id": "v2"}}}

    # -- export -----------------------------------------------------------
    def export(self, session_id=None, html=None, fmt="docx", filename=None):
        return b"FAKE-EXPORT-BYTES"

    # -- test helpers -----------------------------------------------------
    def queue_job_result(self, job_id_placeholder_result: dict) -> None:
        """Set the canned result the NEXT chat_async call's job_id will return from get_job()."""
        self._next_job_result = job_id_placeholder_result


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    model: str = "fake-model"


@dataclass
class _FakeRelationship:
    procedure_section_id: str
    policy_section_id: str
    confidence: float
    reason: str


@dataclass
class _FakeResult:
    relationships: list
    usage: _FakeUsage


class FakeLLMClient:
    """Returns a canned set of relationships, keyed by (policy_title, procedure_title)
    so different pairs in a multi-pair test can get different answers."""

    def __init__(self):
        self.canned: dict[tuple[str, str], list[tuple[str, str, float, str]]] = {}
        self.calls: list[tuple[str, str]] = []

    def set_canned(self, policy_title, procedure_title, relationships):
        self.canned[(policy_title, procedure_title)] = relationships

    def discover_references(self, policy_title, policy_sections, procedure_title, procedure_sections):
        self.calls.append((policy_title, procedure_title))
        raw = self.canned.get((policy_title, procedure_title), [])
        rels = [_FakeRelationship(proc_id, pol_id, conf, reason) for (proc_id, pol_id, conf, reason) in raw]
        return _FakeResult(relationships=rels, usage=_FakeUsage())
