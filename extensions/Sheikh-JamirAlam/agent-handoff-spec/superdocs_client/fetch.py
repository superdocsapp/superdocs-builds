from collections.abc import Callable
import re
from html import unescape
from typing import Any

import httpx

from agents import DocumentState
from schema import ReviewState


class SuperDocsAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        if isinstance(detail, dict):
            message = detail.get("message_user") or detail.get(
                "message") or str(detail)
            action = detail.get("suggested_action")
            text = f"{message}" + \
                (f" Suggested action: {action}" if action else "")
        else:
            text = str(detail)
        super().__init__(f"SuperDocs API error ({status_code}): {text}")


# Fetch existing document
class SuperDocsFetchAdapter:
    @staticmethod
    def chunks(html: str, sections: dict[str, str]) -> dict[str, list[dict[str, str]]]:
        chunks: dict[str, list[dict[str, str]]] = {
            name: [] for name in sections}
        pattern = re.compile(
            r'<([a-zA-Z][\w:-]*)\b[^>]*data-chunk-id=["\']([^"\']+)["\'][^>]*>(.*?)</\1>', re.I | re.S)
        for _, chunk_id, raw in pattern.findall(html):
            text = re.sub(r'<[^>]+>', '', raw)
            text = unescape(text).strip()
            for section, value in sections.items():
                if text and text in value:
                    chunks[section].append(
                        {"chunk_id": chunk_id, "text": text})
                    break
        return chunks

    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app",
                 client: httpx.Client | None = None, verbose: bool = False,
                 timeout: float = 180.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.verbose = verbose

    def fetch(self, document_id: str,
              section_extractor: Callable[[str], dict[str, str]] | None = None) -> DocumentState:
        url = f"{self._base_url}/v1/documents/{document_id}"
        if self.verbose:
            print(f"[SuperDocs] GET {url}?include_html=true")
        response = self._client.get(
            url,
            params={"include_html": "true"},
            headers=self._headers,
        )
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise SuperDocsAPIError(response.status_code, detail)
        payload: dict[str, Any] = response.json()
        html = payload.get("html") or payload.get("document_html") or ""
        sections = section_extractor(html) if section_extractor else {
            "document": html}
        raw_state = payload.get("review_state", "draft")
        return DocumentState(
            document_id=str(payload.get("id", document_id)),
            review_state=ReviewState(raw_state),
            sections=sections,
            chunks=SuperDocsFetchAdapter.chunks(html, sections),
            raw_html=html,
        )

    def create_session(self, document_id: str) -> str:
        if self.verbose:
            print(
                f"[SuperDocs] POST {self._base_url}/v1/sessions/init payload={{'document_ids': ['{document_id}']}}")
        response = self._client.post(
            f"{self._base_url}/v1/sessions/init",
            headers=self._headers,
            json={"document_ids": [document_id]},
        )
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise SuperDocsAPIError(response.status_code, detail)
        payload = response.json()
        if self.verbose:
            print(f"[SuperDocs] POST response={payload}")
        return str(payload["session_id"])

    def close(self) -> None:
        self._client.close()
