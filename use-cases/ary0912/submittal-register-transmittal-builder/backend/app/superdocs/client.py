from typing import Protocol


class SuperDocsClient(Protocol):

    async def upload_document(
        self,
        filename: str,
        content: bytes,
    ) -> dict:
        ...

    async def edit_document(
        self,
        session_id: str,
        message: str,
        document_html: str,
        approval_mode: str = "ask_every_time",
    ) -> dict:
        ...

    async def get_job(
        self,
        job_id: str,
    ) -> dict:
        ...

    async def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: str | None,
        approved: bool,
    ) -> dict:
        ...

    async def export_document(
        self,
        session_id: str,
        format: str = "docx",
        html: str | None = None,
        filename: str | None = None,
    ) -> dict:
        ...
