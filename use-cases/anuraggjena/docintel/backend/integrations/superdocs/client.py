"""
SuperDocs MCP Client.

Wraps SuperDocs MCP tools with error handling, retries, and type safety.
"""

import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from backend.logging_config import get_logger
from backend.config import settings

logger = get_logger(__name__)


class JobStatus(str, Enum):
    """SuperDocs job status values."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class UploadURLResult:
    """Result from request_upload_url."""
    upload_id: str
    upload_url: str
    curl_example: str


@dataclass
class ProcessResult:
    """Result from process_uploaded_document."""
    document_id: str
    chunks_count: int
    version_id: str


@dataclass
class Session:
    """SuperDocs session."""
    session_id: str
    document_ids: List[str]


@dataclass
class Job:
    """SuperDocs async job."""
    job_id: str
    session_id: str
    status: JobStatus


@dataclass
class JobStatusResult:
    """Detailed job status."""
    job_id: str
    status: JobStatus
    progress: Optional[float]
    result: Optional[Dict[str, Any]]
    pending_changes: List[Dict[str, Any]]
    error: Optional[str]
    awaiting_kind: Optional[str] = None  # 'changes' | 'continue_prompt' | None


@dataclass
class ApprovalResult:
    """Result from approve_change."""
    change_id: str
    approved: bool
    job_status: JobStatus


@dataclass
class ExportResult:
    """Result from export_document."""
    download_url: str
    format: str
    filename: str


class SuperDocsError(Exception):
    """Base exception for SuperDocs client errors."""
    pass


class SuperDocsConnectionError(SuperDocsError):
    """Connection error to SuperDocs API."""
    pass


class SuperDocsTimeoutError(SuperDocsError):
    """SuperDocs API timeout."""
    pass


class SuperDocsAPIError(SuperDocsError):
    """SuperDocs API returned an error."""
    pass


class SuperDocsClient:
    """
    Client for SuperDocs MCP API.

    Wraps MCP tools with error handling, retries, and type safety.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize SuperDocs client.

        Args:
            api_key: SuperDocs API key (defaults to settings.superdocs_api_key)
        """
        self.api_key = api_key or settings.superdocs_api_key
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds

    async def _call_mcp_tool(
        self,
        tool_name: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call SuperDocs MCP tool with error handling.

        Args:
            tool_name: Name of MCP tool (e.g., "mcp__superdocs__init_session")
            **kwargs: Tool parameters

        Returns:
            Tool result

        Raises:
            SuperDocsConnectionError: Connection failed
            SuperDocsTimeoutError: Request timed out
            SuperDocsAPIError: API returned error
        """
        # Add authorization if not provided
        if "authorization" not in kwargs:
            kwargs["authorization"] = self.api_key

        for attempt in range(self.max_retries):
            try:
                logger.info(
                    "calling_superdocs_mcp_tool",
                    tool=tool_name,
                    attempt=attempt + 1
                )

                # Import the MCP tool invoker
                from backend.integrations.superdocs.mcp_invoker import invoke_mcp_tool

                # Call the MCP tool
                result = await invoke_mcp_tool(tool_name, **kwargs)

                logger.info(
                    "superdocs_mcp_tool_success",
                    tool=tool_name,
                    attempt=attempt + 1
                )

                return result

            except TimeoutError as exc:
                if attempt == self.max_retries - 1:
                    logger.error("superdocs_timeout", tool=tool_name, error=str(exc))
                    raise SuperDocsTimeoutError(
                        f"SuperDocs API timeout after {self.max_retries} attempts"
                    ) from exc

                await asyncio.sleep(self.retry_delay * (2 ** attempt))

            except ConnectionError as exc:
                if attempt == self.max_retries - 1:
                    logger.error("superdocs_connection_error", tool=tool_name, error=str(exc))
                    raise SuperDocsConnectionError(
                        f"Failed to connect to SuperDocs API"
                    ) from exc

                await asyncio.sleep(self.retry_delay * (2 ** attempt))

            except Exception as exc:
                # Check if this is a SuperDocs API error response
                if hasattr(exc, 'response') or 'error' in str(exc).lower():
                    logger.error("superdocs_api_error", tool=tool_name, error=str(exc))
                    raise SuperDocsAPIError(f"SuperDocs API error: {str(exc)}") from exc

                # For other exceptions, retry
                if attempt == self.max_retries - 1:
                    logger.error("superdocs_unexpected_error", tool=tool_name, error=str(exc))
                    raise SuperDocsAPIError(f"Unexpected error calling {tool_name}: {str(exc)}") from exc

                await asyncio.sleep(self.retry_delay * (2 ** attempt))

    async def request_upload_url(
        self,
        filename: str,
        content_type: str,
        size_bytes: int
    ) -> UploadURLResult:
        """
        Request pre-signed upload URL for large files.

        Args:
            filename: Original filename with extension
            content_type: MIME type (e.g., 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            size_bytes: File size in bytes

        Returns:
            UploadURLResult with upload_id, upload_url, and curl_example
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__request_upload_url",
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            purpose="document"
        )

        return UploadURLResult(
            upload_id=result["upload_id"],
            upload_url=result["upload_url"],
            curl_example=result.get("curl_example", "")
        )

    async def upload_document_base64(
        self,
        filename: str,
        file_base64: str,
        session_id: Optional[str] = None
    ) -> ProcessResult:
        """
        Upload document inline via base64 (for files <100KB).

        Args:
            filename: Original filename with extension
            file_base64: Base64-encoded file content
            session_id: Optional session to load document into

        Returns:
            ProcessResult with document_id and metadata
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__upload_document_base64",
            filename=filename,
            file_base64=file_base64,
            session_id=session_id,
            return_html=False  # Compact mode
        )

        # When uploading to a session, the API returns version_id but no document_id
        # The document is implicitly part of the session, so use session_id as the reference
        document_id = result.get("document_id")
        if not document_id and session_id:
            document_id = session_id

        return ProcessResult(
            document_id=document_id or "",
            chunks_count=result.get("chunks_count", 0),
            version_id=result.get("version_id", "")
        )

    async def process_uploaded_document(
        self,
        upload_id: str,
        session_id: str,
        filename: str
    ) -> ProcessResult:
        """
        Process document uploaded via pre-signed URL.

        Args:
            upload_id: ID from request_upload_url
            session_id: Session to load document into
            filename: Original filename

        Returns:
            ProcessResult with document_id and metadata
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__process_uploaded_document",
            upload_id=upload_id,
            session_id=session_id,
            filename=filename,
            parse_mode="document",
            return_html=False  # Compact mode
        )

        return ProcessResult(
            document_id=result["document_id"],
            chunks_count=result.get("chunks_count", 0),
            version_id=result.get("version_id", "")
        )

    async def init_session(
        self,
        document_ids: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> Session:
        """
        Create SuperDocs editing session.

        Args:
            document_ids: Optional list of documents to open
            session_id: Optional client-chosen session ID (will be auto-generated if None)

        Returns:
            Session with session_id and document_ids
        """
        # Generate session_id if not provided (required by SuperDocs MCP)
        if session_id is None:
            import uuid
            session_id = f"session_{uuid.uuid4().hex[:16]}"

        result = await self._call_mcp_tool(
            "mcp__superdocs__init_session",
            document_ids=document_ids,
            session_id=session_id,
            include_html=False  # Compact mode
        )

        return Session(
            session_id=result["session_id"],
            document_ids=result.get("document_ids", [])
        )

    async def chat_async(
        self,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
        response_mode: str = "compact"
    ) -> Job:
        """
        Send async edit instruction to SuperDocs.

        Args:
            session_id: SuperDocs session ID
            message: Natural language instruction
            approval_mode: "ask_every_time" (default) or "approve_all"
            response_mode: "compact" (default) or "full"

        Returns:
            Job with job_id for polling
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__chat_async",
            session_id=session_id,
            message=message,
            approval_mode=approval_mode,
            response_mode=response_mode,
            async_mode=True
        )

        return Job(
            job_id=result["job_id"],
            session_id=session_id,
            status=JobStatus(result.get("status", "pending"))
        )

    async def get_job(
        self,
        job_id: str,
        compact: bool = True
    ) -> JobStatusResult:
        """
        Get job status and results.

        Args:
            job_id: Job ID from chat_async
            compact: If True, omit heavy result body

        Returns:
            JobStatusResult with status, progress, and results
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__get_job",
            job_id=job_id,
            compact=compact
        )

        status = JobStatus(result["status"])
        pending_changes = []

        # Extract pending_changes when awaiting approval.
        # SuperDocs returns pending_changes as a TOP-LEVEL field in the get_job response,
        # NOT nested under "metadata". Also check metadata fallback for compatibility.
        if status == JobStatus.AWAITING_APPROVAL:
            pending_changes = (
                result.get("pending_changes")
                or result.get("metadata", {}).get("pending_changes")
                or []
            )
            # Detect awaiting_kind='continue_prompt' — these have no changes to approve;
            # the job needs continue_chat() instead. Surface as empty pending_changes.
            awaiting_kind = result.get("awaiting_kind") or result.get("metadata", {}).get("awaiting_kind")
            if awaiting_kind == "continue_prompt":
                pending_changes = []

        return JobStatusResult(
            job_id=job_id,
            status=status,
            progress=result.get("progress"),
            result=result.get("result"),
            pending_changes=pending_changes,
            awaiting_kind=result.get("awaiting_kind") or (result.get("metadata") or {}).get("awaiting_kind"),
            error=result.get("error")
        )

    async def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: Optional[str] = None,
        approved: bool = True,
        feedback: Optional[str] = None,
        changes: Optional[List[Dict[str, Any]]] = None,
    ) -> ApprovalResult:
        """
        Approve or reject proposed change(s).

        Supports both:
        - Single change: change_id="...", approved=True/False
        - Batch changes: changes=[{"change_id": "...", "approved": True, ...}], approved=True

        Args:
            session_id: SuperDocs session ID
            job_id: Job ID with pending changes
            change_id: Specific change to approve/reject (optional if changes list provided)
            approved: True to approve, False to reject
            feedback: Optional feedback for rejected changes
            changes: Optional list of batch change decisions

        Returns:
            ApprovalResult with updated job status
        """
        kwargs: Dict[str, Any] = {
            "session_id": session_id,
            "job_id": job_id,
            "approved": approved,
        }
        if change_id is not None:
            kwargs["change_id"] = change_id
        if feedback is not None:
            kwargs["feedback"] = feedback
        if changes is not None:
            kwargs["changes"] = changes

        result = await self._call_mcp_tool(
            "mcp__superdocs__approve_change",
            **kwargs
        )

        resolved_cid = change_id or (changes[0].get("change_id") if changes and isinstance(changes[0], dict) else "")
        status_val = result.get("job_status", "in_progress") if isinstance(result, dict) else "in_progress"

        return ApprovalResult(
            change_id=resolved_cid,
            approved=approved,
            job_status=JobStatus(status_val) if status_val in [s.value for s in JobStatus] else JobStatus.IN_PROGRESS
        )

    async def export_document(
        self,
        session_id: str,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None
    ) -> ExportResult:
        """
        Export document to specified format.

        Args:
            session_id: SuperDocs session ID
            format: Export format ("docx", "pdf", "html", "markdown", "txt")
            options: Optional export options (paper_size, margins, etc.)

        Returns:
            ExportResult with download_url
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__export_document",
            session_id=session_id,
            format=format,
            options=options or {}
        )

        return ExportResult(
            download_url=result["download_url"],
            format=format,
            filename=result.get("filename", f"export.{format}")
        )

    async def request_download_url(
        self,
        session_id: str,
        format: str = "docx",
        filename: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> ExportResult:
        """
        Request pre-signed download URL for export.

        Args:
            session_id: SuperDocs session ID
            format: Export format
            filename: Optional custom filename
            options: Optional export options

        Returns:
            ExportResult with download_url
        """
        result = await self._call_mcp_tool(
            "mcp__superdocs__request_download_url",
            session_id=session_id,
            format=format,
            filename=filename,
            options=options or {}
        )

        return ExportResult(
            download_url=result["download_url"],
            format=format,
            filename=result.get("filename", f"export.{format}")
        )

    async def poll_job_until_complete(
        self,
        job_id: str,
        timeout_seconds: int = 300,
        poll_interval: float = 2.0
    ) -> JobStatusResult:
        """
        Poll job until completed, failed, or cancelled.

        Args:
            job_id: Job ID to poll
            timeout_seconds: Maximum time to wait
            poll_interval: Seconds between polls

        Returns:
            Final JobStatusResult

        Raises:
            SuperDocsTimeoutError: If timeout exceeded
            SuperDocsAPIError: If job failed
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise SuperDocsTimeoutError(
                    f"Job {job_id} did not complete within {timeout_seconds}s"
                )

            status = await self.get_job(job_id, compact=True)

            if status.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                if status.status == JobStatus.FAILED:
                    raise SuperDocsAPIError(
                        f"Job {job_id} failed: {status.error}"
                    )
                return status

            logger.info(
                "polling_superdocs_job",
                job_id=job_id,
                status=status.status.value,
                progress=status.progress
            )

            await asyncio.sleep(poll_interval)
