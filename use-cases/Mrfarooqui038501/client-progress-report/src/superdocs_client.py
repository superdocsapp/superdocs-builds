"""
Thin wrapper around the SuperDocs REST API.

API endpoints are based on the SuperDocs OpenAPI specification:

  Auth:
      Authorization: Bearer sk_...

  Chat:
      POST /v1/chat

  Images:
      POST /v1/documents/images/upload-base64

  Export:
      POST /v1/documents/export

  Document list:
      GET /v1/sessions/{session_id}/documents

  Persist:
      POST /v1/sessions/{session_id}/documents/{document_id}/save

  Sessions/history:
      GET /v1/sessions
      GET /v1/sessions/{id}/history

The batch runner uses synchronous /v1/chat with
approval_mode="approve_all" because the workflow is unattended.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

import httpx


BASE_URL = os.environ.get(
    "SUPERDOCS_BASE_URL",
    "https://api.superdocs.app",
)

DEFAULT_TIMEOUT = 300.0

T = TypeVar("T")


class SuperDocsError(RuntimeError):
    """
    Represents a non-successful SuperDocs API response.
    """

    def __init__(
        self,
        status_code: int,
        body: str,
    ):
        super().__init__(
            f"SuperDocs API {status_code}: {body}"
        )
        self.status_code = status_code
        self.body = body


@dataclass
class ChatResult:
    response_text: str
    updated_html: Optional[str]
    version_id: Optional[str]
    monthly_remaining: Optional[int]


class SuperDocsClient:
    """
    Small explicit wrapper around the SuperDocs REST API.

    No hidden retries are performed inside individual methods.

    The caller can use retry_with_backoff() around operations where retrying
    is safe and useful.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = (
            api_key
            or os.environ.get("SUPERDOCS_API_KEY")
        )

        if not self.api_key:
            raise ValueError(
                "No SuperDocs API key found. "
                "Set SUPERDOCS_API_KEY or pass api_key=."
            )

        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=timeout,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def verify_key(self) -> bool:
        """
        GET /v1/sessions.

        A 200 means the key was accepted.
        Other statuses return False instead of raising because this method
        is used as a CLI pre-flight check.
        """

        response = self._client.get(
            "/v1/sessions"
        )

        return response.status_code == 200

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        message: str,
        session_id: str,
        document_html: Optional[str] = None,
        approval_mode: str = "approve_all",
        model_tier: Optional[str] = None,
    ) -> ChatResult:
        """
        POST /v1/chat.

        This method intentionally does not retry automatically because a
        timeout after the server accepts an AI mutation can make it unclear
        whether the request already succeeded.
        """

        payload = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }

        if document_html is not None:
            payload["document_html"] = document_html

        if model_tier:
            payload["model_tier"] = model_tier

        response = self._client.post(
            "/v1/chat",
            json=payload,
        )

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        data = response.json()

        changes = data.get(
            "document_changes"
        ) or {}

        usage = data.get(
            "usage"
        ) or {}

        return ChatResult(
            response_text=data.get(
                "response",
                "",
            ),
            updated_html=changes.get(
                "updated_html"
            ),
            version_id=changes.get(
                "version_id"
            ),
            monthly_remaining=usage.get(
                "monthly_remaining"
            ),
        )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def list_session_documents(
        self,
        session_id: str,
    ) -> list[dict]:
        """
        GET /v1/sessions/{session_id}/documents.

        Used to discover the durable document id needed by save.
        """

        response = self._client.get(
            f"/v1/sessions/{session_id}/documents"
        )

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        data = response.json()

        if isinstance(data, dict):
            documents = data.get(
                "documents",
                data,
            )
        else:
            documents = data

        if not isinstance(documents, list):
            raise SuperDocsError(
                200,
                "Unexpected document-list response shape",
            )

        return documents

    def persist_document(
        self,
        session_id: str,
        document_id: str,
        html: str,
    ) -> dict:
        """
        POST /v1/sessions/{session_id}/documents/{document_id}/save.

        This is a non-AI document write.

        The batch runner sends deterministic table/chart HTML here so the AI
        does not have to reproduce numerical values.
        """

        response = self._client.post(
            f"/v1/sessions/{session_id}/documents/"
            f"{document_id}/save",
            json={
                "html": html,
            },
        )

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        return response.json()

    def get_session_history(
        self,
        session_id: str,
    ) -> Optional[dict]:
        response = self._client.get(
            f"/v1/sessions/{session_id}/history"
        )

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        return response.json()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def upload_image(
        self,
        png_bytes: bytes,
        filename: str = "chart.png",
    ) -> str:
        """
        POST /v1/documents/images/upload-base64.

        Returns the stable image URL.
        """

        encoded = base64.b64encode(
            png_bytes
        ).decode("ascii")

        response = self._client.post(
            "/v1/documents/images/upload-base64",
            json={
                "image_base64": encoded,
                "filename": filename,
            },
        )

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        data = response.json()

        image_url = data.get("url")

        if not image_url:
            raise SuperDocsError(
                200,
                "Image upload succeeded but response did not contain 'url'",
            )

        return image_url

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(
        self,
        *,
        session_id: Optional[str] = None,
        html: Optional[str] = None,
        fmt: str = "docx",
        filename: Optional[str] = None,
    ) -> bytes:
        """
        POST /v1/documents/export.

        Either session_id or html must be provided.
        """

        if not session_id and not html:
            raise ValueError(
                "export() needs session_id or html"
            )

        payload: dict = {
            "format": fmt,
        }

        if session_id:
            payload["session_id"] = session_id

        if html:
            payload["html"] = html

        if filename:
            payload["options"] = {
                "filename": filename,
            }

        response = self._client.post(
            "/v1/documents/export",
            json=payload,
        )

        if response.status_code != 200:
            raise SuperDocsError(
                response.status_code,
                response.text,
            )

        return response.content


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    base_delay: float = 1.5,
) -> T:
    """
    Retry transient SuperDocs errors.

    Retry:
        429 - rate limit
        502 - bad gateway
        503 - service unavailable
        504 - gateway timeout

    Do not retry:
        400
        401
        403
        404
        other 4xx errors

    The batch runner deliberately avoids wrapping AI chat mutations in this
    helper because an ambiguous timeout after server-side processing could
    otherwise result in duplicate AI turns.
    """

    attempt = 0

    while True:
        try:
            return fn()

        except SuperDocsError as exc:
            attempt += 1

            retryable = exc.status_code in (
                429,
                502,
                503,
                504,
            )

            if not retryable or attempt > retries:
                raise

            delay = base_delay * (
                2 ** (attempt - 1)
            )

            time.sleep(delay)