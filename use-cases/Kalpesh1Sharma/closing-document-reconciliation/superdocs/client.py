from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()


class SuperDocsError(RuntimeError):
    pass


class SuperDocsClient:
    BASE_URL = "https://api.superdocs.app"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 180,
    ) -> None:
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is missing. "
                "Add it to your local .env file."
            )

    @property
    def auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    @property
    def json_headers(self) -> dict[str, str]:
        return {
            **self.auth_headers,
            "Content-Type": "application/json",
        }

    def upload_document(
        self,
        *,
        path: str | Path,
        session_id: str,
        open_mode: str = "replace",
    ) -> dict[str, Any]:
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(path)

        with path.open("rb") as file_handle:
            response = requests.post(
                f"{self.BASE_URL}/v1/documents/upload",
                headers=self.auth_headers,
                files={
                    "file": (
                        path.name,
                        file_handle,
                    )
                },
                data={
                    "session_id": session_id,
                    "open_mode": open_mode,
                },
                timeout=self.timeout,
            )

        if not response.ok:
            raise SuperDocsError(
                f"Upload failed for {path.name}. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def list_session_documents(
        self,
        *,
        session_id: str,
    ) -> Any:
        response = requests.get(
            (
                f"{self.BASE_URL}/v1/sessions/"
                f"{session_id}/documents"
            ),
            headers=self.auth_headers,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Failed to list session documents. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()


    def chat(
        self,
        *,
        session_id: str,
        message: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
        }

        if document_id is not None:
            payload["document_id"] = document_id

        response = requests.post(
            f"{self.BASE_URL}/v1/chat",
            headers=self.json_headers,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Chat request failed. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def start_async_chat(
        self,
        *,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
    ) -> dict[str, Any]:
        payload = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }

        response = requests.post(
            f"{self.BASE_URL}/v1/chat/async",
            headers=self.json_headers,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Failed to start async chat. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def get_job(
        self,
        *,
        job_id: str,
    ) -> dict[str, Any]:
        response = requests.get(
            f"{self.BASE_URL}/v1/jobs/{job_id}",
            headers=self.auth_headers,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Failed to read job status. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def approve_changes(
        self,
        *,
        session_id: str,
        job_id: str,
        changes: list[dict[str, Any]],
        approved: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "job_id": job_id,

            # Required even when every individual change
            # below has its own approval decision.
            "approved": approved,

            "changes": changes,
        }

        response = requests.post(
            (
                f"{self.BASE_URL}/v1/chat/"
                f"{session_id}/approve"
            ),
            headers=self.json_headers,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Failed to submit approval decision. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def continue_job(
        self,
        *,
        session_id: str,
        job_id: str,
        should_continue: bool,
    ) -> dict[str, Any]:
        response = requests.post(
            (
                f"{self.BASE_URL}/v1/chat/"
                f"{session_id}/continue"
            ),
            headers=self.json_headers,
            json={
                "job_id": job_id,
                "continue": should_continue,
            },
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Failed to continue job. "
                f"HTTP {response.status_code}: {response.text}"
            )

        return response.json()

    def export_document(
        self,
        *,
        session_id: str,
        output_path: str | Path,
        filename: str,
        file_format: str = "docx",
    ) -> Path:
        output_path = Path(output_path)

        payload = {
            "session_id": session_id,
            "format": file_format,
            "filename": filename,
        }

        response = requests.post(
            f"{self.BASE_URL}/v1/documents/export",
            headers=self.json_headers,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            raise SuperDocsError(
                "Document export failed. "
                f"HTTP {response.status_code}: {response.text}"
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_bytes(
            response.content
        )

        return output_path