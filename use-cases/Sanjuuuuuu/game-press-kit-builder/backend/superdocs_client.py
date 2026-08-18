import base64
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


class SuperDocsAPIError(RuntimeError):
    """Actionable error for live SuperDocs failures."""


class SuperDocsClient:
    BASE_URL = os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app/v1")

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise RuntimeError("SUPERDOCS_API_KEY is missing. Add it to your .env file.")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _post(self, path: str, payload: dict[str, Any], timeout: float = 180) -> httpx.Response:
        try:
            response = httpx.post(f"{self.BASE_URL}{path}", headers=self._headers(), json=payload, timeout=timeout)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            raise SuperDocsAPIError(f"SuperDocs returned HTTP {exc.response.status_code}: {body}") from exc
        except httpx.RequestError as exc:
            raise SuperDocsAPIError(f"SuperDocs request failed: {exc}") from exc

    def upload(self, file_path: str, session_id: str, return_html: bool = True) -> dict[str, Any]:
        with open(file_path, "rb") as file:
            file_base64 = base64.b64encode(file.read()).decode("utf-8")
        return self._post("/documents/upload-base64", {
            "filename": os.path.basename(file_path),
            "file_base64": file_base64,
            "session_id": session_id,
            "return_html": return_html,
        }).json()

    def chat(self, message: str, session_id: str, document_html: str) -> dict[str, Any]:
        return self._post("/chat", {
            "message": message,
            "session_id": session_id,
            "document_html": document_html,
        }).json()

    def approve(self, session_id: str, job_id: str, approved: bool, change_id: str, feedback: str = "", changes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._post(f"/chat/{session_id}/approve", {
            "job_id": job_id,
            "approved": approved,
            "change_id": change_id,
            "feedback": feedback,
            "changes": changes or [],
        }).json()

    def export(self, session_id: str, html: str, filename: str, source_filename: str, upload_id: str | None = None, format: str = "docx") -> dict[str, Any]:
        response = self._post("/documents/export", {
            "session_id": session_id,
            "html": html,
            "format": format,
            "options": {
                "paper_size": "Letter",
                "orientation": "portrait",
                "margins": "normal",
                "custom_margins_inches": {},
                "filename": filename,
                "embed_images": True,
                "watermark_text": "",
                "watermark_opacity": 0.3,
            },
            "filename": filename,
            "source_filename": source_filename,
            "upload_id": upload_id,
        })
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {"content_type": content_type, "content": response.content, "filename": filename}
