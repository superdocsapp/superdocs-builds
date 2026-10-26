"""Client for the real SuperDocs API (https://api.superdocs.app).

Endpoint contract verified against the live OpenAPI spec (Universal
Document AI API 2.0.0) and live calls:

  POST /v1/documents/upload-base64   -> {html, session_id, filename,
                                         chunks_count, version_id, ...}
  GET  /v1/sessions/{sid}/documents  -> durable document ids for a session
  POST /v1/chat/async                -> {job_id, session_id, status}
  GET  /v1/jobs/{job_id}             -> status + metadata.pending_changes
  POST /v1/chat/{sid}/approve        -> approve/deny a proposed change
  POST /v1/downloads                 -> {download_url, expires_at, ...}
  GET  /v1/documents/{document_id}   -> saved document detail/outline

Per the build spec: uploads and exports are free; searches cost operations.
"""

import base64
import copy
import hashlib
import re
from html.parser import HTMLParser
from typing import Any, Optional
from uuid import uuid4

import httpx

from core.config import (
    SUPERDOCS_API_BASE,
    SUPERDOCS_API_KEY,
    SUPERDOCS_MODEL_TIER,
    SUPERDOCS_SESSION_ID,
)
from core.models import ParsedDocument


class _ChunkSplitter(HTMLParser):
    """Split SuperDocs' chunked HTML into one record per `data-chunk-id`.

    SuperDocs returns structured HTML where every block-level element
    (heading, paragraph, table, row, cell) carries a stable
    `data-chunk-id`. Those ids are the addressing scheme for edits, so we
    store each element's full outer HTML keyed by its id. Nested elements
    that also carry an id are captured too, but only the outermost element
    is emitted as a top-level chunk to avoid double-counting content.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.chunks: list[dict] = []
        self._depth = 0
        self._buf: list[str] = []
        self._chunk_id: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        raw = self.get_starttag_text() or f"<{tag}>"
        if self._chunk_id is None:
            if "data-chunk-id" in attr_map:
                self._chunk_id = attr_map["data-chunk-id"]
                self._buf = [raw]
                self._depth = 1
            return
        self._buf.append(raw)
        self._depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if self._chunk_id is not None:
            self._buf.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if self._chunk_id is None:
            return
        self._buf.append(f"</{tag}>")
        self._depth -= 1
        if self._depth <= 0:
            self.chunks.append({"chunk_id": self._chunk_id, "html": "".join(self._buf)})
            self._chunk_id = None
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._chunk_id is not None:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._chunk_id is not None:
            self._buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._chunk_id is not None:
            self._buf.append(f"&#{name};")


def split_chunked_html(html: str) -> list[dict]:
    """Parse chunked HTML into [{chunk_id, html, content_hash}, ...]."""
    parser = _ChunkSplitter()
    parser.feed(html or "")
    parser.close()
    chunks = parser.chunks

    if not chunks and (html or "").strip():
        # No data-chunk-id attributes at all: keep the document addressable
        # rather than silently dropping its content.
        chunks = [{"chunk_id": "chunk-000", "html": html}]

    for c in chunks:
        c["content_hash"] = hashlib.sha256(c["html"].encode()).hexdigest()
    return chunks


class SuperDocsError(RuntimeError):
    pass


class SuperDocsClient:
    def __init__(
        self,
        session_id: str = SUPERDOCS_SESSION_ID,
        api_key: str = SUPERDOCS_API_KEY,
        base_url: str = SUPERDOCS_API_BASE,
        timeout: float = 180.0,
    ):
        self.session_id = session_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def _headers(self) -> dict:
        if not self.api_key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is not set. Add it to backend/.env "
                "(see backend/config/.env.template)."
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise SuperDocsError(
                f"SuperDocs {method} {path} failed [{resp.status_code}]: {resp.text[:500]}"
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    # ---------------- Ingest ----------------

    def for_session(self, session_id: Optional[str]) -> "SuperDocsClient":
        """A client bound to another session, sharing these credentials.

        Documents live in their own sessions, so editing one means talking to
        *its* session — open, focus, chat and approve are all session-scoped
        paths. Returns self when the session already matches, so callers need
        no special case.
        """
        if not session_id or session_id == self.session_id:
            return self
        clone = copy.copy(self)
        clone.session_id = session_id
        return clone

    def session_for_document(self, key: str) -> str:
        """A dedicated session id for one document.

        A SuperDocs session holds a single active document. Uploading into a
        session that already has one REPLACES it — verified against the live
        API: uploading a new file into an existing session created no new
        document and instead bumped `updated_at` on the session's existing
        durable document, overwriting its content.

        So a shared session cannot hold a corpus. Every document gets its own
        session, which is also what makes its durable id unambiguous: that
        session's roster has exactly one entry, so no title matching is needed.
        """
        return f"{self.session_id}-doc-{key}"

    async def upload_document(
        self, file_path: str, session_id: Optional[str] = None
    ) -> ParsedDocument:
        """Upload a file and return its chunked HTML split into chunks.

        `return_html=True` is required: without it the API returns compact
        metadata only, and we need the chunk-addressed HTML to reason over
        and to target edits.

        `session_id` must be unique per document. Omitting it entirely is not
        an option: without a session the API answers `persisted: false` and
        the upload is a throwaway conversion that never becomes a document.
        """
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        filename = file_path.replace("\\", "/").split("/")[-1]
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Default to a session derived from the content hash: re-uploading the
        # same bytes lands on the same session rather than spawning a new
        # document for every retry.
        doc_session = session_id or self.session_for_document(file_hash[:16])

        data = await self._request(
            "POST",
            "/v1/documents/upload-base64",
            json={
                "filename": filename,
                "file_base64": base64.b64encode(file_bytes).decode(),
                "session_id": doc_session,
                "return_html": True,
            },
        )

        if data.get("persisted") is False:
            raise SuperDocsError(
                f"SuperDocs did not persist {filename}: "
                f"{data.get('how_to_persist') or 'no session_id was accepted'}. "
                f"A non-persisted upload has no document id and can never be edited."
            )

        html = data.get("html") or ""
        chunks = split_chunked_html(html)
        superdocs_doc_id = await self._resolve_document_id(doc_session)

        return ParsedDocument(
            document_id=uuid4(),  # our own id; caller overwrites after insert
            session_id=data.get("session_id") or doc_session,
            # Deliberately NOT falling back to version_id: a version id is not
            # a document id, and storing one only defers the failure to a 404
            # at apply time. An empty value fails loudly and locally instead.
            superdocs_doc_id=superdocs_doc_id or "",
            filename=filename,
            file_hash=file_hash,
            chunks=chunks,
            html=html,
        )

    async def _resolve_document_id(self, session_id: str) -> Optional[str]:
        """Read the DURABLE document id out of a single-document session.

        Shape notes that matter here:
        * A session roster entry's `document_id` is a session-scoped alias —
          always "doc_primary" — while the persistent id is
          `durable_document_id`. Storing the alias, or worse the upload's
          `version_id`, produces a 404 from GET /v1/documents/{id} later,
          which is exactly how apply broke.
        * This used to match on document *title* against the filename. That
          cannot work: the title is the stem without extension, several
          documents legitimately share one, and after an overwrite the durable
          document keeps its original title while holding different content.
          Reading the roster of a session known to contain exactly this
          document removes the guesswork entirely.
        """
        try:
            data = await self._request("GET", f"/v1/sessions/{session_id}/documents")
        except SuperDocsError:
            return None

        docs = data.get("documents") if isinstance(data, dict) else data
        if not isinstance(docs, list):
            return None

        for d in docs:
            if not isinstance(d, dict):
                continue
            durable = d.get("durable_document_id")
            if durable and durable != "doc_primary":
                return durable
        return None

    async def document_exists(self, doc_id: str) -> bool:
        """Whether a durable document is still retrievable.

        Used to tell "this fix cannot be applied because the document is gone"
        apart from a transient API failure, so the UI can say which.
        """
        if not doc_id:
            return False
        try:
            await self.get_document_detail(doc_id)
            return True
        except SuperDocsError:
            return False

    async def open_documents(self, document_ids: list[str]) -> dict:
        """Open durable documents into the chat session (shared, not copied).

        An edit targets a document that is open in the session, so a document
        uploaded in an earlier session must be re-opened before it can be
        edited.
        """
        return await self._request(
            "POST",
            f"/v1/sessions/{self.session_id}/documents/open",
            json={"document_ids": document_ids},
        )

    async def focus_document(self, document_id: str) -> dict:
        """Make one document the focused target in a multi-document session."""
        return await self._request(
            "POST",
            f"/v1/sessions/{self.session_id}/documents/{document_id}/focus",
            json={},
        )

    async def get_document_detail(self, doc_id: str, include_html: bool = False) -> dict:
        return await self._request(
            "GET",
            f"/v1/documents/{doc_id}",
            params={"include_html": str(include_html).lower()},
        )

    async def get_document_chunks(self, doc_id: str) -> list[dict]:
        """Current chunk state straight from SuperDocs.

        The byte-identity proof must compare against the document as it
        actually is after an edit, not against our own stored copy — reading
        our copy back would only prove we didn't modify our copy.
        """
        detail = await self.get_document_detail(doc_id, include_html=True)
        html = detail.get("html") or ""
        return split_chunked_html(html)

    async def list_session_documents(self) -> dict:
        return await self._request("GET", f"/v1/sessions/{self.session_id}/documents")

    # ---------------- Edit ----------------

    async def chat_async(
        self,
        message: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = SUPERDOCS_MODEL_TIER,
        document_id: Optional[str] = None,
    ) -> str:
        body: dict = {
            "message": message,
            "session_id": self.session_id,
            "async_mode": True,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
        }
        if document_id:
            body["document_id"] = document_id
        data = await self._request("POST", "/v1/chat/async", json=body)
        job_id = data.get("job_id")
        if not job_id:
            raise SuperDocsError(f"chat_async returned no job_id: {data}")
        return job_id

    async def get_job(self, job_id: str) -> dict:
        """Fetch job status. `metadata.pending_changes` is an object here
        (the SSE path returns it as a JSON string instead)."""
        return await self._request("GET", f"/v1/jobs/{job_id}")

    async def approve_change(
        self,
        job_id: str,
        change_id: Optional[str],
        approved: bool = True,
        feedback: Optional[str] = None,
    ) -> dict:
        # Top-level `approved` is required on every approve call.
        body: dict = {"job_id": job_id, "approved": approved}
        if change_id:
            body["change_id"] = change_id
        if feedback:
            body["feedback"] = feedback
        return await self._request(
            "POST", f"/v1/chat/{self.session_id}/approve", json=body
        )

    async def continue_job(self, job_id: str, message: str = "") -> dict:
        """Used when metadata.awaiting_kind == 'continue_prompt'."""
        return await self._request(
            "POST",
            f"/v1/chat/{self.session_id}/continue",
            json={"job_id": job_id, "message": message},
        )

    # ---------------- Export ----------------

    async def request_download_url(self, format: str = "docx") -> str:
        data = await self._request(
            "POST",
            "/v1/downloads",
            json={"session_id": self.session_id, "format": format},
        )
        url = data.get("download_url")
        if not url:
            raise SuperDocsError(f"downloads returned no download_url: {data}")
        return url


class MockSuperDocsClient(SuperDocsClient):
    """Offline stand-in used by the test suite (no network, no API key).

    Produces the same chunk-addressed shape the real API returns so tests
    exercise real parsing logic rather than a different code path.
    """

    def __init__(self, session_id: str = "test-session", **kwargs):
        super().__init__(session_id=session_id, api_key="mock-key", **kwargs)

    async def upload_document(
        self, file_path: str, session_id: Optional[str] = None
    ) -> ParsedDocument:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        filename = file_path.replace("\\", "/").split("/")[-1]
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        raw = file_bytes.decode("utf-8", errors="replace")

        html_parts = []
        for i, block in enumerate(b for b in re.split(r"\n\s*\n", raw) if b.strip()):
            cid = f"chunk-{i:03d}"
            text = " ".join(line.strip() for line in block.strip().splitlines())
            heading = re.match(r"^(#{1,6})\s+(.*)$", text)
            if heading:
                lvl = len(heading.group(1))
                html_parts.append(
                    f'<h{lvl} data-chunk-id="{cid}">{heading.group(2)}</h{lvl}>'
                )
            else:
                html_parts.append(f'<p data-chunk-id="{cid}">{text}</p>')
        html = "\n".join(html_parts)

        return ParsedDocument(
            document_id=uuid4(),
            session_id=session_id or self.session_for_document(file_hash[:16]),
            superdocs_doc_id=f"sd-{file_hash[:12]}",
            filename=filename,
            file_hash=file_hash,
            chunks=split_chunked_html(html),
            html=html,
        )

    async def _resolve_document_id(self, session_id: str) -> Optional[str]:
        return None

    async def document_exists(self, doc_id: str) -> bool:
        return bool(doc_id)

    async def open_documents(self, document_ids: list[str]) -> dict:
        return {"opened": document_ids}

    async def focus_document(self, document_id: str) -> dict:
        return {"focused": document_id}

    async def chat_async(self, message: str, approval_mode: str = "ask_every_time",
                         model_tier: str = "max", document_id: Optional[str] = None) -> str:
        return f"job-mock-{uuid4().hex[:8]}"

    async def get_job(self, job_id: str) -> dict:
        return {
            "job_id": job_id,
            "status": "awaiting_approval",
            "metadata": {
                "awaiting_kind": "change",
                "pending_changes": [
                    {
                        "change_id": f"change-{uuid4().hex[:8]}",
                        "chunk_id": "chunk-000",
                        "html_diff": "<div>diff</div>",
                    }
                ],
            },
        }

    async def approve_change(self, job_id: str, change_id: Optional[str],
                             approved: bool = True, feedback: Optional[str] = None) -> dict:
        return {"status": "approved", "job_id": job_id, "change_id": change_id}

    async def request_download_url(self, format: str = "docx") -> str:
        return f"https://download.mock.superdocs.app/{uuid4().hex}.{format}"

    async def get_document_detail(self, doc_id: str, include_html: bool = False) -> dict:
        return {
            "document_id": doc_id,
            "section_count": 3,
            "block_count": 5,
            "headings": [{"level": 1, "text": "Mock Doc", "position": 1}],
        }
