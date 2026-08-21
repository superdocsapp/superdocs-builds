"""Test fixtures.

Nothing here touches the network or needs a key. The SuperDocs client is
exercised against a fake *transport* rather than a mocked client, so the tests
cover the request shapes, the double-parse of proposed changes, the error
mapping and the budget — the parts most likely to be wrong — instead of
verifying that a mock returns what the mock was told to return.
"""

from __future__ import annotations

import json
import pathlib
import re
from pathlib import Path

import httpx
import pytest

from packet.order import Order
from packet.superdocs import Ledger, SuperDocs

ORDER_PATH = Path(__file__).resolve().parent.parent / "orders" / "acme-fiber-SO-40188.yaml"


@pytest.fixture
def order() -> Order:
    return Order.load(ORDER_PATH)


def _multipart_file_body(raw: str) -> str:
    """The file part of a multipart body, and only the file part.

    Splitting on the second blank line lands in the *session_id* field, not the
    document — which stored the wrong text and made every "did the edit land"
    check meaningless.
    """
    marker = 'name="file"'
    start = raw.find(marker)
    if start < 0:
        return ""
    body_start = raw.find("\r\n\r\n", start)
    if body_start < 0:
        return ""
    body_start += 4
    boundary_end = raw.find("\r\n--", body_start)
    return raw[body_start:boundary_end if boundary_end > 0 else len(raw)]


class FakeSuperDocs:
    """A stand-in for the API that records what it was asked.

    Behaves the way the documentation says the real service behaves, including
    the awkward parts: an upload returns the session roster, a HITL job pauses
    before it completes, and the proposed changes arrive JSON-encoded inside a
    JSON field.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.documents: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self._job_seq = 0
        self.approvals: list[dict] = []
        self.encode_pending_as_string = False
        self.replaced_focus = 0
        # Fields the fake will pretend it could not apply, so a test can
        # exercise the repair pass. Values are the `after` strings to drop.
        self.drop_values: set[str] = set()
        self.pending_apply: dict[str, tuple] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        # Multipart bodies are not JSON. Parsing every request as JSON is how
        # the fake used to reject the very endpoint the real build depends on.
        body: dict = {}
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            try:
                body = json.loads(request.content)
            except json.JSONDecodeError:
                body = {}
        self.requests.append((request.method, path, body))

        if path.endswith("/documents/upload-base64"):
            # The real base64 endpoint returns NO document id and NO roster —
            # it replaces the session's focused document. The fake used to
            # invent both, which is precisely why the offline suite was green
            # while the live build produced a manifest full of nulls. It now
            # lies the way the real endpoint does.
            self.replaced_focus += 1
            return httpx.Response(200, json={
                "session_id": body.get("session_id"),
                "filename": body["filename"],
                "chunks_count": 12,
                "version_id": "ver_stub",
                "html": None,
                "page_setup": None,
                "persisted": True,
            })
        if path.endswith("/documents/upload"):
            return self._upload_multipart(request)
        if path.endswith("/chat"):
            return httpx.Response(
                200,
                json={
                    "response": "done",
                    "document_changes": {"updated_html": "<p>edited</p>"},
                    "usage": {"monthly_used": 1, "monthly_limit": 10000},
                },
            )
        if path.endswith("/chat/async"):
            return self._chat_async(body)
        if "/approve" in path:
            self.approvals.append(body)
            job = self.jobs.get(body["job_id"])
            if job is not None:
                job["status"] = "completed"
            self._apply_approved(body)
            return httpx.Response(200, json={"status": "resumed"})
        if "/continue" in path:
            self.jobs[body["job_id"]]["status"] = "completed"
            return httpx.Response(200, json={"status": "resumed"})
        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.jobs.get(job_id, {"status": "completed"}))
        if path.endswith("/documents/export"):
            # Export takes a session_id and no document_id, so in a
            # multi-document session it returns the FOCUSED document. The fake
            # behaves the same way, which is what lets a test catch a verifier
            # that assumed otherwise.
            if body.get("session_id"):
                mine = [
                    m for m in self.documents.values() if m["session"] == body["session_id"]
                ]
                content = (mine[-1]["html"] if mine else "").encode()
            else:
                content = (body.get("html") or "").encode()
            return httpx.Response(
                200,
                content=content or b"# exported\n",
                headers={"Content-Type": "application/octet-stream"},
            )
        if path.endswith("/documents") and "/sessions/" in path and request.method == "GET":
            session = path.split("/sessions/")[1].split("/")[0]
            include_html = "include_html=true" in (request.url.query or b"").decode()
            mine = {d: m for d, m in self.documents.items() if m["session"] == session}
            focused = list(mine)[-1] if mine else None
            return httpx.Response(200, json={
                "session_id": session,
                "focused_document_id": focused,
                "documents": [
                    {"document_id": did, "durable_document_id": f"dur_{did}",
                     "title": meta["title"], "chunks_count": 12,
                     "focused": did == focused,
                     "html": meta.get("html") if include_html else None}
                    for did, meta in mine.items()
                ],
            })
        if path.startswith("/v1/documents/") and request.method == "GET":
            doc_id = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "structure": {
                        "headings": [{"level": 1, "text": self.documents.get(doc_id, {}).get("title", "Doc")}],
                        "section_count": 6,
                        "block_count": 40,
                        "media": {"images": 0, "diagrams": 1},
                    }
                },
            )
        if path.endswith("/agents/whoami"):
            return httpx.Response(
                200,
                json={"subscription_tier": "pro", "monthly_used": 12, "monthly_limit": 10000},
            )
        return httpx.Response(200, json={})

    def _apply_approved(self, body: dict) -> None:
        """Rewrite the stored body for every change the caller approved."""
        doc_id, pairs = self.pending_apply.get(body.get("job_id"), (None, []))
        if not doc_id or doc_id not in self.documents:
            return
        approved = {
            d.get("change_id") for d in (body.get("changes") or [])
            if d.get("approved", body.get("approved"))
        }
        if body.get("change_id") and body.get("approved"):
            approved.add(body["change_id"])
        html = self.documents[doc_id].get("html", "")
        for change_id, old_html, new_html in pairs:
            if change_id in approved:
                old = old_html.removeprefix("<td>").removesuffix("</td>")
                new = new_html.removeprefix("<td>").removesuffix("</td>")
                html = html.replace(old, new)
        self.documents[doc_id]["html"] = html

    def _upload_multipart(self, request: httpx.Request) -> httpx.Response:
        """Mirrors the real multipart endpoint, verified against production.

        Three details matter, and all three were wrong in the first version of
        this fake — which is why the offline suite was green while the live
        build produced a manifest full of nulls:

        * roster entries key the id as ``document_id``, not ``id``
        * roster entries in an *upload* response carry ``title: None``; the
          title only appears when you read the roster back
        * ``open_mode=new_focused`` adds a document, anything else replaces the
          focused one
        """
        raw = request.content.decode("utf-8", errors="replace")
        fields = dict(re.findall(r'name="([^"]+)"\r\n\r\n([^\r]*)\r\n', raw))
        filename = "unknown.html"
        m = re.search(r'filename="([^"]+)"', raw)
        if m:
            filename = m.group(1)
        session = fields.get("session_id", "unknown")
        open_mode = fields.get("open_mode", "replace")

        in_session = [d for d, meta in self.documents.items() if meta["session"] == session]
        if open_mode in ("new_focused", "new_tab", "background") or not in_session:
            doc_id = f"doc_{len(self.documents) + 1:02d}"
        else:
            doc_id = in_session[-1]
        # Keep the uploaded body so the roster can serve each document its own
        # HTML. A fake that returns null here cannot catch a verifier reading
        # the wrong document, which is exactly the bug that reached production.
        body = f"<!--{filename}-->" + _multipart_file_body(raw)
        self.documents[doc_id] = {
            "title": pathlib.Path(filename).stem,
            "session": session,
            "html": body,
        }

        roster = [
            {
                "document_id": did,
                "title": None,
                "focused": did == doc_id,
                "chunks_count": 12,
                "durable_document_id": f"dur_{did}",
            }
            for did, meta in self.documents.items()
            if meta["session"] == session
        ]
        return httpx.Response(
            200,
            json={
                "session_id": session,
                "document_id": doc_id,
                "filename": filename,
                "chunks_count": 12,
                "version_id": "ver_stub",
                "documents": roster,
                "html": None,
                "persisted": True,
            },
        )

    _REPLACE = re.compile(r'says "([^"]+)".{0,80}?replace it with "([^"]+)"', re.S)
    _SETVALUE = re.compile(r'set the value to "([^"]+)"\. Its current\s+value is "([^"]+)"', re.S)

    def _edits_in(self, instruction: str) -> list[tuple[str, str]]:
        """The (old, new) pairs an instruction asks for, in both phrasings."""
        pairs = [(a, b) for a, b in self._REPLACE.findall(instruction)]
        pairs += [(b, a) for a, b in self._SETVALUE.findall(instruction)]
        return pairs

    def _chat_async(self, body: dict) -> httpx.Response:
        self._job_seq += 1
        job_id = f"job_{self._job_seq}"

        # Apply the requested substitutions to the stored body, so "did the
        # change land" is a real question with a real answer. A fake that
        # accepts an edit and changes nothing makes every verification test
        # meaningless — and makes the repair pass look like it fires always.
        doc_id = body.get("document_id") or (list(self.documents)[-1] if self.documents else None)
        pending = []
        for i, (old, new) in enumerate(self._edits_in(body.get("message", "")), start=1):
            if new in self.drop_values:
                continue  # simulate a field the model quietly skipped
            pending.append({
                "change_id": f"{job_id}_ch{i}",
                "operation": "edit",
                "chunk_id": f"chunk-{i}",
                "old_html": f"<td>{old}</td>",
                "new_html": f"<td>{new}</td>",
                "ai_explanation": f"Replaced {old} with {new} as instructed.",
            })
        self.pending_apply[job_id] = (doc_id, [(p["change_id"], p["old_html"], p["new_html"])
                                               for p in pending])
        if not pending:
            pending = [{
                "change_id": f"{job_id}_ch1",
                "operation": "edit",
                "chunk_id": "chunk-1",
                "old_html": "<td>nothing matched</td>",
                "new_html": "<td>nothing matched</td>",
                "ai_explanation": "No instructed value was found in this document.",
            }]
        metadata = {"awaiting_kind": "approval"}
        # The real service sends this JSON-encoded on the SSE path. Both shapes
        # are exercised so the double-parse cannot regress.
        metadata["pending_changes"] = (
            json.dumps(pending) if self.encode_pending_as_string else pending
        )
        self.jobs[job_id] = {"status": "awaiting_approval", "metadata": metadata}
        return httpx.Response(200, json={"job_id": job_id})


@pytest.fixture
def fake() -> FakeSuperDocs:
    return FakeSuperDocs()


@pytest.fixture
def client(fake: FakeSuperDocs) -> SuperDocs:
    transport = httpx.MockTransport(fake.handler)
    # Mirrors the production client: no client-level Content-Type, so a
    # multipart upload can set its own boundary. Pinning it here is what made
    # the fixture accept a request shape the real client cannot send.
    http = httpx.Client(
        transport=transport,
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer sk_test"},
    )
    return SuperDocs("sk_test_key", ledger=Ledger(limit=100), client=http)
