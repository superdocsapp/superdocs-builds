"""A small SuperDocs client — the four calls this build needs.

Deliberately self-contained so this extension can be lifted out of the repository on its
own. Errors name their cause and their fix, because the most common failure here is a
key problem and a bare 401 tells nobody anything.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.superdocs.app"
SETTLED = frozenset({"completed", "failed", "cancelled"})


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, fix: str = "") -> None:
        super().__init__(message if not fix else f"{message}\n  fix: {fix}")
        self.status = status


@dataclass
class Call:
    method: str
    path: str
    status: int | None
    ms: int
    note: str = ""
    billable: bool = False


@dataclass
class Client:
    """Four calls: chat, poll, export, and a free key check."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 300.0
    calls: list[Call] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise SuperDocsError(
                "no API key",
                fix="set SUPERDOCS_API_KEY in your environment or .env file; "
                    "get one from use.superdocs.app -> Settings -> API Keys",
            )
        self._http = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- plumbing ---------------------------------------------------------

    def _request(
        self, method: str, path: str, *, note: str = "", billable: bool = False, **kw: Any
    ) -> httpx.Response:
        started = time.monotonic()
        try:
            r = self._http.request(method, path, **kw)
        except httpx.TransportError as exc:
            self.calls.append(Call(method, path, None, int((time.monotonic() - started) * 1000),
                                   note=f"transport error: {exc}"))
            raise SuperDocsError(
                f"could not reach {self.base_url}: {exc}",
                fix="check SUPERDOCS_BASE_URL and your network",
            ) from exc
        self.calls.append(Call(method, path, r.status_code,
                               int((time.monotonic() - started) * 1000),
                               note=note, billable=billable))
        if r.status_code >= 400:
            raise self._error(r)
        return r

    def _error(self, r: httpx.Response) -> SuperDocsError:
        try:
            body = r.json()
            detail = body.get("detail") or body.get("error") or body
            if isinstance(detail, dict):
                detail = " | ".join(str(v) for v in detail.values() if v)
        except (json.JSONDecodeError, ValueError):
            detail = r.text[:300]
        if r.status_code == 401:
            return SuperDocsError(
                f"401 unauthorized: {detail}", status=401,
                fix="the value is just sk_... with no 'Bearer ' inside it, and "
                    "/v1/users/* endpoints reject API keys by design",
            )
        if r.status_code == 429:
            return SuperDocsError(
                f"429 rate limited: {detail}", status=429,
                fix=f"wait {r.headers.get('Retry-After', '60')}s; you may be out of "
                    "monthly operations",
            )
        return SuperDocsError(f"{r.status_code} from {r.request.url.path}: {detail}",
                              status=r.status_code)

    # --- the calls --------------------------------------------------------

    def ping(self) -> bool:
        """Cheapest key check there is: GET /v1/sessions costs no operations."""
        self._request("GET", "/v1/sessions", note="key check (free)")
        return True

    def chat(
        self, session_id: str, message: str, *, model_tier: str | None = None,
        note: str = "chat",
    ) -> dict[str, Any]:
        """One synchronous turn. Returns the result body.

        Synchronous rather than async because each turn here is one document's worth of
        work and there is a human waiting on it; the job-polling machinery would add
        moving parts for no gain.
        """
        payload: dict[str, Any] = {"message": message, "session_id": session_id,
                                   "approval_mode": "approve_all"}
        if model_tier:
            payload["model_tier"] = model_tier
        r = self._request("POST", "/v1/chat", json=payload, note=note, billable=True)
        return r.json()

    def export(
        self, *, session_id: str | None = None, html: str | None = None,
        fmt: str = "docx", options: dict[str, Any] | None = None,
    ) -> bytes:
        """Export a document. Exports never cost operations."""
        payload: dict[str, Any] = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html is not None:
            payload["html"] = html
        if options:
            payload["options"] = options
        return self._request("POST", "/v1/documents/export", json=payload,
                             note=f"export {fmt} (free)").content

    # --- reporting --------------------------------------------------------

    @property
    def operations_spent(self) -> int:
        return sum(1 for c in self.calls if c.billable and (c.status or 0) < 400)

    def usage_from(self, result: dict[str, Any]) -> dict[str, Any]:
        return (result or {}).get("usage") or {}


def document_html(result: dict[str, Any]) -> str:
    """The document a chat turn produced, whichever shape the response uses."""
    changes = (result or {}).get("document_changes") or {}
    return changes.get("updated_html") or (result or {}).get("document_html") or ""
