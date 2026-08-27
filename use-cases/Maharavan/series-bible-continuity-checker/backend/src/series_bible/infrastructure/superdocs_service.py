"""Typed boundary to the real connected SuperDocs MCP server."""
from __future__ import annotations
import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any, Literal
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

class SuperDocsServiceError(RuntimeError):
    pass

class SuperDocsConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mcp_url: str = "https://api.superdocs.app/mcp"
    mcp_api_key: SecretStr
    timeout_seconds: float = Field(default=60, gt=0, le=300)

class UploadDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1)
    session_id: str | None = Field(default=None, max_length=256)
    return_html: bool = False

class EditInstructionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=100_000)
    document_id: str | None = Field(default=None, max_length=256)
    cursor_context: dict[str, Any] | None = None
    response_mode: Literal["full", "compact"] = "compact"
    model_tier: str | None = None
    thinking_depth: str | None = None

class ApproveChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    job_id: str = Field(min_length=1, max_length=256)
    change_id: str | None = Field(default=None, max_length=256)
    approved: bool
    feedback: str | None = Field(default=None, max_length=10_000)

class ExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_size: Literal["A4", "Letter", "A3", "Legal"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    margins: Literal["narrow", "normal", "wide", "custom"] | None = None
    custom_margins_inches: dict[Literal["top", "right", "bottom", "left"], float] | None = None
    filename: str | None = Field(default=None, max_length=255)
    embed_images: bool | None = None
    watermark_text: str | None = Field(default=None, max_length=64)
    watermark_opacity: float | None = Field(default=None, ge=0.05, le=1)
    fidelity: Literal["strict", "compat"] | None = None

    @field_validator("custom_margins_inches")
    @classmethod
    def margins_in_range(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value and any(not 0.25 <= margin <= 3 for margin in value.values()):
            raise ValueError("custom margins must be between 0.25 and 3 inches")
        return value

class ExportDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    format: Literal["docx", "pdf", "html", "markdown", "txt", "doc"] = "docx"
    options: ExportOptions | None = None
    source_filename: str | None = Field(default=None, max_length=255)

class EditProposal(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    change_id: str
    original_html: str | None = None
    proposed_html: str | None = None

class SuperDocsService:
    """Calls exact names returned by the live server's tools/list operation."""
    UPLOAD_TOOL = "upload_document_base64"
    EDIT_TOOL = "chat_async"
    APPROVE_TOOL = "approve_change"
    EXPORT_TOOL = "export_document"
    GET_JOB_TOOL = "get_job"

    def __init__(self, connection: SuperDocsConnection) -> None:
        self._connection = connection

    async def upload_document(self, request: UploadDocumentRequest) -> dict[str, Any]:
        return await self._call_tool(self.UPLOAD_TOOL, request.model_dump(exclude_none=True))

    async def send_edit_instruction(self, request: EditInstructionRequest) -> dict[str, Any]:
        arguments = request.model_dump(exclude_none=True)
        arguments["approval_mode"] = "ask_every_time"
        return await self._call_tool(self.EDIT_TOOL, arguments)

    async def approve_change(self, request: ApproveChangeRequest) -> dict[str, Any]:
        return await self._call_tool(self.APPROVE_TOOL, request.model_dump(exclude_none=True))

    async def export_document(self, request: ExportDocumentRequest) -> dict[str, Any]:
        return await self._call_tool(self.EXPORT_TOOL, request.model_dump(exclude_none=True))

    async def get_job(self, job_id: str, compact: bool = True) -> dict[str, Any]:
        return await self._call_tool(self.GET_JOB_TOOL, {"job_id": job_id, "compact": compact})

    async def wait_for_edit_proposal(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 90,
        poll_seconds: float = 1,
    ) -> EditProposal:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            result = await self.get_job(job_id, compact=False)
            status = str(result.get("status", "")).lower()
            if status in {"failed", "cancelled", "canceled"}:
                raise SuperDocsServiceError("SuperDocs edit job did not complete")
            changes = result.get("pending_changes")
            if not isinstance(changes, list):
                metadata = result.get("metadata")
                changes = metadata.get("pending_changes") if isinstance(metadata, dict) else None
            if status in {"awaiting_approval", "completed"} and isinstance(changes, list) and changes:
                change = changes[0]
                if not isinstance(change, dict) or not change.get("change_id"):
                    raise SuperDocsServiceError("SuperDocs returned an invalid proposed change")
                return EditProposal(
                    job_id=job_id,
                    change_id=str(change["change_id"]),
                    original_html=change.get("original_html") or change.get("before_html"),
                    proposed_html=change.get("proposed_html") or change.get("after_html"),
                )
            await asyncio.sleep(poll_seconds)
        raise SuperDocsServiceError("Timed out waiting for the SuperDocs edit proposal")

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._connection.mcp_api_key.get_secret_value()}"}
        for attempt in range(3):
            try:
                async with AsyncExitStack() as stack:
                    client = await stack.enter_async_context(httpx.AsyncClient(headers=headers, timeout=self._connection.timeout_seconds))
                    read, write, _ = await stack.enter_async_context(streamable_http_client(self._connection.mcp_url, http_client=client))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                break
            except Exception as error:
                # SuperDocs can temporarily return 5xx responses while parsing
                # larger PDFs. Re-establish the MCP session before failing.
                message = str(error)
                transient = any(value in message for value in (" 502 ", " 503 ", " 504 ", "All connection attempts failed", "unhandled errors in a TaskGroup"))
                if attempt < 2 and transient:
                    await asyncio.sleep(2 ** attempt)
                    continue
                details = [message.strip()]
                for item in getattr(error, "exceptions", ()):
                    nested_message = str(item).strip()
                    if nested_message:
                        details.append(nested_message)
                detail = "; ".join(dict.fromkeys(value for value in details if value)) or type(error).__name__
                raise SuperDocsServiceError(f"SuperDocs MCP operation failed: {detail[:500]}") from error
        if result.isError:
            text = "; ".join(getattr(item, "text", "") for item in result.content)
            raise SuperDocsServiceError(text or "SuperDocs MCP tool returned an error")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
        return {"content": [item.model_dump(mode="json") for item in result.content]}
