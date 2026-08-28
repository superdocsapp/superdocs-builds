import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.superdocs.app"


class SuperDocsError(RuntimeError):
    """Raised when SuperDocs returns an unsuccessful response"""


def headers(api_key: str | None = None) -> dict[str, str]:
    key = api_key or os.getenv("SUPERDOCS_API_KEY")
    if not key:
        raise SuperDocsError("SUPERDOCS_API_KEY is not configured")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def request(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    try:
        request_headers = headers(api_key)
        if "files" in kwargs:
            request_headers.pop("Content-Type", None)
        response = httpx.request(
            method, f"{BASE_URL}{path}", headers=request_headers, timeout=120.0, **kwargs
        )
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise SuperDocsError(
            f"SuperDocs request failed ({exc.response.status_code}): {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SuperDocsError(
            f"SuperDocs request could not be completed: {exc}") from exc


# Load template into a SuperDocs session and return its session ID
def upload_document(html: str, session_id: str | None = None, api_key: str | None = None) -> str:
    if not html.strip():
        raise ValueError("Document HTML must not be empty")
    sid = session_id or str(uuid4())
    response = request(
        "POST",
        "/v1/chat",
        api_key=api_key,
        json={
            "message": "Load this document exactly as provided; do not modify it.",
            "session_id": sid,
            "document_html": html,
            "approval_mode": "approve_all",
        },
    )
    print(f"SuperDocs upload response: {response.json()}")
    return sid


# Return the active reusable templates visible to the authenticated user
def list_user_templates(api_key: str | None = None) -> list[dict[str, Any]]:
    result = request("GET", "/v1/templates",
                     api_key=api_key).json()
    print(f"SuperDocs list templates response: {result}")
    return result if isinstance(result, list) else result.get("templates", [])


# Upload a local file as a reusable SuperDocs template
def upload_user_template(path: str | Path, api_key: str | None = None) -> dict[str, Any]:
    template_path = Path(path)
    if not template_path.is_file():
        raise FileNotFoundError(template_path)
    with template_path.open("rb") as template_file:
        response = request(
            "POST",
            "/v1/templates/upload",
            api_key=api_key,
            files={"file": (template_path.name, template_file)},
        )
    result = response.json()
    print(f"SuperDocs upload template response: {result}")
    return result if isinstance(result, dict) else {"template": result}


# Chat with SuperDocs
def send_chat_instruction(
    session_id: str,
    message: str,
    api_key: str | None = None,
    document_html: str | None = None,
) -> dict[str, Any]:
    if not message.strip():
        raise ValueError("Chat instruction must not be empty")
    payload = {
        "message": message,
        "session_id": session_id,
        "approval_mode": "approve_all",
    }
    if document_html is not None:
        payload["document_html"] = document_html
    response = request("POST", "/v1/chat", api_key=api_key, json=payload)
    result = response.json()
    print(f"SuperDocs chat response: {result}")
    document_changes = result.get("document_changes") or {}
    if document_changes.get("requires_approval") is True:
        job_id = document_changes.get("job_id") or (
            result.get("hint") or {}).get("job_id")
        if not job_id:
            raise SuperDocsError(
                "SuperDocs requested approval but did not return a job_id"
            )
        approved = approve_pending_changes(
            session_id, job_id, approved=True, api_key=api_key
        )
        print(f"SuperDocs approval response: {approved}")
        return approved
    return result


# Approve or deny pending changes from SuperDocs
def approve_pending_changes(
    session_id: str, job_id: str, approved: bool = True, api_key: str | None = None
) -> dict[str, Any]:
    return request(
        "POST", f"/v1/chat/{session_id}/approve", api_key=api_key,
        json={"job_id": job_id, "approved": approved},
    ).json()


# Export current session document
def export_document(session_id: str, format: str = "pdf", api_key: str | None = None) -> bytes:
    allowed = {"docx", "pdf", "html", "markdown", "txt", "doc"}
    if format not in allowed:
        raise ValueError(f"Unsupported export format: {format}")
    return request(
        "POST", "/v1/documents/export", api_key=api_key,
        json={"session_id": session_id, "format": format},
    ).content
