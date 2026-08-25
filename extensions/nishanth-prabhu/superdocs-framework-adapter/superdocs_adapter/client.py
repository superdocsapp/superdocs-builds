from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Any

from .core import SuperDocsAdapter
from .models import ToolName, ToolResult


class SuperDocsClient(SuperDocsAdapter):
    """
    Framework-neutral client for the SuperDocs API.

    The SuperDocs API is stateless: document content is supplied with each
    chat request. This client therefore maintains a local session-to-content
    mapping and keeps all HTTP details isolated from framework integrations.
    """

    def __init__(
        self,
        base_url: str = "https://api.superdocs.app/v1",
        api_key: str | None = None,
        timeout: int = 90,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._documents: dict[str, str] = {}

    def upload(
        self,
        title: str,
        content: str,
    ) -> str:
        """
        Register document content locally and return a document/session ID.

        SuperDocs receives the actual document content during the chat request.
        """
        del title

        document_id = f"superdocs-{uuid.uuid4().hex[:12]}"
        self._documents[document_id] = content
        return document_id

    def edit_document(
        self,
        document_id: str,
        instruction: str,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Ask SuperDocs to identify/apply an instruction-driven document edit.

        The API returns structured document changes when available.
        """

        content = self._documents.get(document_id)

        if content is None:
            return ToolResult.failure(
                ToolName.EDIT_DOCUMENT,
                f"Unknown document_id: {document_id}",
            )

        prompt = instruction.strip()

        if not prompt:
            return ToolResult.failure(
                ToolName.EDIT_DOCUMENT,
                "Instruction cannot be empty.",
            )

        payload = {
            "session_id": document_id,
            "message": (
                f"{prompt}\n\n"
                "Identify the relevant document changes. "
                "Return proposed changes with fields: "
                "change_id, target_section, old_snippet, new_snippet, "
                "explanation. "
                "Respond ONLY with the JSON array inside a ```json code block."
            ),
            "document_html": self._markdown_to_simple_html(content),
        }

        try:
            response = self._request(
                endpoint="/chat",
                method="POST",
                data=payload,
            )

            changes = self._extract_changes(response)

            return ToolResult.ok(
                ToolName.EDIT_DOCUMENT,
                {
                    "document_id": document_id,
                    "changes": changes,
                    "raw_response": response,
                },
            )

        except Exception as exc:
            return ToolResult.failure(
                ToolName.EDIT_DOCUMENT,
                str(exc),
            )

    def search_document(
        self,
        document_id: str,
        query: str,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Search the locally registered document.

        SuperDocs currently exposes document interaction through /chat rather
        than a dedicated search endpoint, so this operation performs a
        deterministic local text search.
        """

        content = self._documents.get(document_id)

        if content is None:
            return ToolResult.failure(
                ToolName.SEARCH_DOCUMENT,
                f"Unknown document_id: {document_id}",
            )

        query = query.strip()

        if not query:
            return ToolResult.failure(
                ToolName.SEARCH_DOCUMENT,
                "Query cannot be empty.",
            )

        query_lower = query.lower()
        matches = [
            line
            for line in content.splitlines()
            if query_lower in line.lower()
        ]

        return ToolResult.ok(
            ToolName.SEARCH_DOCUMENT,
            {
                "document_id": document_id,
                "query": query,
                "matches": matches,
                "count": len(matches),
            },
        )

    def export_document(
        self,
        document_id: str,
        format: str = "docx",
        **kwargs: Any,
    ) -> ToolResult:
        """
        Return the locally maintained document representation.

        Actual binary document export is intentionally left outside the core
        adapter until SuperDocs exposes a dedicated export operation.
        """

        content = self._documents.get(document_id)

        if content is None:
            return ToolResult.failure(
                ToolName.EXPORT_DOCUMENT,
                f"Unknown document_id: {document_id}",
            )

        supported_formats = {"markdown", "md", "txt"}

        if format.lower() not in supported_formats:
            return ToolResult.failure(
                ToolName.EXPORT_DOCUMENT,
                (
                    f"Unsupported export format '{format}'. "
                    f"Supported formats: {sorted(supported_formats)}"
                ),
            )

        return ToolResult.ok(
            ToolName.EXPORT_DOCUMENT,
            {
                "document_id": document_id,
                "format": format.lower(),
                "content": content,
            },
        )

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import ssl

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "superdocs-framework-adapter/0.1.0",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = (
            json.dumps(data).encode("utf-8")
            if data is not None
            else None
        )

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )

        # Use a permissive SSL context so macOS Python installations that lack
        # the system CA bundle (common with python.org builds) don't fail for
        # well-known hosts.  For production use, swap for ssl.create_default_context()
        # with an explicit cafile.
        ssl_ctx = ssl.create_default_context()
        try:
            ssl_ctx.load_default_certs()
        except Exception:
            pass
        try:
            import certifi  # type: ignore[import]
            ssl_ctx.load_verify_locations(certifi.where())
        except ImportError:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=ssl_ctx,
            ) as response:
                response_body = response.read().decode("utf-8")

            if not response_body:
                return {}

            parsed = json.loads(response_body)

            if not isinstance(parsed, dict):
                raise ValueError("SuperDocs returned a non-object JSON response.")

            return parsed

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"SuperDocs HTTP error {exc.code}: {body}"
            ) from exc

        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"SuperDocs connection error: {exc.reason}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON response from SuperDocs: {exc}"
            ) from exc

    def _markdown_to_simple_html(self, markdown: str) -> str:
        parts: list[str] = []

        for line in markdown.splitlines():
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)

            if heading:
                level = len(heading.group(1))
                text = heading.group(2).strip()
                parts.append(f"<h{level}>{text}</h{level}>")
            elif line.strip():
                parts.append(f"<p>{line.strip()}</p>")

        return "\n".join(parts)

    def _extract_changes(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        document_changes = response.get("document_changes") or {}
        changes = document_changes.get("changes") or []

        if changes:
            return [
                {
                    "change_id": change.get(
                        "change_id",
                        f"change_{index + 1}",
                    ),
                    "old_snippet": self._strip_html(
                        change.get("old_html", "")
                    ),
                    "new_snippet": self._strip_html(
                        change.get("new_html", "")
                    ),
                    "explanation": self._strip_html(
                        change.get("ai_explanation", "")
                    ),
                    "chunk_id": change.get("chunk_id"),
                }
                for index, change in enumerate(changes)
            ]

        response_text = response.get("response", "")

        match = re.search(
            r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```",
            response_text,
            re.DOTALL,
        )

        if not match:
            return []

        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, dict):
            parsed = parsed.get("proposed_changes", parsed.get("changes", []))

        if not isinstance(parsed, list):
            return []

        return [
            item
            for item in parsed
            if isinstance(item, dict)
        ]

    @staticmethod
    def _strip_html(value: str) -> str:
        return re.sub(r"<[^>]+>", "", value).strip()
