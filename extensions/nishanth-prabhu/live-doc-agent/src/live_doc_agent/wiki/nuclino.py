"""Nuclino Wiki Adapter with optimistic concurrency control."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional
from live_doc_agent.models import (
    ConflictError,
    Patch,
    SectionNotFoundError,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.wiki.base import WikiAdapter


class NuclinoWikiAdapter(WikiAdapter):
    """Adapter for Nuclino's REST API (GET /v0/items/:id, PATCH /v0/items/:id/content)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.nuclino.com/v0",
        mock_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        self.api_key = api_key or "mock-nuclino-key"
        self.base_url = base_url.rstrip("/")
        self._mock_handler = mock_handler

    def _http_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform HTTP request against Nuclino API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "live-doc-agent/0.1.0",
        }
        body_bytes = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_body = response.read().decode("utf-8")
                return json.loads(res_body) if res_body else {}
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            if err.code == 409:
                raise ConflictError(
                    f"Nuclino 409 Conflict: Document was modified concurrently on server. Details: {err_body}"
                ) from err
            if err.code == 404:
                raise SectionNotFoundError(f"Nuclino item not found: {err_body}") from err
            raise RuntimeError(f"Nuclino API HTTP error {err.code}: {err_body}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"Nuclino connection error: {err.reason}") from err

    def fetch_page(self, doc_id: str) -> WikiDocument:
        """Fetch item content and contentVersion from Nuclino."""
        if self._mock_handler:
            data = self._mock_handler("fetch", {"item_id": doc_id})
        else:
            data = self._http_request(f"/items/{doc_id}", method="GET")

        # Nuclino response format: {"status": "success", "data": {"id": ..., "title": ..., "content": ..., "contentVersion": ...}}
        item_data = data.get("data", data)
        title = item_data.get("title", "Untitled")
        content = item_data.get("content", "")
        version = str(item_data.get("contentVersion", "1"))

        sections = DocumentPatcher.parse_sections(content)
        return WikiDocument(
            doc_id=doc_id,
            title=title,
            content=content,
            content_version=version,
            sections=sections,
            metadata={"raw_nuclino": item_data},
        )

    def apply_patch(self, doc_id: str, patch: Patch) -> WikiDocument:
        """Surgically calculate new markdown and patch Nuclino with contentVersion."""
        # 1. Fetch current document to ensure latest state
        current = self.fetch_page(doc_id)

        # 2. Local version check
        if str(current.content_version) != str(patch.expected_version):
            raise ConflictError(
                f"Local version mismatch on doc '{doc_id}': expected {patch.expected_version}, "
                f"current server version is {current.content_version}."
            )

        # 3. Calculate surgical replacement
        updated_content = DocumentPatcher.apply_patch_to_content(current.content, patch)

        # 4. PATCH Nuclino item content
        payload = {
            "content": updated_content,
            "contentVersion": int(patch.expected_version) if patch.expected_version.isdigit() else patch.expected_version,
        }

        if self._mock_handler:
            data = self._mock_handler("patch", {"item_id": doc_id, "payload": payload})
        else:
            data = self._http_request(f"/items/{doc_id}/content", method="PATCH", data=payload)

        item_data = data.get("data", data)
        new_version = str(item_data.get("contentVersion", str(int(patch.expected_version) + 1 if patch.expected_version.isdigit() else f"{patch.expected_version}_v2")))

        updated_sections = DocumentPatcher.parse_sections(updated_content)
        return WikiDocument(
            doc_id=doc_id,
            title=current.title,
            content=updated_content,
            content_version=new_version,
            sections=updated_sections,
            metadata={"raw_nuclino": item_data},
        )

    def get_version(self, doc_id: str) -> str:
        """Fetch current version token."""
        doc = self.fetch_page(doc_id)
        return doc.content_version
