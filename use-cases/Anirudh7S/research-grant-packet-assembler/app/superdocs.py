import os
from typing import Any, Dict

import requests
from dotenv import load_dotenv


# Load variables from the project's .env file.
load_dotenv()


BASE_URL = os.getenv(
    "SUPERDOCS_API_URL",
    "https://api.superdocs.app",
).rstrip("/") + "/v1"


class SuperDocsError(Exception):
    """Raised when a SuperDocs API request fails."""


class SuperDocsClient:
    """Small Python client for the SuperDocs API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")

        if not self.api_key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY environment variable is not set."
            )

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Make an API request and return JSON."""

        url = f"{BASE_URL}{endpoint}"

        response = requests.request(
            method,
            url,
            headers=self.headers,
            timeout=60,
            **kwargs,
        )

        if not response.ok:
            raise SuperDocsError(
                f"SuperDocs API error "
                f"{response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise SuperDocsError(
                f"SuperDocs returned invalid JSON: {response.text}"
            ) from exc

    def init_session(self) -> Dict[str, Any]:
        """Create a new SuperDocs session."""

        return self._request(
            "POST",
            "/sessions/init",
            json={},
        )

    def upload_document(
        self,
        file_path: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Upload a document into a SuperDocs session."""

        path = os.path.abspath(file_path)

        if not os.path.isfile(path):
            raise SuperDocsError(
                f"Document not found: {path}"
            )

        with open(path, "rb") as file:
            files = {
                "file": (
                    os.path.basename(path),
                    file,
                )
            }

            data = {
                "session_id": session_id,
            }

            return self._request(
                "POST",
                "/documents/upload",
                files=files,
                data=data,
            )

    def chat(
        self,
        session_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """Send a synchronous chat request."""

        return self._request(
            "POST",
            "/chat",
            json={
                "session_id": session_id,
                "message": message,
            },
        )

    def chat_async(
        self,
        session_id: str,
        message: str,
        approval_mode: str | None = None,
    ) -> Dict[str, Any]:
        """Queue an asynchronous chat request."""

        body: Dict[str, Any] = {
            "session_id": session_id,
            "message": message,
        }

        if approval_mode is not None:
            body["approval_mode"] = approval_mode

        return self._request(
            "POST",
            "/chat/async",
            json=body,
        )

    def get_job(
        self,
        job_id: str,
    ) -> Dict[str, Any]:
        """Get the current status of an asynchronous job."""

        return self._request(
            "GET",
            f"/jobs/{job_id}",
        )

    def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool = True,
    ) -> Dict[str, Any]:
        """Approve or reject a pending HITL change."""

        return self._request(
            "POST",
            f"/chat/{session_id}/approve",
            json={
                "approved": approved,
                "job_id": job_id,
                "change_id": change_id,
            },
        )

    def export_document(
        self,
        session_id: str,
        html: str,
        filename: str = "grant_packet.docx",
    ) -> bytes:
        """Export the current SuperDocs document as a DOCX file."""

        url = f"{BASE_URL}/documents/export"

        response = requests.post(
            url,
            headers=self.headers,
            json={
                "session_id": session_id,
                "html": html,
                "format": "docx",
                "filename": filename,
            },
            timeout=60,
        )

        if not response.ok:
            raise SuperDocsError(
                f"SuperDocs export error "
                f"{response.status_code}: {response.text}"
            )

        return response.content