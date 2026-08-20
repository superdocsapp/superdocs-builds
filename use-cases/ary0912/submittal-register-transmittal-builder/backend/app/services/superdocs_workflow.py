from app.superdocs.client import (
    SuperDocsClient,
)


class SuperDocsWorkflow:

    def __init__(
        self,
        client: SuperDocsClient,
    ) -> None:

        self.client = client

    async def create_transmittal_document(
        self,
        filename: str,
        html: str,
    ) -> dict:

        return await self.client.upload_document(
            filename,
            html.encode("utf-8"),
        )

    async def request_edit(
        self,
        session_id: str,
        html: str,
        message: str,
    ) -> dict:

        if not session_id:
            raise ValueError("A SuperDocs session_id is required.")

        result = await self.client.edit_document(
            session_id=session_id,
            message=message,
            document_html=html,
            approval_mode="ask_every_time",
        )

        if not result.get("job_id"):
            raise RuntimeError(
                "SuperDocs edit did not return a job_id."
            )

        return result

    async def get_job(self, job_id: str) -> dict:
        if not job_id:
            raise ValueError("A SuperDocs job_id is required.")

        return await self.client.get_job(job_id)

    async def approve(
        self,
        session_id: str,
        job_id: str,
        change_id: str | None,
        approved: bool,
    ) -> dict:

        if not session_id:
            raise ValueError("A SuperDocs session_id is required.")
        if not job_id:
            raise ValueError("A SuperDocs job_id is required.")

        return await self.client.approve_change(
            session_id=session_id,
            job_id=job_id,
            change_id=change_id,
            approved=approved,
        )

    async def export(
        self,
        session_id: str,
        html: str | None = None,
        format: str = "docx",
        filename: str = "transmittal",
    ) -> dict:

        if not session_id:
            raise ValueError("A SuperDocs session_id is required.")

        return await self.client.export_document(
            session_id=session_id,
            format=format,
            html=html,
            filename=filename,
        )
