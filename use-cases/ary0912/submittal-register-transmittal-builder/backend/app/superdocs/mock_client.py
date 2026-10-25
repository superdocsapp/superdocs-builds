import uuid


class MockSuperDocsClient:

    def __init__(self) -> None:

        self.documents: dict[
            str,
            str,
        ] = {}

        self.jobs: dict[
            str,
            dict,
        ] = {}

        self._job_polls: dict[str, int] = {}

    async def upload_document(
        self,
        filename: str,
        content: bytes,
    ) -> dict:

        session_id = (
            f"mock-{uuid.uuid4()}"
        )

        html = content.decode(
            "utf-8"
        )

        self.documents[
            session_id
        ] = html

        return {
            "session_id": session_id,
            "filename": filename,
            "document_html": html,
        }

    async def edit_document(
        self,
        session_id: str,
        message: str,
        document_html: str,
        approval_mode: str = (
            "ask_every_time"
        ),
    ) -> dict:

        job_id = str(
            uuid.uuid4()
        )

        change_id = str(
            uuid.uuid4()
        )

        proposed_html = (
            document_html
            + (
                "<p "
                'data-chunk-id="mock-added">'
                "SuperDocs proposed edit."
                "</p>"
            )
        )

        self.jobs[job_id] = {
            "session_id": session_id,
            "change_id": change_id,
            "old_html": document_html,
            "new_html": proposed_html,
            "message": message,
            "status": "processing",
            "proposed_changes": [],
        }

        return {
            "session_id": session_id,
            "job_id": job_id,
            "status": "processing",
        }

    async def get_job(
        self,
        job_id: str,
    ) -> dict:

        if job_id not in self.jobs:
            raise KeyError(f"Mock SuperDocs job '{job_id}' not found.")

        job = self.jobs[job_id]
        polls = self._job_polls.get(job_id, 0) + 1
        self._job_polls[job_id] = polls

        if polls >= 1:
            job["status"] = "completed"
            job["proposed_changes"] = [
                {
                    "change_id": job["change_id"],
                    "operation": "edit",
                    "chunk_id": "mock-added",
                    "old_html": job["old_html"],
                    "new_html": job["new_html"],
                    "ai_explanation": job["message"],
                }
            ]

        return {
            "job_id": job_id,
            "session_id": job["session_id"],
            "status": job["status"],
            "proposed_changes": job["proposed_changes"],
        }

    async def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: str | None,
        approved: bool,
    ) -> dict:

        if job_id not in self.jobs:
            raise KeyError(f"Mock SuperDocs job '{job_id}' not found.")

        job = self.jobs[job_id]

        if job["session_id"] != session_id:
            raise ValueError("Mock SuperDocs session does not match job.")

        if job["status"] != "completed":
            raise ValueError("Mock SuperDocs job is not ready for approval.")

        if approved:

            self.documents[
                session_id
            ] = job["new_html"]

            job["status"] = (
                "completed"
            )

        else:

            job["status"] = (
                "completed"
            )

        return {
            "session_id": session_id,
            "job_id": job_id,
            "change_id": change_id,
            "approved": approved,
            "status": job["status"],
            "document_html": (
                self.documents.get(
                    session_id,
                    job["old_html"],
                )
            ),
        }

    async def export_document(
        self,
        session_id: str,
        format: str = "docx",
        html: str | None = None,
        filename: str | None = None,
    ) -> dict:

        return {
            "session_id": session_id,
            "format": format,
            "filename": filename,
            "document_html": (
                html
                or self.documents.get(
                    session_id,
                    "",
                )
            ),
            "download_url": f"mock://transmittal.{format}",
        }
