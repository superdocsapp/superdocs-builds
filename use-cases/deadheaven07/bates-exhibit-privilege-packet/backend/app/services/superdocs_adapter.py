import base64
import json
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.services.superdocs_port import (
    AttachmentUploadResult,
    DocumentUploadResult,
    ExportResult,
    JobStatus,
    PIICategory,
    PIIDetectionResult,
    PIIEntity,
    PrivilegeAnalysisResult,
    PrivilegeCategory,
    ProposedChange,
    ProposedChangeBatch,
    RedactionCandidate,
    SuperDocsPort,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SuperDocsAPIError(Exception):
    def __init__(self, message: str, status_code: int, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class SuperDocsRESTAdapter(SuperDocsPort):
    def __init__(self):
        self.base_url = settings.superdocs_base_url.rstrip("/")
        self.api_key = settings.superdocs_api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _handle_response(self, response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise SuperDocsAPIError(
                f"SuperDocs API error: {response.status_code}",
                response.status_code,
                response.text,
            )
        return dict(response.json())

    async def _ensure_session(self, session_id: str | None) -> str:
        client = await self._get_client()
        payload = {"session_id": session_id} if session_id else {}
        response = await client.post("/v1/sessions/init", json=payload)
        data = self._handle_response(response)
        return str(data.get("session_id", session_id or ""))

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: str | None = None,
        return_html: bool = True,
    ) -> DocumentUploadResult:
        client = await self._get_client()
        file_b64 = base64.b64encode(file_bytes).decode("utf-8")

        if not session_id:
            session_id = await self._ensure_session(None)

        payload = {
            "filename": filename,
            "file_base64": file_b64,
            "return_html": return_html,
            "session_id": session_id,
        }

        response = await client.post("/v1/documents/upload-base64", json=payload)
        data = self._handle_response(response)

        return DocumentUploadResult(
            session_id=data.get("session_id", session_id),
            document_id=data.get("document_id") or data.get("focused_document_id") or "doc_primary",
            chunks_count=data.get("chunks_count", 0),
            version_id=data.get("version_id", ""),
            page_setup=data.get("page_setup", {}),
            html=data.get("html"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def upload_attachment(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: str,
    ) -> AttachmentUploadResult:
        client = await self._get_client()
        file_b64 = base64.b64encode(file_bytes).decode("utf-8")

        payload = {
            "filename": filename,
            "file_base64": file_b64,
            "session_id": session_id,
        }

        response = await client.post("/v1/attachments/upload-base64", json=payload)
        data = self._handle_response(response)

        return AttachmentUploadResult(
            job_id=data.get("job_id", ""),
            filename=data.get("filename", filename),
            status=data.get("status", "processing"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def poll_job(self, job_id: str) -> JobStatus:
        client = await self._get_client()

        response = await client.get(f"/v1/jobs/{job_id}")
        data = self._handle_response(response)

        return JobStatus(
            job_id=data.get("job_id", job_id),
            status=data.get("status", "unknown"),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def chat_async(
        self,
        message: str,
        session_id: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> str:
        client = await self._get_client()

        payload = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
        }
        if document_html:
            payload["document_html"] = document_html

        response = await client.post("/v1/chat/async", json=payload)
        data = self._handle_response(response)

        return str(data.get("job_id", ""))

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def approve_changes(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[dict],
        feedback: str | None = None,
    ) -> JobStatus:
        client = await self._get_client()

        payload = {
            "job_id": job_id,
            "approved": approved,
            "changes": changes,
        }
        if feedback:
            payload["feedback"] = feedback

        response = await client.post(f"/v1/chat/{session_id}/approve", json=payload)
        data = self._handle_response(response)

        return JobStatus(
            job_id=data.get("job_id", job_id),
            status=data.get("status", "unknown"),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def continue_job(
        self,
        session_id: str,
        job_id: str,
        continue_job: bool,
    ) -> JobStatus:
        client = await self._get_client()

        payload = {
            "job_id": job_id,
            "continue": continue_job,
        }

        response = await client.post(f"/v1/chat/{session_id}/continue", json=payload)
        data = self._handle_response(response)

        return JobStatus(
            job_id=data.get("job_id", job_id),
            status=data.get("status", "unknown"),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def export_document(
        self,
        session_id: str,
        format: str = "pdf",
        options: dict | None = None,
    ) -> ExportResult:
        client = await self._get_client()

        payload: dict[str, object] = {
            "session_id": session_id,
            "format": format,
        }
        if options:
            payload["options"] = options

        response = await client.post("/v1/documents/export", json=payload)
        data = self._handle_response(response)

        return ExportResult(
            download_url=data.get("download_url", ""),
            filename=data.get("filename", f"export.{format}"),
            format=format,
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get_session_history(self, session_id: str) -> dict:
        client = await self._get_client()

        response = await client.get(f"/v1/sessions/{session_id}/history")
        return self._handle_response(response)

    def parse_proposed_change_batch(self, content: str) -> ProposedChangeBatch:
        try:
            outer = json.loads(content)
            if "content" not in outer:
                raise ValueError("Missing 'content' field in proposed_change_batch")
            inner_content = outer.get("content", "{}")
            batch_data = json.loads(inner_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse proposed_change_batch: {e}")
            logger.error(f"Content: {content[:500]}")
            raise ValueError(f"Invalid proposed_change_batch format: {e}") from e

        changes = []
        for change_data in batch_data.get("changes", []):
            changes.append(
                ProposedChange(
                    change_id=change_data.get("change_id", ""),
                    operation=change_data.get("operation", ""),
                    chunk_id=change_data.get("chunk_id"),
                    old_html=change_data.get("old_html"),
                    new_html=change_data.get("new_html"),
                    ai_explanation=change_data.get("ai_explanation", ""),
                    insert_after_chunk_id=change_data.get("insert_after_chunk_id"),
                    document_id=change_data.get("document_id"),
                )
            )

        return ProposedChangeBatch(
            batch_id=batch_data.get("batch_id", ""),
            batch_total=batch_data.get("batch_total", len(changes)),
            changes=changes,
            awaiting_kind=batch_data.get("awaiting_kind", "approval"),
            continue_prompt=batch_data.get("continue_prompt"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def detect_pii(
        self,
        session_id: str,
        document_id: str,
        categories: list["PIICategory"] | None = None,
    ) -> "PIIDetectionResult":
        client = await self._get_client()

        payload: dict[str, object] = {
            "session_id": session_id,
            "document_id": document_id,
        }
        if categories:
            payload["categories"] = [c.value for c in categories]

        response = await client.post("/v1/analysis/detect-pii", json=payload)
        data = self._handle_response(response)

        entities = []
        for entity_data in data.get("entities", []):
            entities.append(
                PIIEntity(
                    category=PIICategory(entity_data.get("category", "other")),
                    text=entity_data.get("text", ""),
                    page_number=entity_data.get("page_number", 1),
                    start_offset=entity_data.get("start_offset", 0),
                    end_offset=entity_data.get("end_offset", 0),
                    confidence=entity_data.get("confidence", 1.0),
                    context_before=entity_data.get("context_before", ""),
                    context_after=entity_data.get("context_after", ""),
                )
            )

        return PIIDetectionResult(
            entities=entities,
            total_count=data.get("total_count", len(entities)),
            session_id=session_id,
            document_id=document_id,
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def analyze_privilege(
        self,
        session_id: str,
        document_id: str,
    ) -> "PrivilegeAnalysisResult":
        client = await self._get_client()

        payload = {
            "session_id": session_id,
            "document_id": document_id,
        }

        response = await client.post("/v1/analysis/privilege", json=payload)
        data = self._handle_response(response)

        category = data.get("category")
        if category:
            category = PrivilegeCategory(category)

        return PrivilegeAnalysisResult(
            is_privileged=data.get("is_privileged", False),
            category=category,
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.0),
            key_phrases=data.get("key_phrases", []),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def apply_redactions(
        self,
        session_id: str,
        document_id: str,
        candidates: list["RedactionCandidate"],
    ) -> JobStatus:
        client = await self._get_client()

        payload = {
            "session_id": session_id,
            "document_id": document_id,
            "candidates": [
                {
                    "entity": {
                        "category": c.entity.category.value,
                        "text": c.entity.text,
                        "page_number": c.entity.page_number,
                        "start_offset": c.entity.start_offset,
                        "end_offset": c.entity.end_offset,
                        "confidence": c.entity.confidence,
                        "context_before": c.entity.context_before,
                        "context_after": c.entity.context_after,
                    },
                    "approved": c.approved,
                    "approved_by": c.approved_by,
                    "approved_at": c.approved_at,
                }
                for c in candidates
            ],
        }

        response = await client.post("/v1/redactions/apply", json=payload)
        data = self._handle_response(response)

        return JobStatus(
            job_id=data.get("job_id", ""),
            status=data.get("status", "unknown"),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def get_redaction_preview(
        self,
        session_id: str,
        document_id: str,
        candidates: list["RedactionCandidate"],
    ) -> ExportResult:
        client = await self._get_client()

        payload = {
            "session_id": session_id,
            "document_id": document_id,
            "candidates": [
                {
                    "entity": {
                        "category": c.entity.category.value,
                        "text": c.entity.text,
                        "page_number": c.entity.page_number,
                        "start_offset": c.entity.start_offset,
                        "end_offset": c.entity.end_offset,
                        "confidence": c.entity.confidence,
                        "context_before": c.entity.context_before,
                        "context_after": c.entity.context_after,
                    },
                    "approved": c.approved,
                    "approved_by": c.approved_by,
                    "approved_at": c.approved_at,
                }
                for c in candidates
            ],
        }

        response = await client.post("/v1/redactions/preview", json=payload)
        data = self._handle_response(response)

        return ExportResult(
            download_url=data.get("download_url", ""),
            filename=data.get("filename", "redaction_preview.pdf"),
            format="pdf",
        )
