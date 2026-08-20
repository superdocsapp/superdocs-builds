"""Google Drive API client — async httpx, Bearer token per call.

Handles the two attachment shapes a Classroom submission can carry:
- a native Google file (application/vnd.google-apps.*) — the raw
  `alt=media` download returns nothing, so export to a usable format
  (docs -> text/html, spreadsheets -> csv, presentations -> plain text)
- a real binary file (docx/pdf/etc.) — downloaded directly via alt=media
"""

from __future__ import annotations

import json

import httpx

DRIVE_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)

# Native Google formats -> exportable MIME types SuperDocs can consume.
_NATIVE_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/html",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GoogleDriveClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GoogleDriveClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    async def get_file_metadata(self, access_token: str, file_id: str) -> dict:
        r = await self._client.get(
            f"{DRIVE_BASE}/files/{file_id}",
            headers=self._headers(access_token),
            params={"fields": "id,name,mimeType,size,webViewLink"},
        )
        r.raise_for_status()
        return r.json()

    async def download_file(
        self, access_token: str, file_id: str, mime_type: str | None = None
    ) -> bytes:
        """Downloads file bytes. For native Google files, exports to a
        text-bearing format instead (alt=media returns nothing for them)."""
        export_mime = _NATIVE_EXPORT_MIME.get(mime_type or "")
        if export_mime:
            r = await self._client.get(
                f"{DRIVE_BASE}/files/{file_id}/export",
                headers=self._headers(access_token),
                params={"mimeType": export_mime},
            )
        else:
            r = await self._client.get(
                f"{DRIVE_BASE}/files/{file_id}",
                headers=self._headers(access_token),
                params={"alt": "media"},
            )
        r.raise_for_status()
        return r.content

    async def upload_file(
        self, access_token: str, name: str, content: bytes, mime_type: str = DOCX_MIME
    ) -> dict:
        """Multipart upload (metadata JSON + binary content). Returns the
        created file's resource, whose `id` becomes reviewed_drive_file_id."""
        metadata = {"name": name, "mimeType": mime_type}
        boundary = "classroom_app_boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Type: application/json; charset=UTF-8\r\n\r\n'
            f"{json.dumps(metadata, separators=(',', ':'))}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()

        headers = self._headers(access_token)
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"
        r = await self._client.post(
            f"{UPLOAD_URL}?uploadType=multipart", headers=headers, content=body
        )
        r.raise_for_status()
        return r.json()
