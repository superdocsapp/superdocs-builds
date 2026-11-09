import os
import json
import requests

BASE_URL = "https://api.superdocs.app/v1"
REQUEST_TIMEOUT = 30  # seconds -- prevents an indefinite hang on network issues


class SuperDocsError(Exception):
    """Raised when the SuperDocs API returns an error or unexpected shape."""
    pass


def _get_headers():
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        raise SuperDocsError(
            "SUPERDOCS_API_KEY not set. Run: export SUPERDOCS_API_KEY='sk_...' "
            "or load it from a .env file before calling the client."
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def send_edit(session_id: str, message: str, document_html: str = None) -> dict:
    """
    Send an edit instruction. If document_html is provided, it (re)initializes
    the document for this session. Omit it on follow-up turns in the same
    session to keep editing what's already there.

    Returns the parsed response dict. Raises SuperDocsError on failure.
    """
    payload = {"session_id": session_id, "message": message}
    if document_html is not None:
        payload["document_html"] = document_html

    resp = requests.post(f"{BASE_URL}/chat", headers=_get_headers(), json=payload, timeout=REQUEST_TIMEOUT)

    if resp.status_code != 200:
        raise SuperDocsError(f"chat call failed ({resp.status_code}): {resp.text}")

    data = resp.json()

    # Debug visibility gated behind an explicit env var -- printing full raw
    # API responses by default risks leaking document contents into logs.
    if data.get("document_changes") is None and os.environ.get("SUPERDOCS_DEBUG"):
        print("⚠️  document_changes was null. Full raw response:")
        print(json.dumps(data, indent=2))

    changes = data.get("document_changes") or {}
    for change in changes.get("changes") or []:
        for key in ("old_html", "new_html"):
            val = change.get(key)
            if isinstance(val, str) and val.strip().startswith("{"):
                try:
                    change[key] = json.loads(val)
                except json.JSONDecodeError:
                    pass  # it was just HTML that happened to start with '{', leave it

    return data


def approve_changes(version_id: str, change_ids: list[str] = None, approve_all: bool = True) -> dict:
    """
    NOT YET CONFIRMED against live docs — path/shape is inferred from the task
    doc's naming, not verified. Test this before depending on it.
    """
    payload = {"version_id": version_id}
    if approve_all:
        payload["approve_all"] = True
    else:
        payload["change_ids"] = change_ids or []

    resp = requests.post(f"{BASE_URL}/approve", headers=_get_headers(), json=payload, timeout=REQUEST_TIMEOUT)

    if resp.status_code == 404:
        raise SuperDocsError(
            "POST /v1/approve returned 404 — endpoint path is unconfirmed, "
            "check docs.superdocs.app for the real name before proceeding."
        )
    if resp.status_code != 200:
        raise SuperDocsError(f"approve call failed ({resp.status_code}): {resp.text}")

    return resp.json()


def export_document(html: str, filename: str = "document", format: str = "docx") -> bytes:
    """
    Confirmed shape (captured from the web app's own network traffic):
    the export call takes the full current document HTML directly, not a
    session_id.
    """
    payload = {
        "format": format,
        "html": html,
        "options": {
            "paper_size": "Letter",
            "orientation": "portrait",
            "margins": "custom",
            "custom_margins_inches": {"top": 1, "right": 1, "bottom": 1, "left": 1},
            "source_filename": filename,
        },
    }

    resp = requests.post(f"{BASE_URL}/documents/export", headers=_get_headers(), json=payload, timeout=REQUEST_TIMEOUT)

    if resp.status_code == 404:
        raise SuperDocsError(
            "POST /v1/documents/export returned 404 on api.superdocs.app — "
            "this path was captured from the web app's session-authenticated "
            "internal API, may not exist identically on the Bearer-key API."
        )
    if resp.status_code != 200:
        raise SuperDocsError(f"export call failed ({resp.status_code}): {resp.text}")

    return resp.content