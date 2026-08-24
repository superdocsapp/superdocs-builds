import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

MCP_URL = os.getenv("SUPERDOCS_MCP_URL", "https://api.superdocs.app/mcp")
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".md", ".txt", ".rtf", ".html", ".htm", ".tex", ".zip"}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_EXPORT_BYTES = 100 * 1024 * 1024
INLINE_FILE_BYTES = 100 * 1024
SESSION_PATTERN = re.compile(r"^promotion_[A-Za-z0-9_-]{16,80}$")
_SESSION_ARTIFACTS: dict[str, tuple[str, ...]] = {}
_GROUNDED_SESSIONS: set[str] = set()
_SESSION_ACTIVE_JOBS: dict[str, str] = {}
_REVIEWED_JOBS: set[tuple[str, str]] = set()
_IDEMPOTENCY: dict[tuple[str, str], tuple[str, dict[str, Any] | None]] = {}
_IDEMPOTENCY_LOCK = asyncio.Lock()
_TERMINAL_JOB_STATES = {"complete", "completed", "succeeded", "success"}


def _allowed_signed_url_hosts() -> tuple[str, ...]:
    configured = os.getenv(
        "SUPERDOCS_SIGNED_URL_HOSTS",
        "api.superdocs.app,superdocs.app,amazonaws.com,cloudfront.net",
    )
    return tuple(
        host.strip().casefold().lstrip(".")
        for host in configured.split(",")
        if host.strip()
    )


def validate_signed_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    allowed = _allowed_signed_url_hosts()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not any(host == item or host.endswith("." + item) for item in allowed)
    ):
        raise HTTPException(502, "SuperDocs returned a signed URL outside the configured hosts")
    return url


def require_local_session(session_id: str) -> None:
    if session_id not in _SESSION_ARTIFACTS:
        raise HTTPException(404, "Unknown or expired local session")


def verify_job_owner(job: Mapping[str, Any], session_id: str, job_id: str) -> None:
    if str(job.get("session_id", "")) != session_id:
        raise HTTPException(409, "Provider job does not belong to this session")
    returned_job_id = job.get("job_id") or job.get("id")
    if returned_job_id is not None and str(returned_job_id) != job_id:
        raise HTTPException(409, "Provider returned a different job")


class McpClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not MCP_URL.startswith("https://"):
            raise HTTPException(500, "SUPERDOCS_MCP_URL must use HTTPS")
        key = os.getenv("SUPERDOCS_API_KEY", "").strip()
        if not key:
            raise HTTPException(503, "SUPERDOCS_API_KEY is not configured")
        if key.lower().startswith("bearer "):
            raise HTTPException(500, "Configure the raw key without the Bearer prefix")
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=False,
            transport=transport,
        )
        self._ids = iter(range(1, 1_000_000))

    async def __aenter__(self) -> "McpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not name.replace("_", "").isalnum():
            raise HTTPException(500, "Invalid MCP tool name")
        try:
            response = await self._client.post(
                MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": next(self._ids),
                    "method": "tools/call",
                    "params": {"name": name, "arguments": dict(arguments)},
                },
            )
            response.raise_for_status()
            envelope = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise HTTPException(503, "SuperDocs MCP request failed; retry safely") from exc
        result = envelope.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            raise HTTPException(502, "SuperDocs MCP tool returned an error")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    parsed = json.loads(str(item.get("text", "")))
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        raise HTTPException(502, "SuperDocs MCP returned no structured result")


async def provider() -> AsyncIterator[McpClient]:
    async with McpClient() as client:
        yield client


async def open_download(url: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    validate_signed_url(url)
    client = httpx.AsyncClient(follow_redirects=False, timeout=60)
    try:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > MAX_EXPORT_BYTES:
            raise HTTPException(502, "Provider export exceeds the configured size limit")
    except Exception:
        await client.aclose()
        raise
    return client, response


async def stream_download(
    client: httpx.AsyncClient, response: httpx.Response
) -> AsyncIterator[bytes]:
    received = 0
    try:
        async for chunk in response.aiter_bytes(64 * 1024):
            received += len(chunk)
            if received > MAX_EXPORT_BYTES:
                raise HTTPException(502, "Provider export exceeds the configured size limit")
            yield chunk
    finally:
        await response.aclose()
        await client.aclose()


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_PATTERN.pattern)
    instruction: str = Field(min_length=10, max_length=2_000)
    model_tier: Literal["core", "turbo", "pro", "max"] = "pro"
    template_name: str | None = Field(default=None, max_length=255)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_PATTERN.pattern)
    query: str = Field(min_length=3, max_length=500)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: str = Field(min_length=1, max_length=200)
    approved: bool
    feedback: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def require_feedback(self) -> "Decision":
        if not self.approved and (self.feedback is None or len(self.feedback.strip()) < 3):
            raise ValueError("rejected changes require feedback")
        return self


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_PATTERN.pattern)
    job_id: str = Field(min_length=1, max_length=200)
    changes: list[Decision] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_decisions(self) -> "ReviewRequest":
        ids = [item.change_id for item in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("each change must be decided exactly once")
        return self


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(pattern=SESSION_PATTERN.pattern)
    format: Literal["docx", "pdf"] = "docx"


async def read_file(file: UploadFile) -> tuple[str, bytes]:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type: {filename}")
    content = await file.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File must be 1-{MAX_FILE_BYTES} bytes: {filename}")
    return filename, content


async def file_size(file: UploadFile) -> int:
    if file.size is not None:
        return int(file.size)
    await file.seek(0)
    size = 0
    while chunk := await file.read(64 * 1024):
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            break
    await file.seek(0)
    return size


async def file_sha256(file: UploadFile) -> str:
    digest = hashlib.sha256()
    await file.seek(0)
    while chunk := await file.read(64 * 1024):
        digest.update(chunk)
    await file.seek(0)
    return digest.hexdigest()


async def stream_to_signed_url(url: str, file: UploadFile, content_type: str) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        await file.seek(0)
        while chunk := await file.read(64 * 1024):
            yield chunk

    async with httpx.AsyncClient(follow_redirects=False, timeout=120) as client:
        response = await client.put(
            url,
            headers={"Content-Type": content_type},
            content=chunks(),
        )
        response.raise_for_status()


async def upload_provider_file(
    *,
    client: McpClient,
    file: UploadFile,
    session_id: str,
    parse_mode: Literal["document", "attachment"],
) -> tuple[str, dict[str, Any]]:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type: {filename}")
    size = await file_size(file)
    if not 0 < size <= MAX_FILE_BYTES:
        raise HTTPException(413, f"File must be 1-{MAX_FILE_BYTES} bytes: {filename}")
    if size <= INLINE_FILE_BYTES:
        _, content = await read_file(file)
        tool = (
            "upload_document_base64"
            if parse_mode == "document"
            else "upload_attachment_base64"
        )
        return filename, await client.call(
            tool,
            {
                "filename": filename,
                "file_base64": base64.b64encode(content).decode("ascii"),
                "session_id": session_id,
                "return_html": False,
            },
        )
    content_type = file.content_type or "application/octet-stream"
    reservation = await client.call(
        "request_upload_url",
        {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size,
            "purpose": parse_mode,
        },
    )
    upload_url = reservation.get("upload_url")
    upload_id = reservation.get("upload_id")
    if not isinstance(upload_url, str) or not upload_url.startswith("https://"):
        raise HTTPException(502, "SuperDocs returned no secure upload URL")
    if not isinstance(upload_id, str) or not upload_id:
        raise HTTPException(502, "SuperDocs returned no upload identifier")
    await stream_to_signed_url(validate_signed_url(upload_url), file, content_type)
    return filename, await client.call(
        "process_uploaded_document",
        {
            "upload_id": upload_id,
            "session_id": session_id,
            "filename": filename,
            "parse_mode": parse_mode,
            "return_html": False,
        },
    )


async def idempotency_begin(
    operation: str, key: str, digest: str
) -> dict[str, Any] | None:
    async with _IDEMPOTENCY_LOCK:
        existing = _IDEMPOTENCY.get((operation, key))
        if existing is None:
            _IDEMPOTENCY[(operation, key)] = (digest, None)
            return None
        previous_digest, result = existing
        if previous_digest != digest:
            raise HTTPException(409, "Idempotency key was reused with a different request")
        if result is None:
            raise HTTPException(409, "The same operation is already in progress")
        return dict(result)


async def idempotency_complete(
    operation: str, key: str, digest: str, result: dict[str, Any]
) -> None:
    async with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY[(operation, key)] = (digest, dict(result))


async def idempotency_release(operation: str, key: str) -> None:
    async with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY.pop((operation, key), None)


def request_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def pending_changes(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    direct = job.get("pending_changes")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]
    metadata = job.get("metadata")
    if not isinstance(metadata, dict):
        return []
    nested = metadata.get("pending_changes")
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    responses = metadata.get("intermediate_responses")
    if not isinstance(responses, list):
        return []
    for item in reversed(responses):
        if not isinstance(item, dict):
            continue
        content: object = item.get("content")
        for _ in range(2):
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    break
        if isinstance(content, dict) and isinstance(content.get("changes"), list):
            return [change for change in content["changes"] if isinstance(change, dict)]
    return []


def normalize_job(job: dict[str, Any], artifacts: tuple[str, ...]) -> dict[str, Any]:
    changes = []
    for change in pending_changes(job):
        citations: list[str] = []
        citation_details: list[dict[str, str]] = []
        explicit = change.get("citations") or change.get("sources")
        if isinstance(explicit, list):
            for citation in explicit:
                if isinstance(citation, dict):
                    filename = citation.get("filename") or citation.get("artifact_name")
                    quote = citation.get("quote") or citation.get("excerpt")
                    if (
                        isinstance(filename, str)
                        and filename in artifacts
                        and isinstance(quote, str)
                        and len(quote.strip()) >= 3
                    ):
                        citations.append(filename)
                        citation_details.append(
                            {"filename": filename, "quote": quote.strip()[:1_000]}
                        )
        normalized = dict(change)
        normalized["citation_artifacts"] = sorted(set(citations))
        normalized["citation_details"] = citation_details
        normalized["citation_valid"] = bool(citation_details)
        changes.append(normalized)
    result = dict(job)
    result["normalized_changes"] = changes
    result["all_changes_grounded"] = all(
        change["citation_valid"] for change in changes
    ) if changes else True
    return result


def update_export_readiness(session_id: str, job_id: str, job: Mapping[str, Any]) -> bool:
    normalized_changes = job.get("normalized_changes")
    has_changes = isinstance(normalized_changes, list) and bool(normalized_changes)
    status = str(job.get("status", "")).casefold()
    ready = (
        (session_id, job_id) in _REVIEWED_JOBS
        and status in _TERMINAL_JOB_STATES
        and not has_changes
    )
    if ready:
        _GROUNDED_SESSIONS.add(session_id)
    else:
        _GROUNDED_SESSIONS.discard(session_id)
    return ready


app = FastAPI(title="Promotion Packet Builder", version="1.0.0")
STATIC = Path(__file__).parent / "static"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": "backend-only MCP"}


@app.post("/api/upload")
async def upload_corpus(
    primary: Annotated[UploadFile, File()],
    evidence: Annotated[list[UploadFile], File()],
    client: Annotated[McpClient, Depends(provider)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
    save_template: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    if len(evidence) > 20:
        raise HTTPException(413, "At most 20 evidence attachments are allowed")
    digest = request_digest(
        {
            "primary": [Path(primary.filename or "").name, await file_sha256(primary)],
            "evidence": [
                [Path(file.filename or "").name, await file_sha256(file)] for file in evidence
            ],
            "save_template": save_template,
        }
    )
    if replay := await idempotency_begin("upload", idempotency_key, digest):
        return replay
    try:
        session_id = "promotion_" + secrets.token_urlsafe(18).replace("-", "_")
        primary_name, _ = await upload_provider_file(
            client=client,
            file=primary,
            session_id=session_id,
            parse_mode="document",
        )
        if save_template:
            if await file_size(primary) > INLINE_FILE_BYTES:
                raise HTTPException(
                    413,
                    "Reusable templates are limited to 100KB in this demo; "
                    "the active document still supports presigned uploads up to 100MB.",
                )
            await primary.seek(0)
            _, primary_content = await read_file(primary)
            await client.call(
                "upload_template_base64",
                {
                    "filename": primary_name,
                    "file_base64": base64.b64encode(primary_content).decode("ascii"),
                },
            )
        attachment_names = []
        for file in evidence:
            filename, _ = await upload_provider_file(
                client=client,
                file=file,
                session_id=session_id,
                parse_mode="attachment",
            )
            attachment_names.append(filename)
        _SESSION_ARTIFACTS[session_id] = tuple(attachment_names)
        _GROUNDED_SESSIONS.discard(session_id)
        result = {
            "session_id": session_id,
            "primary_filename": primary_name,
            "attachment_count": len(attachment_names),
            "artifact_names": attachment_names,
            "template_saved": save_template,
            "large_file_path": (
                "presigned" if await file_size(primary) > INLINE_FILE_BYTES else "inline"
            ),
        }
        await idempotency_complete("upload", idempotency_key, digest, result)
        return result
    except Exception:
        await idempotency_release("upload", idempotency_key)
        raise


@app.get("/api/templates")
async def templates(client: Annotated[McpClient, Depends(provider)]) -> dict[str, Any]:
    return await client.call("list_user_templates", {})


@app.post("/api/search")
async def search(
    request: SearchRequest,
    client: Annotated[McpClient, Depends(provider)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
) -> dict[str, Any]:
    require_local_session(request.session_id)
    digest = request_digest(request.model_dump(mode="json"))
    if replay := await idempotency_begin("search", idempotency_key, digest):
        return replay
    try:
        result = await client.call(
            "chat",
            {
                "session_id": request.session_id,
                "message": (
                    "Search only the uploaded evidence attachments. Do not edit the document. "
                    "Return matching exact quotes and artifact filenames for: " + request.query
                ),
                "approval_mode": "ask_every_time",
                "cross_session_memory": False,
                "cross_session_search": False,
            },
        )
        await idempotency_complete("search", idempotency_key, digest, result)
        return result
    except Exception:
        await idempotency_release("search", idempotency_key)
        raise


@app.post("/api/edit")
async def edit(
    request: EditRequest,
    client: Annotated[McpClient, Depends(provider)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
) -> dict[str, Any]:
    require_local_session(request.session_id)
    digest = request_digest(request.model_dump(mode="json"))
    if replay := await idempotency_begin("edit", idempotency_key, digest):
        return replay
    instruction = (
        "Use only facts supported by the supplied evidence attachments. Preserve source/citation "
        "references, surface gaps or conflicts instead of inventing facts, and make targeted "
        "edits.\n\n"
        + request.instruction
    )
    if request.template_name:
        instruction = (
            f"Use the saved template named {request.template_name!r} as the structural guide.\n"
            + instruction
        )
    try:
        result = await client.call(
            "chat_async",
            {
                "session_id": request.session_id,
                "message": instruction,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
                "model_tier": request.model_tier,
                "thinking_depth": "balanced",
                "cross_session_memory": False,
                "cross_session_search": False,
            },
        )
        job_id = result.get("job_id") or result.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise HTTPException(502, "SuperDocs returned no job identifier")
        _SESSION_ACTIVE_JOBS[request.session_id] = job_id
        _REVIEWED_JOBS.discard((request.session_id, job_id))
        _GROUNDED_SESSIONS.discard(request.session_id)
        await idempotency_complete("edit", idempotency_key, digest, result)
        return result
    except Exception:
        await idempotency_release("edit", idempotency_key)
        raise


@app.get("/api/jobs/{job_id}")
async def job(
    job_id: str,
    client: Annotated[McpClient, Depends(provider)],
    session_id: Annotated[str, Query(pattern=SESSION_PATTERN.pattern)],
) -> dict[str, Any]:
    require_local_session(session_id)
    if _SESSION_ACTIVE_JOBS.get(session_id) != job_id:
        raise HTTPException(409, "Job is not the active edit for this session")
    result = await client.call("get_job", {"job_id": job_id, "compact": False})
    verify_job_owner(result, session_id, job_id)
    normalized = normalize_job(result, _SESSION_ARTIFACTS[session_id])
    normalized["export_ready"] = update_export_readiness(session_id, job_id, normalized)
    return normalized


@app.post("/api/review")
async def review(
    request: ReviewRequest,
    client: Annotated[McpClient, Depends(provider)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
) -> dict[str, Any]:
    require_local_session(request.session_id)
    if _SESSION_ACTIVE_JOBS.get(request.session_id) != request.job_id:
        raise HTTPException(409, "Job is not the active edit for this session")
    digest = request_digest(request.model_dump(mode="json"))
    if replay := await idempotency_begin("review", idempotency_key, digest):
        return replay
    try:
        job_result = await client.call(
            "get_job", {"job_id": request.job_id, "compact": False}
        )
        verify_job_owner(job_result, request.session_id, request.job_id)
        normalized = normalize_job(
            job_result, _SESSION_ARTIFACTS.get(request.session_id, ())
        )
        by_id = {
            str(change.get("change_id")): change
            for change in normalized["normalized_changes"]
        }
        decision_ids = {decision.change_id for decision in request.changes}
        if decision_ids != set(by_id):
            raise HTTPException(
                409,
                "Every current proposed change must receive exactly one decision.",
            )
        for decision in request.changes:
            change = by_id.get(decision.change_id)
            if change is None:
                raise HTTPException(409, f"Unknown or stale change: {decision.change_id}")
            if decision.approved and not change["citation_valid"]:
                raise HTTPException(
                    409,
                    f"Approved change {decision.change_id} has no resolvable source artifact.",
                )
        result = await client.call(
            "approve_change",
            {
                "session_id": request.session_id,
                "job_id": request.job_id,
                "approved": any(item.approved for item in request.changes),
                "changes": [item.model_dump(exclude_none=True) for item in request.changes],
            },
        )
        _REVIEWED_JOBS.add((request.session_id, request.job_id))
        refreshed = await client.call(
            "get_job", {"job_id": request.job_id, "compact": False}
        )
        verify_job_owner(refreshed, request.session_id, request.job_id)
        normalized_after = normalize_job(
            refreshed, _SESSION_ARTIFACTS[request.session_id]
        )
        export_ready = update_export_readiness(
            request.session_id, request.job_id, normalized_after
        )
        response = {
            "provider_result": result,
            "job": normalized_after,
            "export_ready": export_ready,
        }
        await idempotency_complete("review", idempotency_key, digest, response)
        return response
    except Exception:
        await idempotency_release("review", idempotency_key)
        raise


@app.post("/api/export")
async def export(
    request: ExportRequest,
    client: Annotated[McpClient, Depends(provider)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
) -> StreamingResponse:
    require_local_session(request.session_id)
    active_job = _SESSION_ACTIVE_JOBS.get(request.session_id)
    if active_job is None or (request.session_id, active_job) not in _REVIEWED_JOBS:
        raise HTTPException(409, "A fully grounded explicit review is required before export")
    current = await client.call("get_job", {"job_id": active_job, "compact": False})
    verify_job_owner(current, request.session_id, active_job)
    normalized_current = normalize_job(current, _SESSION_ARTIFACTS[request.session_id])
    if not update_export_readiness(request.session_id, active_job, normalized_current):
        raise HTTPException(
            409,
            "The reviewed job is not terminal or has a revised change round awaiting review",
        )
    digest = request_digest(request.model_dump(mode="json"))
    result = await idempotency_begin("export", idempotency_key, digest)
    if result is None:
        try:
            result = await client.call(
                "export_document",
                {
                    "session_id": request.session_id,
                    "format": request.format,
                    "options": {"filename": "promotion-packet", "fidelity": "strict"},
                },
            )
            await idempotency_complete("export", idempotency_key, digest, result)
        except Exception:
            await idempotency_release("export", idempotency_key)
            raise
    url = result.get("download_url")
    if not isinstance(url, str):
        raise HTTPException(502, "SuperDocs returned no secure export URL")
    download_client, response = await open_download(validate_signed_url(url))
    media = "application/pdf" if request.format == "pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return StreamingResponse(
        stream_download(download_client, response),
        media_type=media,
        headers={
            "Content-Disposition": (
                f'attachment; filename="promotion-packet.{request.format}"'
            )
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)
