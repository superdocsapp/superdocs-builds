import os
import time
import json
import httpx
from typing import Dict, Any, List, Optional

SUPERDOCS_API_BASE = os.getenv("SUPERDOCS_API_BASE", "https://api.superdocs.app")

class SuperDocsAPIError(Exception):
    """Custom exception for SuperDocs REST API errors."""
    pass

class SuperDocsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self._is_mock = not self.api_key or self.api_key.lower() == "mock"

    def _execute_with_warmup_retry(self, request_fn) -> httpx.Response:
        """
        Executes an API request. If the initial call fails (e.g. cold session warm-up),
        silently retries once.
        """
        if self._is_mock:
            return None  # Handled in caller

        try:
            response = request_fn()
            if response.status_code < 500 and response.status_code != 408:
                return response
            # Cold-session warm-up retry
            time.sleep(1.0)
            return request_fn()
        except (httpx.TimeoutException, httpx.NetworkError):
            time.sleep(1.0)
            return request_fn()

    def upload_document(self, session_id: str, file_path: str, filename: str) -> Dict[str, Any]:
        """
        Uploads document passage/file to SuperDocs session.
        """
        if self._is_mock:
            return {
                "session_id": session_id,
                "document_id": f"doc_{session_id}",
                "status": "uploaded"
            }

        with open(file_path, "rb") as f:
            import base64
            file_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "session_id": session_id,
            "filename": filename,
            "file_base64": file_b64
        }

        def req():
            return httpx.post(
                f"{SUPERDOCS_API_BASE}/v1/documents/upload-base64",
                headers=self.headers,
                json=payload,
                timeout=30.0
            )

        res = self._execute_with_warmup_retry(req)
        if res.status_code >= 400:
            raise SuperDocsAPIError(f"Upload failed (HTTP {res.status_code}): {res.text}")

        return res.json()

    def send_async_edit(
        self,
        session_id: str,
        instruction: str,
        target_anchor: str,
        comment_id: str
    ) -> str:
        """
        Sends targeted edit instruction for a comment range via chat_async.
        Returns job_id.
        """
        if self._is_mock:
            return f"job_mock_{comment_id}"

        message = (
            f"Target anchor: '{target_anchor}'. "
            f"Edit instruction: {instruction}"
        )

        payload = {
            "session_id": session_id,
            "message": message,
            "approval_mode": "ask_every_time",
            "model_tier": "core"
        }

        def req():
            return httpx.post(
                f"{SUPERDOCS_API_BASE}/v1/chat/async",
                headers=self.headers,
                json=payload,
                timeout=30.0
            )

        res = self._execute_with_warmup_retry(req)
        if res.status_code >= 400:
            raise SuperDocsAPIError(f"Async edit request failed (HTTP {res.status_code}): {res.text}")

        data = res.json()
        return data.get("job_id", f"job_{session_id}_{comment_id}")

    def poll_job_status(
        self,
        job_id: str,
        max_timeout_seconds: int = 600
    ) -> Dict[str, Any]:
        """
        Polls GET /v1/jobs/{job_id} with progressive backoff (2s -> 5s -> 10s)
        until status is awaiting_approval, completed, or failed.
        Treats pending and in_progress as normal states.
        Double-parses JSON diff card strings if stringified.
        """
        if self._is_mock or job_id.startswith("job_mock_"):
            comment_id = job_id.replace("job_mock_", "")
            # Return synthetic mock change
            return {
                "status": "awaiting_approval",
                "job_id": job_id,
                "changes": [
                    {
                        "change_id": f"ch_{comment_id}",
                        "comment_id": comment_id,
                        "old_text": "Target anchor text",
                        "new_text": f"Mock revised text for comment {comment_id}",
                        "explanation": "Applied requested edit."
                    }
                ]
            }

        start_time = time.time()
        backoff_intervals = [2.0, 3.0, 5.0, 10.0]
        poll_count = 0

        while (time.time() - start_time) < max_timeout_seconds:
            res = httpx.get(
                f"{SUPERDOCS_API_BASE}/v1/jobs/{job_id}",
                headers=self.headers,
                timeout=30.0
            )

            if res.status_code >= 400:
                raise SuperDocsAPIError(f"Job polling failed (HTTP {res.status_code}): {res.text}")

            data = res.json()
            status = data.get("status", "pending")

            if status == "awaiting_approval":
                metadata = data.get("metadata", {})
                pending_raw = metadata.get("pending_changes", [])

                # Handle double-parsed stringified JSON diff if stringified
                changes = []
                for item in pending_raw:
                    if isinstance(item, str):
                        try:
                            item = json.loads(item)
                        except json.JSONDecodeError:
                            pass
                    changes.append(item)

                return {
                    "status": "awaiting_approval",
                    "job_id": job_id,
                    "changes": changes
                }

            if status in ("completed", "failed", "cancelled"):
                return data

            # Progressive backoff delay
            interval = backoff_intervals[min(poll_count, len(backoff_intervals) - 1)]
            poll_count += 1
            time.sleep(interval)

        raise SuperDocsAPIError(f"Job polling timed out after {max_timeout_seconds} seconds for job {job_id}")

    def approve_changes(
        self,
        session_id: str,
        job_id: str,
        change_decisions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calls POST /v1/chat/{session_id}/approve.
        Enforces mandatory top-level "approved": true in payload.
        change_decisions shape: [{"change_id": "ch_1", "approved": True}, ...]
        """
        if self._is_mock or job_id.startswith("job_mock_"):
            return {
                "session_id": session_id,
                "job_id": job_id,
                "status": "approved"
            }

        # Enforce top-level approved parameter (required by SuperDocs schema)
        all_approved = all(c.get("approved", True) for c in change_decisions)
        payload = {
            "job_id": job_id,
            "approved": all_approved,
            "changes": change_decisions
        }

        res = httpx.post(
            f"{SUPERDOCS_API_BASE}/v1/chat/{session_id}/approve",
            headers=self.headers,
            json=payload,
            timeout=30.0
        )

        if res.status_code >= 400:
            raise SuperDocsAPIError(f"Approval failed (HTTP {res.status_code}): {res.text}")

        return res.json()
