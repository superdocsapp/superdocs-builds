"""
Thin REST client over the four core SuperDocs operations plus the handful
of read endpoints this build needs. Every method here maps to a call this
build actually makes and has been verified against the real API while
building it -- see PROGRESS.md for the exact request/response shapes that
weren't obvious from the docs alone (particularly the approve endpoint's
required top-level job_id + approved fields, discovered from a live 422).
"""

import httpx


class SuperDocsError(RuntimeError):
    pass


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app"):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs):
        r = httpx.request(method, f"{self._base_url}{path}", headers=self._headers, timeout=60, **kwargs)
        if r.status_code >= 400:
            raise SuperDocsError(f"{method} {path} -> HTTP {r.status_code}: {r.text}")
        return r.json()

    def whoami(self) -> dict:
        return self._request("GET", "/v1/agents/whoami")

    def init_session(self, document_ids: list[str] | None = None) -> dict:
        return self._request("POST", "/v1/sessions/init", json={"document_ids": document_ids or []})

    def chat(self, session_id: str, message: str) -> dict:
        """Synchronous edit -- used only for one-time document creation in
        this build. Ongoing owned-section updates use chat_async + approve
        instead, so they go through Review every time (see living_doc_agent.py)."""
        return self._request("POST", "/v1/chat", json={"session_id": session_id, "message": message})

    def chat_async(self, session_id: str, message: str, approval_mode: str = "ask_every_time") -> dict:
        return self._request(
            "POST",
            "/v1/chat/async",
            json={"session_id": session_id, "message": message, "approval_mode": approval_mode},
        )

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{job_id}")

    def approve_changes(self, session_id: str, job_id: str, change_ids: list[str]) -> dict:
        return self._request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json={
                "job_id": job_id,
                "approved": True,
                "changes": [{"change_id": cid, "approved": True} for cid in change_ids],
            },
        )

    def reject_changes(self, session_id: str, job_id: str, change_ids: list[str], feedback: str | None = None) -> dict:
        body = {
            "job_id": job_id,
            "approved": False,
            "changes": [{"change_id": cid, "approved": False} for cid in change_ids],
        }
        if feedback:
            body["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=body)

    def list_session_documents(self, session_id: str) -> dict:
        return self._request("GET", f"/v1/sessions/{session_id}/documents")

    def get_document(self, document_id: str, include_html: bool = False) -> dict:
        return self._request(
            "GET", f"/v1/documents/{document_id}", params={"include_html": str(include_html).lower()}
        )

    def get_session_history(self, session_id: str) -> dict:
        return self._request("GET", f"/v1/sessions/{session_id}/history")
