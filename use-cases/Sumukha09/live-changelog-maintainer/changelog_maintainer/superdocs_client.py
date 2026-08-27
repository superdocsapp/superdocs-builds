

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SuperDocsError(RuntimeError):
    """Raised for any SuperDocs API failure."""


class AuthError(SuperDocsError):
    """Raised when the bearer token is missing or rejected."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.superdocs.app"
DEFAULT_TIMEOUT_S = 180.0


def _load_dotenv() -> None:
    """Lightweight pure-Python .env file loader."""
    for candidate in (
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ):
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


@dataclass(frozen=True)
class SuperDocsConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: Optional[str] = None
    timeout_s: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, api_key: Optional[str] = None) -> "SuperDocsConfig":
        _load_dotenv()
        return cls(
            base_url=os.environ.get("SUPERDOCS_BASE_URL", DEFAULT_BASE_URL),
            api_key=api_key or os.environ.get("SUPERDOCS_API_KEY"),
            timeout_s=float(os.environ.get("SUPERDOCS_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class SurgicalInsertResult:
    """The outcome of a single targeted edit."""

    document_id: str
    inserted_chunk_ids: tuple[str, ...]
    html: Optional[str] = None  # when include_html=True


class SuperDocsClient:
    """High-level SuperDocs client tailored for the changelog workflow."""

    def __init__(
        self,
        config: SuperDocsConfig | None = None,
        mode: Literal["http", "passthrough"] = "http",
    ) -> None:
        self.config = config or SuperDocsConfig.from_env()
        self.mode = mode
        if mode == "http" and not self.config.api_key:
            raise AuthError(
                "SuperDocs API key missing. Set SUPERDOCS_API_KEY or pass --api-key."
            )

    # ------------------------------------------------------------------
    # Mode-specific implementations
    # ------------------------------------------------------------------

    def create_document(self, title: str, markdown: str) -> str:
        """Create a new SuperDocs document from Markdown. Returns document id."""
        if self.mode == "http":
            return self._create_document_http(title, markdown)
        raise SuperDocsError(
            "passthrough mode requires manual MCP call; use create_document_via_mcp()"
        )

    def create_document_via_mcp(self, title: str, markdown: str) -> str:
        """Helper called by an MCP-enabled host to record a freshly created
        document id. We DO NOT call MCP tools here — we only persist the id
        that the host reports."""
        raise NotImplementedError(
            "This method exists for API symmetry only. In passthrough mode the "
            "host invokes the MCP tools directly and the result is passed back "
            "to ChangelogMaintainer via apply_mcp_result()."
        )

    def surgical_insert(
        self,
        document_id: str,
        anchor_text: str,
        new_markdown: str,
    ) -> SurgicalInsertResult:
        """Insert ``new_markdown`` immediately after the first heading whose
        text contains ``anchor_text``. Returns chunk ids of newly inserted
        content. Other content is preserved byte-identically by the server."""
        if self.mode == "http":
            return self._surgical_insert_http(document_id, anchor_text, new_markdown)
        raise SuperDocsError(
            "passthrough mode requires manual MCP call; use surgical_insert_via_mcp()"
        )

    def export_document(
        self,
        document_id: str,
        fmt: Literal["md", "docx", "pdf", "html", "txt"],
    ) -> bytes:
        if self.mode == "http":
            return self._export_http(document_id, fmt)
        raise SuperDocsError(
            "passthrough mode requires manual MCP call; use export_via_mcp()"
        )

    def get_document_html(self, document_id: str) -> str:
        if self.mode == "http":
            return self._get_document_html_http(document_id)
        raise SuperDocsError(
            "passthrough mode requires manual MCP call; use get_html_via_mcp()"
        )

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any] | bytes:
        url = self.config.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data: Optional[bytes] = None
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "live-changelog-maintainer/1.0",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if ctype.startswith("application/json"):
                    return json.loads(raw.decode("utf-8"))
                return raw
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (401, 403):
                raise AuthError(
                    f"SuperDocs auth failed ({exc.code}): {detail}"
                ) from exc
            raise SuperDocsError(
                f"SuperDocs HTTP {exc.code} on {method} {path}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SuperDocsError(
                f"SuperDocs unreachable: {exc}"
            ) from exc

    # ----- create_document -------------------------------------------------------

    def _create_document_http(self, title: str, markdown: str) -> str:
        session_id = f"clm-{uuid.uuid4().hex[:12]}"
        resp = self._request(
            "POST",
            "/v1/chat",
            body={
                "session_id": session_id,
                "message": f"Initialize the {title} changelog.",
                "document_html": _md_to_html(title, markdown),
            },
        )
        return session_id

    # ----- surgical_insert -------------------------------------------------------

    def _surgical_insert_http(
        self,
        document_id: str,
        anchor_text: str,
        new_markdown: str,
    ) -> SurgicalInsertResult:
        # Step 1: get original HTML for diffing
        try:
            original_html = self._get_document_html_http(document_id)
        except Exception:
            original_html = None

        # Step 2: ask chat for a SURGICAL insert.
        instruction = (
            "Surgical edit required. Insert the Markdown block below "
            f"immediately AFTER the first heading whose visible text contains "
            f"the exact substring {anchor_text!r}. "
            "Do not modify, reformat, reorder, or rephrase ANY other content. "
            "Do not touch paragraphs, tables, lists, links, or headings "
            "outside the insertion point. The block to insert is exactly:\n\n"
            f"<<<BEGIN BLOCK>>>\n{new_markdown.rstrip()}\n<<<END BLOCK>>>\n\n"
            "If the anchor is not found, REFUSE the edit and respond with "
            "'ANCHOR NOT FOUND' — do not invent a position."
        )
        chat_resp = self._request(
            "POST",
            "/v1/chat",
            body={
                "session_id": document_id,
                "message": instruction,
                "response_mode": "compact",
                "approval_mode": "approve_all",
                "thinking_depth": "fast",
            },
        )
        doc_changes = chat_resp.get("document_changes") if isinstance(chat_resp, dict) else {}
        chunk_diffs = (doc_changes.get("chunk_diffs") if isinstance(doc_changes, dict) else None) or (chat_resp.get("chunk_diffs") if isinstance(chat_resp, dict) else None) or []
        inserted_ids = tuple(
            d.get("chunk_id") for d in chunk_diffs if isinstance(d, dict) and d.get("chunk_id")
        )
        return SurgicalInsertResult(
            document_id=document_id,
            inserted_chunk_ids=inserted_ids,
            html=original_html,
        )

    # ----- export ----------------------------------------------------------------

    def _export_http(
        self,
        document_id: str,
        fmt: Literal["md", "docx", "pdf", "html", "txt"],
    ) -> bytes:
        format_map = {
            "md": "markdown",
            "markdown": "markdown",
            "docx": "docx",
            "pdf": "pdf",
            "html": "html",
            "txt": "txt",
            "doc": "doc",
        }
        export_fmt = format_map.get(fmt.lower(), fmt.lower())
        resp = self._request(
            "POST",
            "/v1/documents/export",
            body={"session_id": document_id, "format": export_fmt},
        )
        if isinstance(resp, dict):
            if resp.get("download_url"):
                url = resp["download_url"]
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self.config.timeout_s) as r:
                    return r.read()
            if resp.get("content_base64"):
                import base64

                return base64.b64decode(resp["content_base64"])
            if "markdown" in resp:
                return resp["markdown"].encode("utf-8")
            if "html" in resp:
                return resp["html"].encode("utf-8")
            raise SuperDocsError(f"Unexpected export response: {resp!r}")
        if isinstance(resp, str):
            return resp.encode("utf-8")
        return resp

    # ----- get_document_html -----------------------------------------------------

    def _get_document_html_http(self, document_id: str) -> str:
        data = self._export_http(document_id, "html")
        return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _md_to_html(title: str, markdown: str) -> str:
    """Wrap Markdown in a minimal HTML shell for verbatim load.

    We use the simplest possible conversion — the SuperDocs parser will
    re-parse the Markdown. We keep <pre> wrappers only so headings round-trip
    cleanly during the initial verbatim load.
    """
    body = _escape_html(markdown)
    return (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset='utf-8'><title>"
        f"{_escape_html(title)}"
        "</title></head><body>\n"
        f"<pre>{body}</pre>\n"
        "</body></html>\n"
    )


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _first_document_html(open_resp: dict[str, Any]) -> str:
    docs = open_resp.get("documents") or []
    if not docs:
        raise SuperDocsError("documents/open returned no documents")
    first = docs[0]
    html = first.get("html") or first.get("html_content")
    if not html:
        raise SuperDocsError("documents/open response missing html field")
    return html


__all__ = [
    "AuthError",
    "DEFAULT_BASE_URL",
    "SuperDocsClient",
    "SuperDocsConfig",
    "SuperDocsError",
    "SurgicalInsertResult",
]
