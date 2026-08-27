from pathlib import Path
from typing import Any, Literal

import httpx


class SuperDocsMutationAdapter:
    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app",
                 client: httpx.Client | None = None, verbose: bool = False) -> None:
        self._client = client or httpx.Client(timeout=180.0)
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.verbose = verbose

    def log(self, method: str, url: str, payload: dict[str, Any] | None = None) -> None:
        if self.verbose:
            print(f"[SuperDocs] {method} {url}")
            if payload is not None:
                print(f"[SuperDocs] payload={payload}")

    def edit(self, session_id: str, message: str,
             approval_mode: Literal["approve_all", "ask_every_time"] = "approve_all") -> dict[str, Any]:
        self.log("POST", f"{self._base_url}/v1/chat", {
            "session_id": session_id, "message": message,
            "approval_mode": approval_mode, "response_mode": "compact"})
        response = self._client.post(
            f"{self._base_url}/v1/chat",
            headers=self._headers,
            json={
                "session_id": session_id,
                "message": message,
                "approval_mode": approval_mode,
                "response_mode": "compact",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if self.verbose:
            print(f"[SuperDocs] POST response={payload}")
        return payload

    def approve(self, session_id: str, *, approved: bool = True,
                job_id: str | None = None,
                changes: list[dict[str, Any]] | None = None,
                feedback: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"approved": approved}
        if job_id is not None:
            body["job_id"] = job_id
        if changes is not None:
            body["changes"] = changes
        if feedback is not None:
            body["feedback"] = feedback
        self.log(
            "POST", f"{self._base_url}/v1/chat/{session_id}/approve", body)
        response = self._client.post(
            f"{self._base_url}/v1/chat/{session_id}/approve",
            headers=self._headers,
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        if self.verbose:
            print(f"[SuperDocs] POST response={payload}")
        return payload

    def export(self, session_id: str, format: str = "docx",
               options: dict[str, Any] | None = None,
               output_path: str | Path | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id, "format": format}
        if options is not None:
            body["options"] = options
        self.log("POST", f"{self._base_url}/v1/documents/export", body)
        response = self._client.post(
            f"{self._base_url}/v1/documents/export",
            headers=self._headers,
            json=body,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
            if self.verbose:
                print(f"[SuperDocs] POST response={payload}")
            return payload
        if self.verbose:
            print(
                f"[SuperDocs] POST response=<binary {len(response.content)} bytes; "
                f"content_type={content_type!r}>"
            )
        if output_path is None:
            raise RuntimeError(
                "SuperDocs returned binary export data; output_path is required")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return {
            "path": str(path),
            "content_type": content_type,
            "bytes": len(response.content),
        }

    def close(self) -> None:
        self._client.close()
