"""Deterministic stand-in for SuperDocsClient — mirrors Task 1's FakeLLMClient pattern
so handler/service tests never need a live SuperDocs key. Records calls it received so
tests can assert on what would have been sent, not just what came back."""


class FakeSuperDocsClient:
    def __init__(self, *args, **kwargs):
        self.approve_calls = []
        self.export_calls = []
        self.chat_calls = []
        self.upload_calls = []
        self.get_job_status = "completed"
        self.get_job_pending_changes = []
        self.fail_approve = False  # set True to simulate approve_change raising
        self.fail_get_job_for: set[str] = set()  # job_ids for which get_job raises
        self.fail_chat_with_session_busy = False  # set True to simulate chat_async's 409

    def upload_document(self, session_id, filename, content):
        self.upload_calls.append((session_id, filename, content))
        return {"document_id": "doc_primary", "durable_document_id": "dc-fake", "title": filename}

    def chat_async(self, session_id, message, document_id=None, approval_mode="ask_every_time"):
        if self.fail_chat_with_session_busy:
            from app.services.superdocs_client import SessionBusyError

            raise SessionBusyError("simulated session busy")
        self.chat_calls.append((session_id, message, document_id, approval_mode))
        job_id = f"job_fake_{len(self.chat_calls)}"
        return {"job_id": job_id, "session_id": session_id, "status": "pending", "message": "queued"}

    def get_job(self, job_id):
        if job_id in self.fail_get_job_for:
            raise RuntimeError(f"simulated SuperDocs failure for {job_id}")
        return {
            "job_id": job_id,
            "status": self.get_job_status,
            "metadata": {"pending_changes": self.get_job_pending_changes},
        }

    def approve_change(self, session_id, job_id, approved, change_id=None):
        if self.fail_approve:
            raise RuntimeError("simulated SuperDocs failure")
        self.approve_calls.append((session_id, job_id, approved, change_id))
        return {}

    def export_document(self, session_id, format="docx"):
        self.export_calls.append((session_id, format))
        return {"filename": f"export.{format}", "content": b"fake-file-bytes", "content_type": "application/octet-stream"}

    def list_documents(self, limit=50, offset=0):
        return {"documents": []}

    def close(self):
        pass
