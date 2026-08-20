import httpx
import uuid
from app.config import SUPERDOCS_API_KEY, SUPERDOCS_BASE_URL


class SuperDocsClient:
    def __init__(self):
        self.base_url = SUPERDOCS_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
        }

    async def list_sessions(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/sessions",
                headers=self.headers,
            )

        response.raise_for_status()
        return response.json()

    async def create_upload(
    self,
    filename: str,
    content_type: str,
    size_bytes: int,
):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/uploads",
                headers=self.headers,
                json={
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
            )
        print(response)
        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs returned {response.status_code}: {response.text}"
            )

        return response.json()
    async def upload_file_to_storage(
    self,
    upload_url: str,
    file_bytes: bytes,
    content_type: str,
):
        async with httpx.AsyncClient() as client:
            response = await client.put(
                upload_url,
                content=file_bytes,
                headers={
                    "Content-Type": content_type,
                },
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"File upload failed: "
                f"{response.status_code} {response.text}"
            )

        return True
    async def process_upload(
        self,
        upload_id: str,
        session_id: str,
        filename: str,
        open_mode: str = "new_focused",
    ):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/uploads/{upload_id}/process",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json={
                    "session_id": session_id,
                    "filename": filename,
                    "parse_mode": "document",
                    "return_html": True,
                    "open_mode": open_mode,
                },
            )

        print("========== PROCESS UPLOAD ==========")
        print("FILENAME:", filename)
        print("OPEN MODE:", open_mode)
        print("PROCESS STATUS:", response.status_code)
        print("PROCESS RESPONSE:", repr(response.text))

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs processing failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()
    async def create_session(self):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/chat",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json={
                    "message": "Create a document session.",
                    "session_id": f"task2-{uuid.uuid4()}",
                },
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs session creation failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    async def chat(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "approve_all",
        document_id: str | None = None,
    ):
        payload = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }

        if document_html is not None:
            payload["document_html"] = document_html

        if document_id is not None:
            payload["document_id"] = document_id

        print("========== CHAT DEBUG ==========")
        print("PAYLOAD:", payload)
        print("URL:", f"{self.base_url}/v1/chat")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat",
                    headers={
                        **self.headers,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            print("STATUS:", response.status_code)
            print("RESPONSE:", repr(response.text))

            return {
                "superdocs_status": response.status_code,
                "superdocs_response": response.text,
            }

        except Exception as error:
            print("========== CHAT EXCEPTION ==========")
            print("TYPE:", type(error).__name__)
            print("ERROR:", repr(error))
            print("====================================")

            raise
    
    async def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        document_id: str | None = None,
    ):
        payload = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }

        if document_html:
            payload["document_html"] = document_html

        if document_id:
            payload["document_id"] = document_id

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/async",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs async chat failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    async def approve_change(
        self,
    session_id: str,
    job_id: str,
    change_id: str,
    approved: bool,
    feedback: str | None = None,
    ):
        payload = {
            "job_id": job_id,
            "approved": approved,
            "change_id": change_id,
            "feedback": feedback,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/{session_id}/approve",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs approval failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()
    async def get_job(self, job_id: str):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/jobs/{job_id}",
                headers=self.headers,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs job status failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    async def cancel_job(self, job_id: str):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/jobs/{job_id}/cancel",
                headers=self.headers,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs cancel job failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()
    async def list_jobs(
        self,
        status: str | None = None,
        limit: int = 50,
        compact: bool = False,
    ):
        params = {
            "limit": limit,
            "compact": compact,
        }

        if status:
            params["status"] = status

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/jobs",
                headers=self.headers,
                params=params,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs list jobs failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()
    async def post(
        self,
        path: str,
        json: dict,
    ):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}{path}",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=json,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs POST failed: "
                f"{response.status_code} {response.text}"
            )

        return response.json()
    async def export_document( 
        self,
        session_id: str,
        export_format: str,
        document_id: str | None = None,
    ):
        payload = {
            "session_id": session_id,
            "format": export_format,
        }

        if document_id:
            payload["document_id"] = document_id

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/export",
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"SuperDocs export failed: "
                f"{response.status_code} {response.text}"
            )

        return {
            "content": response.content,
            "content_type": response.headers.get(
                "content-type",
                "application/octet-stream",
            ),
            "filename": response.headers.get(
                "content-disposition"
            ),
        }
    async def approve_all(
        self,
        session_id: str,
        job_id: str,
        changes: list,
    ):
        payload = {
            "job_id": job_id,
            "approved": True,
            "changes": [
                {
                    "change_id": change["change_id"],
                    "approved": True,
                }
                for change in changes
            ],
        }

        return await superdocs_client.post(
            f"/v1/chat/{session_id}/approve",
            json=payload,
        )
superdocs_client = SuperDocsClient()