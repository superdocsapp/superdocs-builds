import base64
from pathlib import Path

import httpx

from app.config import SUPERDOCS_API_KEY, SUPERDOCS_BASE_URL


class SuperDocsError(Exception):
    """Raised when a SuperDocs API request fails."""


class SuperDocsClient:
    def __init__(self) -> None:
        self.base_url = SUPERDOCS_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
        }

    async def chat(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        image_attachments: list[dict] | None = None,
    ) -> dict:
        """Send a synchronous SuperDocs edit request."""

        payload = {
            "message": message,
            "session_id": session_id,
        }

        if document_html is not None:
            payload["document_html"] = document_html

        if image_attachments:
            payload["image_attachments"] = image_attachments

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response, "chat")
        return response.json()

    async def upload_document(
        self,
        *,
        session_id: str,
        file_path: str | Path,
    ) -> dict:
        """
        Upload a document into a SuperDocs editing session.
        """

        path = Path(file_path)

        if not path.exists():
            raise SuperDocsError(
                f"Document does not exist: {path}"
            )

        with path.open("rb") as file:
            files = {
                "file": (
                    path.name,
                    file,
                    self._content_type(path),
                )
            }

            data = {
                "session_id": session_id,
                "open_mode": "replace",
            }

            async with httpx.AsyncClient(
                timeout=120.0
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/documents/upload",
                    headers=self.headers,
                    data=data,
                    files=files,
                )

        self._raise_for_error(response, "document upload")
        return response.json()

    async def upload_image(
        self,
        *,
        file_path: str | Path,
    ) -> dict:
        """
        Upload an image to SuperDocs and receive a
        stable URL that can be embedded into report HTML.
        """

        path = Path(file_path)

        if not path.exists():
            raise SuperDocsError(
                f"Image does not exist: {path}"
            )

        raw_bytes = path.read_bytes()
        encoded = base64.b64encode(
            raw_bytes
        ).decode("ascii")

        payload = {
            "image_base64": encoded,
            "filename": path.name,
            "content_type": self._content_type(path),
        }

        async with httpx.AsyncClient(
            timeout=120.0
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/images/upload-base64",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response, "image upload")
        return response.json()

    async def start_approval_job(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        image_attachments: list[dict] | None = None,
    ) -> dict:
        """Start an asynchronous AI edit requiring human approval."""

        payload = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
        }

        if document_html is not None:
            payload["document_html"] = document_html

        if image_attachments:
            payload["image_attachments"] = image_attachments

        async with httpx.AsyncClient(
            timeout=120.0
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/async",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response, "async chat")
        return response.json()

    async def get_job(
        self,
        job_id: str,
    ) -> dict:
        """Get the current status of an asynchronous SuperDocs job."""

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:
            response = await client.get(
                f"{self.base_url}/v1/jobs/{job_id}",
                headers=self.headers,
            )

        self._raise_for_error(response, "job status")
        return response.json()

    async def approve_changes(
        self,
        *,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[dict] | None = None,
    ) -> dict:
        """
        Approve or deny proposed AI changes.

        SuperDocs expects batch approval entries to contain only
        the change_id and the per-change approval decision.
        """

        payload = {
            "job_id": job_id,
            "approved": approved,
        }

        if changes is not None:
            payload["changes"] = [
                {
                    "change_id": change["change_id"],
                    "approved": approved,
                }
                for change in changes
            ]

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/{session_id}/approve",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response, "approval")
        return response.json()
    async def export_document(
        self,
        *,
        session_id: str,
        format: str = "pdf",
        filename: str = "daily-field-report",
    ) -> dict:
        """
        Export the current SuperDocs session document.

        The SuperDocs export endpoint returns the generated
        document as binary content. The file is saved locally
        instead of attempting to parse it as JSON.
        """

        if format not in {
            "pdf",
            "docx",
            "html",
            "markdown",
            "txt",
        }:
            raise ValueError(
                "Unsupported export format."
            )

        payload = {
            "session_id": session_id,
            "format": format,
            "options": {
                "filename": filename,
                "embed_images": True,
            },
        }

        async with httpx.AsyncClient(
            timeout=120.0
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/export",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        self._raise_for_error(response, "export")

        output_dir = Path("storage/exports")
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        extension = (
            "md"
            if format == "markdown"
            else format
        )

        output_path = (
            output_dir
            / f"{filename}.{extension}"
        )

        output_path.write_bytes(
            response.content
        )

        return {
            "status": "exported",
            "format": format,
            "filename": output_path.name,
            "path": str(output_path),
            "content_type": response.headers.get(
                "content-type",
                "",
            ),
            "size_bytes": len(
                response.content
            ),
        }

    @staticmethod
    def _content_type(
        path: Path,
    ) -> str:
        suffix = path.suffix.lower()

        content_types = {
            ".html": "text/html",
            ".htm": "text/html",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
            ".docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
        }

        return content_types.get(
            suffix,
            "application/octet-stream",
        )

    @staticmethod
    def _raise_for_error(
        response: httpx.Response,
        operation: str,
    ) -> None:
        if response.is_error:
            raise SuperDocsError(
                f"SuperDocs {operation} failed: "
                f"{response.status_code} "
                f"{response.text}"
            )