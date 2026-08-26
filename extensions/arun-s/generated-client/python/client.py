"""Thin async client over the SuperDocs REST surface (the four core calls + the
agent lifecycle). This is the hand layer; Task 2.1 formalizes/generates the full
typed client + cross-language conformance suite on top of the same contract."""
from __future__ import annotations
import httpx

class SuperDocs:
    def __init__(self, base_url: str, api_key: str, timeout: float = 300.0, transport=None):
        self._c = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,   # inject httpx.MockTransport for keyless conformance tests
        )

    # --- conformance helpers that encode the real spec ambiguities we found ---
    @staticmethod
    def parse_proposed_change(content):
        """AMBIGUITIES #1: proposed-change content arrives as a JSON-ENCODED STRING;
        it needs a SECOND json.loads. Miss this and every diff field reads undefined."""
        import json as _json
        return _json.loads(content) if isinstance(content, str) else content

    @staticmethod
    def build_approve_body(job_id: str, changes: list[dict], approved: bool = True) -> dict:
        """AMBIGUITIES #3: approve REQUIRES job_id + approved, and identifies changes
        by change_id (NOT chunk_id, which is 'new' for a create)."""
        body: dict = {"job_id": job_id, "approved": approved}
        if changes:
            body["changes"] = [{"change_id": c.get("change_id"), "approved": c.get("approved", approved)}
                               for c in changes]
        return body

    async def aclose(self):
        await self._c.aclose()

    # --- the four core calls (upload happens via document_html / pre-signed uploads) ---
    async def chat_async(self, message, session_id, document_html=None, *,
                         approval_mode=None, model_tier=None, thinking_depth=None,
                         response_mode="compact"):
        body = {"message": message, "session_id": session_id, "response_mode": response_mode}
        if document_html is not None:
            body["document_html"] = document_html
        if approval_mode:
            body["approval_mode"] = approval_mode
        if model_tier:
            body["model_tier"] = model_tier
        if thinking_depth:
            body["thinking_depth"] = thinking_depth
        r = await self._c.post("/v1/chat/async", json=body)
        r.raise_for_status()
        return r.json()

    async def get_job(self, job_id: str):
        r = await self._c.get(f"/v1/jobs/{job_id}")
        r.raise_for_status()
        return r.json()

    async def approve(self, session_id: str, job_id: str, approved: bool = True, *,
                      change_id: str | None = None, feedback: str | None = None,
                      changes: list[dict] | None = None):
        """Approve/deny proposed changes (HITL). The real schema REQUIRES job_id +
        approved, and identifies changes by change_id (NOT chunk_id — the prose is
        misleading; see AMBIGUITIES.md #3). Single: pass change_id. Batch
        ("Accept All"): pass changes=[{change_id, approved, feedback?}]."""
        body: dict = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            body["change_id"] = change_id
        if feedback is not None:
            body["feedback"] = feedback
        if changes is not None:
            body["changes"] = changes
        r = await self._c.post(f"/v1/chat/{session_id}/approve", json=body)
        r.raise_for_status()
        return r.json()

    async def export(self, session_id: str, fmt: str = "docx") -> bytes:
        r = await self._c.post("/v1/documents/export",
                               json={"session_id": session_id, "format": fmt})
        r.raise_for_status()
        return r.content

    # --- agent lifecycle: the no-human-in-the-loop demo ---
    @staticmethod
    async def agent_signup(base_url: str, agent_name: str):
        async with httpx.AsyncClient(base_url=base_url.rstrip("/")) as c:
            r = await c.post("/v1/agents/signup",
                             json={"terms_accepted": True, "agent_name": agent_name})
            r.raise_for_status()
            return r.json()

    async def whoami(self):
        r = await self._c.get("/v1/agents/whoami")
        r.raise_for_status()
        return r.json()
