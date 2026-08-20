"""
superdocs_pipeline.py — reusable SuperDocs-side functions for the
Streamlit app. Two generation paths, both real and tested:

1. generate_plain() — the /v1/chat path. Proven reliable across every
   test in this build. Used as the default.
2. generate_with_approval_start() / submit_approval_decision() —
   the /v1/chat/async + approval_mode='ask_every_time' path. Also
   proven to WORK when it triggers - but found, via repeated testing,
   to activate inconsistently. Offered as an opt-in "experimental"
   mode in the UI, disclosed honestly, not hidden.
"""
import base64

import requests

SUPERDOCS_API_BASE = "https://api.superdocs.app/v1"


def upload_image(api_key: str, image_path) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    response = requests.post(
        f"{SUPERDOCS_API_BASE}/documents/images/upload-base64",
        headers=headers,
        json={"image_base64": image_base64},
    )
    if response.status_code != 200:
        return None
    return response.json().get("url")


def seed_document(api_key: str, session_id: str, seed_html: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(
        f"{SUPERDOCS_API_BASE}/chat",
        headers=headers,
        json={
            "message": "Load this content as the starting document. Do not rewrite anything yet.",
            "session_id": session_id,
            "document_html": seed_html,
        },
    )
    return response.json()


def generate_plain(api_key: str, session_id: str, instruction: str) -> dict:
    """The reliable path - proven across every test in this build."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(
        f"{SUPERDOCS_API_BASE}/chat",
        headers=headers,
        json={"message": instruction, "session_id": session_id},
    )
    return response.json()


def generate_with_approval_start(api_key: str, session_id: str, instruction: str) -> str:
    """Starts an async job with human review. Returns job_id, or None
    if the call itself failed."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(
        f"{SUPERDOCS_API_BASE}/chat/async",
        headers=headers,
        json={"message": instruction, "session_id": session_id, "approval_mode": "ask_every_time"},
    )
    if response.status_code != 200:
        return None
    return response.json().get("job_id")


def poll_job(api_key: str, job_id: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(f"{SUPERDOCS_API_BASE}/jobs/{job_id}", headers=headers)
    return response.json()


def submit_approval_decision(api_key: str, session_id: str, job_id: str, decisions: list) -> dict:
    """decisions: list of {"change_id": ..., "approved": bool}.
    job_id is REQUIRED in the body - undocumented, found via a real
    422 error during testing."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if len(decisions) == 1:
        body = {"job_id": job_id, "approved": decisions[0]["approved"]}
    else:
        body = {"job_id": job_id, "changes": decisions}
    response = requests.post(f"{SUPERDOCS_API_BASE}/chat/{session_id}/approve", headers=headers, json=body)
    return response.json()


def export_document(api_key: str, session_id: str, format_type: str) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(
        f"{SUPERDOCS_API_BASE}/documents/export",
        headers=headers,
        json={"session_id": session_id, "format": format_type, "options": {"paper_size": "Letter", "margins": "normal"}},
    )
    if response.status_code != 200:
        return None
    return response.content