"""Slim SuperDocs hand-off — send the document + an edit instruction, then export.
Same public API as the main client; injectable transport for keyless tests."""
from __future__ import annotations
import json
import os
import urllib.request

BASE = os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app")


class SuperDocs:
    def __init__(self, api_key: str | None = None, base: str = BASE, transport=None):
        self.key = api_key or os.getenv("SUPERDOCS_API_KEY", "")
        self.base = base
        self._t = transport   # callable(method, url, headers, body) -> (status, text)

    def _req(self, method: str, path: str, body: dict | None = None) -> str:
        url = self.base + path
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self._t:
            status, text = self._t(method, url, headers, body)
        else:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                         headers=headers, method=method)
            with urllib.request.urlopen(req) as r:
                status, text = r.status, r.read().decode("utf-8")
        if status >= 400:
            raise RuntimeError(f"SuperDocs {status}: {text[:200]}")
        return text

    def send_document(self, html: str, session_id: str, instruction: str) -> dict:
        return json.loads(self._req("POST", "/v1/chat/async", {
            "session_id": session_id, "message": instruction,
            "document_html": html, "model_tier": "core", "response_mode": "compact"}))

    def export(self, session_id: str, fmt: str = "docx") -> bytes:
        return self._req("POST", "/v1/documents/export",
                         {"session_id": session_id, "format": fmt}).encode()


def insert_clause(superdocs: SuperDocs, document_html: str, clause_text: str,
                  section_hint: str, session_id: str = "clause-insert") -> bytes:
    """Insert a chosen clause into the document via SuperDocs, adapting party names,
    defined terms and numbering to the host document — nothing else is touched."""
    instruction = (f"Insert this clause into the {section_hint} section, adapting party names, defined "
                   f"terms and numbering to this document; change nothing else. Clause: {clause_text}")
    superdocs.send_document(document_html, session_id, instruction)
    return superdocs.export(session_id, "docx")
