"""SuperDocs API Client implementation with defensive double-JSON parsing."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional
from live_doc_agent.models import (
    ProposedChange,
    SuperDocsAPIError,
)


class SuperDocsClient:
    """Client for interacting with the SuperDocs REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://use.superdocs.app/api",
        mock_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        self.api_key = api_key or "mock-key"
        self.base_url = base_url.rstrip("/")
        self._mock_handler = mock_handler

    def _http_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform HTTP request using standard library urllib."""
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
            raise SuperDocsAPIError(f"SuperDocs HTTP error {err.code}: {err_body}") from err
        except urllib.error.URLError as err:
            raise SuperDocsAPIError(f"SuperDocs connection error: {err.reason}") from err
        except json.JSONDecodeError as err:
            raise SuperDocsAPIError(f"Invalid JSON response from SuperDocs: {err}") from err

    def upload(self, title: str, content: str) -> str:
        """Upload a markdown document snapshot to SuperDocs.

        Returns:
            document_id string.
        """
        if self._mock_handler:
            res = self._mock_handler("upload", {"title": title, "content": content})
            return str(res.get("document_id", f"doc_{uuid.uuid4().hex[:8]}"))

        try:
            data = self._http_request("/documents", method="POST", data={"title": title, "content": content})
            return data.get("document_id") or data.get("id") or str(uuid.uuid4().hex[:8])
        except Exception as e:
            if isinstance(e, SuperDocsAPIError):
                raise
            raise SuperDocsAPIError(f"Failed to upload document to SuperDocs: {e}") from e

    def chat(
        self,
        doc_id: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ProposedChange]:
        """Send chat instructions to SuperDocs and parse proposed surgical edits.

        Defensively handles:
        - Native dictionary or list payloads
        - Double-encoded JSON string payloads (e.g. '{"changes": [...]}')
        """
        if self._mock_handler:
            raw_response = self._mock_handler(
                "chat", {"doc_id": doc_id, "prompt": prompt, "context": context}
            )
            return self._parse_proposed_changes(raw_response)

        try:
            payload = {
                "document_id": doc_id,
                "message": prompt,
                "context": context or {},
            }
            data = self._http_request("/chat", method="POST", data=payload)
            return self._parse_proposed_changes(data)
        except Exception as e:
            if isinstance(e, SuperDocsAPIError):
                raise
            raise SuperDocsAPIError(f"Failed to execute SuperDocs chat: {e}") from e

    def approve(self, doc_id: str, change_ids: List[str]) -> bool:
        """Submit approval for specific proposed changes."""
        if self._mock_handler:
            res = self._mock_handler("approve", {"doc_id": doc_id, "change_ids": change_ids})
            return bool(res.get("success", True))

        try:
            self._http_request(
                f"/documents/{doc_id}/approve",
                method="POST",
                data={"change_ids": change_ids},
            )
            return True
        except Exception as e:
            if isinstance(e, SuperDocsAPIError):
                raise
            raise SuperDocsAPIError(f"Failed to approve changes in SuperDocs: {e}") from e

    def export(self, doc_id: str) -> str:
        """Export the resulting document content from SuperDocs."""
        if self._mock_handler:
            res = self._mock_handler("export", {"doc_id": doc_id})
            return str(res.get("content", ""))

        try:
            data = self._http_request(f"/documents/{doc_id}/export", method="GET")
            return data.get("content", "")
        except Exception as e:
            if isinstance(e, SuperDocsAPIError):
                raise
            raise SuperDocsAPIError(f"Failed to export document from SuperDocs: {e}") from e

    def _parse_proposed_changes(self, raw_data: Any) -> List[ProposedChange]:
        """Normalize raw SuperDocs response into a list of ProposedChange models."""
        if not raw_data:
            return []

        # 1. If raw_data itself is a JSON string, decode it
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                raise SuperDocsAPIError(f"Malformed JSON in SuperDocs response string: {e}") from e

        # 2. Extract proposed changes container
        changes_container = raw_data
        if isinstance(raw_data, dict):
            # Check common wrapper keys
            if "proposed_changes" in raw_data:
                changes_container = raw_data["proposed_changes"]
            elif "changes" in raw_data:
                changes_container = raw_data["changes"]
            elif "data" in raw_data:
                changes_container = raw_data["data"]

        # 3. If changes_container is a double-encoded JSON string, decode it
        if isinstance(changes_container, str):
            try:
                changes_container = json.loads(changes_container)
            except json.JSONDecodeError as e:
                raise SuperDocsAPIError(
                    f"Malformed double-encoded JSON in 'proposed_changes': {e}"
                ) from e

        # 4. If container is a dict with "changes" key
        if isinstance(changes_container, dict):
            if "changes" in changes_container:
                changes_container = changes_container["changes"]
            elif "proposed_changes" in changes_container:
                changes_container = changes_container["proposed_changes"]
            else:
                # Single change represented as a dict
                changes_container = [changes_container]

        if not isinstance(changes_container, list):
            return []

        # 5. Parse each item into ProposedChange
        parsed: List[ProposedChange] = []
        for idx, item in enumerate(changes_container):
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except Exception:
                    continue

            if not isinstance(item, dict):
                continue

            change_id = item.get("change_id") or item.get("id") or f"change_{idx + 1}"
            target_section = (
                item.get("target_section")
                or item.get("section")
                or item.get("target")
                or item.get("heading")
                or "General"
            )
            old_snippet = (
                item.get("old_snippet")
                or item.get("old")
                or item.get("original")
                or item.get("target_old_text")
                or ""
            )
            new_snippet = (
                item.get("new_snippet")
                or item.get("new")
                or item.get("replacement")
                or item.get("replacement_new_text")
                or ""
            )
            explanation = item.get("explanation") or item.get("reason") or ""
            confidence = float(item.get("confidence", 1.0))

            if old_snippet and new_snippet:
                parsed.append(
                    ProposedChange(
                        change_id=str(change_id),
                        target_section=str(target_section),
                        old_snippet=str(old_snippet),
                        new_snippet=str(new_snippet),
                        explanation=str(explanation),
                        confidence=confidence,
                    )
                )

        return parsed
