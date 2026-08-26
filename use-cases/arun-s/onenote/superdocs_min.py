"""Slim SuperDocs hand-off — the two calls this build needs: send the normalized
document, then export it. Same public API as the main client; kept tiny so this
use-case folder is self-contained. `transport` is injectable for keyless tests.
"""
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
        data = json.dumps(body).encode() if body is not None else None
        if self._t:
            status, text = self._t(method, url, headers, body)
        else:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req) as r:
                status, text = r.status, r.read().decode("utf-8")
        if status >= 400:
            raise RuntimeError(f"SuperDocs {status}: {text[:200]}")
        return text

    def send_document(self, html: str, session_id: str, instruction: str) -> dict:
        """Upload the normalized doc + an edit instruction (SuperDocs chat)."""
        return json.loads(self._req("POST", "/v1/chat/async", {
            "session_id": session_id, "message": instruction,
            "document_html": html, "model_tier": "core", "response_mode": "compact"}))

    def export(self, session_id: str, fmt: str = "docx") -> bytes:
        return self._req("POST", "/v1/documents/export",
                         {"session_id": session_id, "format": fmt}).encode()
