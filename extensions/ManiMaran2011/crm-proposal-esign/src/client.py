"""
Thin wrapper around the real SuperDocs REST API. Every method maps to exactly one documented endpoint —
no cleverness here, so a diff against docs.superdocs.app stays trivial. Business logic (chunk protection,
verification, glossary grounding, revision handling) lives in the other modules and never calls `requests`
directly; they only ever see this interface (or FakeSuperDocsClient, same shape).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

BASE_URL = "https://api.superdocs.app"


class SuperDocsError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SuperDocs API error {status_code}: {detail}")


@dataclass
class ChunkedDocument:
    html: str
    session_id: str
    chunks_count: int
    version_id: str


class SuperDocsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY not set. Get one from use.superdocs.app > Settings > API Keys.")
        self._headers = {"Authorization": f"Bearer {self.api_key}"}

    def _raise_for_status(self, resp: requests.Response):
        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise SuperDocsError(resp.status_code, detail)

    def upload_document(self, filepath: str, session_id: str) -> ChunkedDocument:
        with open(filepath, "rb") as f:
            resp = requests.post(
                f"{BASE_URL}/v1/documents/upload",
                headers=self._headers,
                files={"file": f},
                data={"session_id": session_id},
            )
        self._raise_for_status(resp)
        body = resp.json()
        return ChunkedDocument(html=body["html"], session_id=session_id, chunks_count=body["chunks_count"], version_id=body["version_id"])

    def chat(self, session_id: str, message: str, document_html: Optional[str] = None) -> dict:
        payload = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        resp = requests.post(f"{BASE_URL}/v1/chat", headers=self._headers, json=payload)
        self._raise_for_status(resp)
        return resp.json()

    def export(self, session_id: str, fmt: str = "docx", filename: Optional[str] = None) -> bytes:
        payload = {"session_id": session_id, "format": fmt}
        if filename:
            payload["options"] = {"filename": filename}
        resp = requests.post(f"{BASE_URL}/v1/documents/export", headers=self._headers, json=payload)
        self._raise_for_status(resp)
        return resp.content

    def load_html_as_document(self, session_id: str, html: str) -> None:
        """Replaces the session's active document with EXACT html, verbatim, no AI turn involved --
        wraps POST /v1/documents/upload-base64 with parse_mode='document' (the documented 'reliable way to
        REPLACE a session's document with exact content you already hold'). Non-billable per the docs.

        This exists because of a real bug found in production use (2026-08-22): repair_protected_chunks()
        fixes corrupted content LOCALLY, in this process's memory, but export() pulls the document from
        SuperDocs' SERVER-SIDE session state. Without this call, export() returns the AI's original
        (unrepaired) output every time -- the local fix never reaches the server, so the exported file
        silently contains the wrong content despite verification reporting success. This method is the
        missing sync step: call it with the repaired html BEFORE exporting.
        """
        import base64
        encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
        resp = requests.post(
            f"{BASE_URL}/v1/documents/upload-base64",
            headers=self._headers,
            json={
                "session_id": session_id,
                "filename": "repaired.html",
                "file_base64": encoded,
                "parse_mode": "document",
            },
        )
        self._raise_for_status(resp)
