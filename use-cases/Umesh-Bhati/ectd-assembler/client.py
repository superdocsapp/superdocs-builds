import os
import time
import uuid
import requests
from requests.exceptions import RequestException

API_BASE_URL = "https://api.superdocs.app/v1"
WEB_APP_BASE_URL = "https://use.superdocs.app"

TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


class JobFailedError(RuntimeError):
    pass


class JobTimeoutError(TimeoutError):
    pass


def session_url(session_id: str) -> str:
    return f"{WEB_APP_BASE_URL}/sessions/{session_id}"


class SuperDocsClient:
    def __init__(self, base_url: str = API_BASE_URL, api_key: str | None = None):
        self.api_key = (
            api_key if api_key is not None else os.environ.get("SUPERDOCS_API_KEY")
        )
        self.base_url = base_url

    @property
    def auth_headers(self) -> dict:
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY environment variable is missing")
        return {"Authorization": f"Bearer {self.api_key}"}

    def _json_headers(self) -> dict:
        return {**self.auth_headers, "Content-Type": "application/json"}

    def _post_file(self, endpoint: str, filepath: str, extra_data: dict | None = None) -> dict:
        headers = self.auth_headers
        with open(filepath, "rb") as f:
            files = {"file": (os.path.basename(filepath), f)}
            response = requests.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                files=files,
                data=extra_data or {},
            )
            response.raise_for_status()
        return response.json()

    def verify_connection(self) -> bool:
        headers = self.auth_headers
        try:
            response = requests.get(f"{self.base_url}/sessions", headers=headers, timeout=30)
            return response.status_code == 200
        except RequestException:
            return False

    def upload_document(self, filepath: str, session_id: str | None = None) -> dict:
        session_id = session_id or str(uuid.uuid4())
        res = self._post_file(
            "/documents/upload?index=true",
            filepath,
            extra_data={"session_id": session_id},
        )
        return {
            "session_id": session_id,
            "document_id": res.get("document_id"),
            "filename": res.get("filename"),
            "chunks_count": res.get("chunks_count"),
        }

    def upload_attachment(self, session_id: str, filepath: str) -> str:
        res = self._post_file(
            "/attachments/upload",
            filepath,
            extra_data={"session_id": session_id},
        )
        job_id = res.get("job_id")
        if not job_id:
            raise ValueError(f"Attachment upload did not return a job_id for {filepath}")
        return job_id

    def get_job(self, job_id: str) -> dict:
        headers = self.auth_headers
        response = requests.get(f"{self.base_url}/jobs/{job_id}", headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_job_status(self, job_id: str) -> str:
        return self.get_job(job_id).get("status", "unknown")

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        stop_on_awaiting_approval: bool = True,
    ) -> dict:
        start = time.time()
        while True:
            job = self.get_job(job_id)
            status = job.get("status", "unknown")

            if status in TERMINAL_JOB_STATUSES:
                if status == "failed":
                    raise JobFailedError(job.get("error") or f"Job {job_id} failed")
                return job

            if stop_on_awaiting_approval and status == "awaiting_approval":
                return job

            if time.time() - start > max_wait:
                raise JobTimeoutError(f"Job {job_id} did not finish within {max_wait}s")

            time.sleep(poll_interval)

    def upload_attachment_and_wait(self, session_id: str, filepath: str) -> dict:
        job_id = self.upload_attachment(session_id, filepath)
        return self.wait_for_job(job_id, stop_on_awaiting_approval=False)

    def chat_async(
        self,
        session_id: str,
        prompt: str,
        *,
        approval_mode: str = "ask_every_time",
    ) -> str:
        payload = {
            "session_id": session_id,
            "message": prompt,
            "approval_mode": approval_mode,
        }
        response = requests.post(
            f"{self.base_url}/chat/async",
            headers=self._json_headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        job_id = response.json().get("job_id")
        if not job_id:
            raise ValueError("chat/async did not return a job_id")
        return job_id

    def approve_changes(
        self,
        session_id: str,
        job_id: str,
        pending_changes: list,
        *,
        approved: bool = True,
    ) -> None:
        payload = {
            "job_id": job_id,
            "approved": approved,
            "changes": [
                {"change_id": change["change_id"], "approved": approved}
                for change in pending_changes
            ],
        }
        response = requests.post(
            f"{self.base_url}/chat/{session_id}/approve",
            headers=self._json_headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def continue_job(self, session_id: str, job_id: str, *, continue_editing: bool = True) -> None:
        payload = {"job_id": job_id, "continue": continue_editing}
        response = requests.post(
            f"{self.base_url}/chat/{session_id}/continue",
            headers=self._json_headers(),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def resolve_job(
        self,
        session_id: str,
        job_id: str,
        *,
        browser_review: bool = False,
    ) -> dict:
        while True:
            job = self.wait_for_job(job_id)
            status = job.get("status")

            if status == "completed":
                return job

            metadata = job.get("metadata") or {}
            awaiting_kind = metadata.get("awaiting_kind")

            if awaiting_kind == "continue_prompt":
                prompt = metadata.get("continue_prompt") or {}
                print(f"  Large edit paused: {prompt.get('message', 'Continue?')}")
                self.continue_job(session_id, job_id, continue_editing=True)
                continue

            pending_changes = metadata.get("pending_changes") or []
            if pending_changes:
                self._handle_pending_changes(
                    session_id, job_id, pending_changes, browser_review=browser_review
                )
                continue

            raise JobFailedError(f"Job {job_id} paused with unhandled awaiting_approval state")

    def _handle_pending_changes(
        self,
        session_id: str,
        job_id: str,
        pending_changes: list,
        *,
        browser_review: bool,
    ) -> None:
        print(f"\n  {len(pending_changes)} proposed change(s) awaiting review:")
        for change in pending_changes:
            explanation = change.get("ai_explanation") or change.get("operation") or "Proposed edit"
            print(f"    - {explanation}")

        print(f"\n  Review session: {session_url(session_id)}")
        if browser_review:
            print("  Tip: if the document looks stale, refresh the browser tab to sync API changes.")

        if browser_review:
            input("  Press Enter after approving changes in the SuperDocs web UI...")
            return

        self.approve_changes(session_id, job_id, pending_changes, approved=True)
        print("  Approved all proposed changes via API.")

    def export_document(self, session_id: str, output_path: str) -> str:
        payload = {"session_id": session_id, "format": "docx"}
        response = requests.post(
            f"{self.base_url}/documents/export",
            headers=self._json_headers(),
            json=payload,
            timeout=120,
        )
        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

        return output_path

    def bootstrap_session(
        self,
        shell_path: str,
        attachment_paths: list[str],
        *,
        session_id: str | None = None,
    ) -> dict:
        doc_res = self.upload_document(shell_path, session_id=session_id)
        session_id = doc_res["session_id"]
        attachments = {}

        for path in attachment_paths:
            filename = os.path.basename(path)
            print(f"Uploading attachment: {path}...")
            job = self.upload_attachment_and_wait(session_id, path)
            attachments[path] = {
                "filename": filename,
                "job_id": job.get("job_id"),
            }
            print(f"  Attachment ready: {filename}")

        return {
            "session_id": session_id,
            "document_id": doc_res.get("document_id"),
            "attachments": attachments,
            "session_url": session_url(session_id),
        }
