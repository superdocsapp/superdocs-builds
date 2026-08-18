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
    """Client for interacting with the SuperDocs REST API.

    The real SuperDocs API is a single stateless endpoint:
        POST https://api.superdocs.app/v1/chat
        { session_id, message, document_html }

    The mock_handler interface is preserved for all tests.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.superdocs.app/v1",
        mock_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        self.api_key = api_key or "mock-key"
        self.base_url = base_url.rstrip("/")
        self._mock_handler = mock_handler
        # Kept internally for the stateless single-call API
        self._session_content: Dict[str, str] = {}  # session_id -> document markdown

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
            with urllib.request.urlopen(req, timeout=90) as response:
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
        """'Upload' a document snapshot.

        For the real SuperDocs API, the document is stateless — it is sent
        inline with each chat call as `document_html`.  We store the markdown
        locally under a session ID and return that ID so the agent can pass it
        to `chat()` later.

        The mock_handler path is preserved unchanged for all automated tests.
        """
        if self._mock_handler:
            res = self._mock_handler("upload", {"title": title, "content": content})
            return str(res.get("document_id", f"doc_{uuid.uuid4().hex[:8]}"))

        # Real API: store the content locally; send it inline with the chat call.
        session_id = f"ld-agent-{uuid.uuid4().hex[:12]}"
        self._session_content[session_id] = content
        return session_id

    def chat(
        self,
        doc_id: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[ProposedChange]:
        """Send the decision to SuperDocs and parse proposed surgical edits.

        Real API: POST /v1/chat with session_id, message, document_html.
        Parses changes from document_changes.changes (preferred) or from the
        JSON code block embedded in the response text.

        Mock path: unchanged for all automated tests.
        """
        if self._mock_handler:
            raw_response = self._mock_handler(
                "chat", {"doc_id": doc_id, "prompt": prompt, "context": context}
            )
            return self._parse_proposed_changes(raw_response)

        try:
            # Convert stored markdown to simple HTML for the real API
            markdown_content = self._session_content.get(doc_id, "")
            document_html = self._markdown_to_simple_html(markdown_content)

            payload = {
                "session_id": doc_id,
                "message": (
                    f"{prompt}\n\n"
                    "Identify stale or conflicting sections. For each stale section, "
                    "return a JSON array of proposed_changes with fields: "
                    "change_id, target_section, old_snippet, new_snippet, explanation. "
                    "Respond ONLY with the JSON array inside a ```json code block."
                ),
                "document_html": document_html,
            }
            data = self._http_request("/chat", method="POST", data=payload)
            return self._parse_real_api_response(data)
        except Exception as e:
            if isinstance(e, SuperDocsAPIError):
                raise
            raise SuperDocsAPIError(f"SuperDocs interaction failed: {e}") from e

    def approve(self, doc_id: str, change_ids: List[str]) -> bool:
        """Record approval for specific proposed changes.

        The real SuperDocs API is stateless — changes are returned in the
        chat response and applied by the local patch engine.  No separate
        approval HTTP call is needed.  This method is a no-op for live mode.
        """
        if self._mock_handler:
            res = self._mock_handler("approve", {"doc_id": doc_id, "change_ids": change_ids})
            return bool(res.get("success", True))
        # No-op for real API (stateless; approval is implicit in applying the patch locally)
        return True

    def export(self, doc_id: str) -> str:
        """Export the resulting document content from SuperDocs."""
        if self._mock_handler:
            res = self._mock_handler("export", {"doc_id": doc_id})
            return str(res.get("content", ""))
        # Real API is stateless — document is managed locally by the patch engine.
        return self._session_content.get(doc_id, "")

    def _markdown_to_simple_html(self, markdown: str) -> str:
        """Convert markdown to minimal HTML for the real SuperDocs API."""
        import re
        lines = markdown.splitlines()
        html_parts: List[str] = []
        for line in lines:
            m = re.match(r"^(#{1,6})\s+(.+)$", line)
            if m:
                level = len(m.group(1))
                text = m.group(2).strip()
                html_parts.append(f"<h{level}>{text}</h{level}>")
            elif line.strip():
                html_parts.append(f"<p>{line.strip()}</p>")
        return "\n".join(html_parts)

    def _parse_real_api_response(self, data: Dict[str, Any]) -> List[ProposedChange]:
        """Parse proposed changes from the real SuperDocs API response.

        Tries two locations in order:
        1. data['document_changes']['changes'] — structured list from the API
        2. JSON code block embedded in data['response'] text
        """
        import re

        def strip_html(html: str) -> str:
            return re.sub(r"<[^>]+>", "", html).strip()

        def find_section_for_chunk(chunk_id: str, updated_html: str) -> str:
            """Walk backwards in updated_html from the changed chunk to find the
            nearest h1/h2 heading — that is the section name."""
            # Find position of the chunk in the HTML
            pos = updated_html.find(chunk_id)
            if pos == -1:
                return "General"
            before = updated_html[:pos]
            # Find last heading before this chunk
            headings = list(re.finditer(r"<h[12][^>]*>([^<]+)</h[12]>", before))
            if headings:
                return headings[-1].group(1).strip()
            return "General"

        doc_changes = data.get("document_changes") or {}
        raw_changes = doc_changes.get("changes") or []
        updated_html = doc_changes.get("updated_html", "")

        if raw_changes:
            results: List[ProposedChange] = []
            for i, c in enumerate(raw_changes):
                old_text = strip_html(c.get("old_html", ""))
                new_text = strip_html(c.get("new_html", ""))
                raw_explanation = c.get("ai_explanation", "")

                # Try to extract target_section from the JSON embedded in ai_explanation
                target_section = "General"
                section_match = re.search(
                    r'"target_section"\s*:\s*"([^"]+)"', raw_explanation
                )
                if section_match:
                    target_section = section_match.group(1)
                else:
                    # Fall back: walk backwards in updated_html (or old_html) to the nearest heading
                    chunk_id = c.get("chunk_id", "")
                    search_html = updated_html if updated_html else c.get("old_html", "")
                    if chunk_id and search_html:
                        target_section = find_section_for_chunk(chunk_id, search_html)

                explanation = strip_html(raw_explanation)
                if old_text and new_text:
                    results.append(
                        ProposedChange(
                            change_id=c.get("change_id", f"c_{i}"),
                            target_section=target_section,
                            old_snippet=old_text,
                            new_snippet=new_text,
                            explanation=explanation[:200] if explanation else "",
                        )
                    )
            if results:
                return results

        # Strategy 2: JSON code block in the response text
        response_text = data.get("response", "")
        json_match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            return self._parse_proposed_changes(json_match.group(1))

        # No changes found → NOOP
        return []


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
