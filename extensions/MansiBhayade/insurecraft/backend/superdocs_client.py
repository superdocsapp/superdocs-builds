import requests
from typing import Optional, Dict, Any, List

from .config import SUPERDOCS_API_KEY, SUPERDOCS_BASE_URL


class SuperDocsClient:

    def __init__(self):
        self.base_url = SUPERDOCS_BASE_URL.rstrip("/")

        self.headers = {
            "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
        }

    # =========================================================
    # INTERNAL REQUEST
    # =========================================================

    def _request(
        self,
        method: str,
        path: str,
        **kwargs
    ):

        url = (
            f"{self.base_url}/"
            f"{path.lstrip('/')}"
        )

        headers = kwargs.pop(
            "headers",
            {}
        )

        merged_headers = {
            **self.headers,
            **headers,
        }

        response = requests.request(
            method=method,
            url=url,
            headers=merged_headers,
            timeout=300,
            **kwargs
        )

        if not response.ok:

            print(
                "================================"
            )

            print("SUPERDOCS API ERROR")
            print("Method:", method)
            print("URL:", url)
            print(
                "Status:",
                response.status_code
            )
            print(
                "Body:",
                response.text
            )

            print(
                "================================"
            )

        response.raise_for_status()

        if not response.content:
            return {}

        return response.json()

    # =========================================================
    # GET SESSIONS
    # =========================================================

    def get_sessions(self):

        return self._request(
            "GET",
            "/sessions"
        )

    # =========================================================
    # UPLOAD DOCUMENT
    # =========================================================

    def upload_document(
        self,
        file_path: str
    ):

        with open(
            file_path,
            "rb"
        ) as file:

            filename = (
                file_path
                .replace("\\", "/")
                .split("/")[-1]
            )

            files = {
                "file": (
                    filename,
                    file,
                    "application/octet-stream"
                )
            }

            return self._request(
                "POST",
                "/attachments",
                files=files
            )

    # =========================================================
    # SYNCHRONOUS CHAT
    # =========================================================

    def chat(
        self,
        message: str,
        session_id: str,
        document_html: Optional[str] = None,
        approval_mode: str = "ask_every_time"
    ):

        payload = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }

        if document_html:
            payload["document_html"] = document_html

        print(
            "SUPERDOCS CHAT REQUEST:",
            {
                "session_id": session_id,
                "approval_mode": approval_mode,
                "document_html_length": (
                    len(document_html)
                    if document_html
                    else 0
                )
            }
        )

        return self._request(
            "POST",
            "/chat",
            json=payload,
            headers={
                "Content-Type":
                    "application/json"
            }
        )

    # =========================================================
    # ASYNCHRONOUS CHAT
    # =========================================================

    def chat_async(
        self,
        message: str,
        session_id: str,
        document_html: Optional[str] = None,
        approval_mode: str = "ask_every_time"
    ):

        payload = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }

        if document_html:
            payload["document_html"] = document_html

        print(
            "================================"
        )

        print("SUPERDOCS ASYNC CHAT REQUEST")
        print(
            "Session:",
            session_id
        )
        print(
            "Approval mode:",
            approval_mode
        )
        print(
            "Document HTML length:",
            len(document_html)
            if document_html
            else 0
        )

        print(
            "================================"
        )

        return self._request(
            "POST",
            "/chat/async",
            json=payload,
            headers={
                "Content-Type":
                    "application/json"
            }
        )

    # =========================================================
    # SESSION JOBS
    # =========================================================

    def get_session_jobs(
        self,
        session_id: str
    ):

        return self._request(
            "GET",
            f"/sessions/{session_id}/jobs"
        )

    # =========================================================
    # SINGLE JOB
    # =========================================================

    def get_job(
        self,
        job_id: str
    ):

        return self._request(
            "GET",
            f"/jobs/{job_id}"
        )

    # =========================================================
    # APPROVE / REJECT CHANGES
    # =========================================================

   # =========================================================
# APPROVE / REJECT CHANGES
# =========================================================

    def approve_changes(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: Optional[List[Dict[str, Any]]] = None
             ):
        payload: Dict[str, Any] = {
            "job_id": job_id,
            "approved": approved,
        }

        if changes:
            payload["changes"] = changes

        print("================================")
        print("SUPERDOCS APPROVAL REQUEST")
        print("Session:", session_id)
        print("Job:", job_id)
        print("Approved:", approved)
        print("Changes:", changes)
        print("Payload:", payload)
        print("================================")

        result = self._request(
            "POST",
            f"/chat/{session_id}/approve",
            json=payload,
            headers={
                "Content-Type": "application/json"
            }
        )

        print("================================")
        print("SUPERDOCS APPROVAL RESPONSE")
        print(result)
        print("================================")

        return result

    # =========================================================
    # EXPORT DOCUMENT
    # =========================================================

    def export_document(
        self,
        session_id: str,
        document_id: Optional[str] = None
    ):

        payload: Dict[str, Any] = {}

        if document_id:
            payload["document_id"] = (
                document_id
            )

        print(
            "Exporting SuperDocs session:",
            session_id
        )

        return self._request(
            "POST",
            f"/documents/{session_id}/export",
            json=payload,
            headers={
                "Content-Type":
                    "application/json"
            }
        )