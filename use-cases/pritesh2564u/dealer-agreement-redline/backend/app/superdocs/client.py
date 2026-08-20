from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings


class SuperDocsError(Exception):
    """Raised when the SuperDocs API returns an error."""


class SuperDocsClient:
    BASE_URL = "https://api.superdocs.app/v1"

    def __init__(self) -> None:
        settings = get_settings()

        self.api_key = settings.superdocs_api_key

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

    async def verify_key(self) -> Any:
        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        ) as client:
            response = await client.get(
                "/sessions",
                headers=self.headers,
            )

        if response.is_error:
            raise SuperDocsError(
                f"SuperDocs authentication failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    async def upload_document(
        self,
        file_path: str | Path,
        session_id: str,
    ) -> dict[str, Any]:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {path}"
            )

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=120.0,
        ) as client:

            with path.open("rb") as file:
                response = await client.post(
                    "/documents/upload",
                    headers=self.headers,
                    files={
                        "file": (
                            path.name,
                            file,
                            self._content_type(path),
                        )
                    },
                    data={
                        "session_id": session_id,
                    },
                )

        self._raise_for_error(response)

        return response.json()

    async def upload_attachment(
        self,
        file_path: str | Path,
        session_id: str,
    ) -> dict[str, Any]:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Attachment not found: {path}"
            )

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=120.0,
        ) as client:

            with path.open("rb") as file:
                response = await client.post(
                    "/attachments/upload",
                    headers=self.headers,
                    files={
                        "file": (
                            path.name,
                            file,
                            self._content_type(path),
                        )
                    },
                    data={
                        "session_id": session_id,
                    },
                )

        self._raise_for_error(response)

        return response.json()

    async def get_job(
        self,
        job_id: str,
    ) -> dict[str, Any]:

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        ) as client:

            response = await client.get(
                f"/jobs/{job_id}",
                headers=self.headers,
            )

        self._raise_for_error(response)

        return response.json()

    async def chat(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        document_id: str | None = None,
        approval_mode: str | None = None,
        response_mode: str | None = None,
    ) -> dict[str, Any]:

        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
        }

        if document_html is not None:
            payload["document_html"] = document_html

        if document_id is not None:
            payload["document_id"] = document_id

        if approval_mode is not None:
            payload["approval_mode"] = approval_mode

        if response_mode is not None:
            payload["response_mode"] = response_mode

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=180.0,
        ) as client:

            response = await client.post(
                "/chat",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response)

        return response.json()

    async def approve_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> dict[str, Any]:

        payload: dict[str, Any] = {
            "job_id": job_id,
            "change_id": change_id,
            "approved": approved,
        }

        if feedback:
            payload["feedback"] = feedback

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=120.0,
        ) as client:

            response = await client.post(
                f"/chat/{session_id}/approve",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response)

        return response.json()

    async def export_document(
        self,
        *,
        session_id: str,
        filename: str,
    ) -> bytes:

        payload = {
            "session_id": session_id,
            "format": "docx",
            "options": {
                "filename": filename,
            },
        }

        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=180.0,
        ) as client:

            response = await client.post(
                "/documents/export",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response)

        return response.content

    @staticmethod
    def _content_type(path: Path) -> str:
        suffix = path.suffix.lower()

        mapping = {
            ".pdf": "application/pdf",
            ".docx": (
                "application/vnd.openxmlformats-"
                "officedocument.wordprocessingml.document"
            ),
            ".doc": "application/msword",
            ".txt": "text/plain",
            ".html": "text/html",
            ".htm": "text/html",
            ".md": "text/markdown",
            ".rtf": "application/rtf",
        }

        return mapping.get(
            suffix,
            "application/octet-stream",
        )

    @staticmethod
    def _raise_for_error(
        response: httpx.Response,
    ) -> None:

        if response.is_success:
            return

        raise SuperDocsError(
            f"SuperDocs API error "
            f"{response.status_code}: "
            f"{response.text}"
        )