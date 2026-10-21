from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from urllib.parse import quote

from routes.errors import failure
from routes.superdocs_common import provider_json, superdocs_failure
from schemas.declare import ApplyRequest, ApproveRequest, ExportRequest, UploadRequest
from utils.review import review_issues
from utils.statements import render_statements, render_statements_html
from utils.superdocs import SuperDocsError, declaration_instruction, provider_request

router = APIRouter(prefix="/api/superdocs")

@router.post("/upload")
async def upload(input_: UploadRequest):
    try:
        response = await provider_request(
            "POST",
            "/v1/documents/upload-base64",
            {
                "session_id": input_.sessionId,
                "filename": input_.filename,
                "file_base64": input_.fileBase64,
                "return_html": input_.returnHtml,
            },
        )
        return {"success": True, "data": provider_json(response), "error": None}
    except SuperDocsError as error:
        return superdocs_failure(error, "SUPERDOCS_UPLOAD_FAILED")


@router.post("/apply")
async def apply(input_: ApplyRequest):
    issues = review_issues(input_.facts)
    if issues:
        return failure(422, "REVIEW_REQUIRED", issues)
    try:
        html = render_statements_html(render_statements(input_.facts))
        payload = {
            "session_id": input_.sessionId,
            "message": declaration_instruction(html),
            "approval_mode": input_.approvalMode,
        }
        if input_.documentHtml is not None:
            payload["document_html"] = input_.documentHtml
        response = await provider_request("POST", "/v1/chat/async", payload)
        provider = provider_json(response)
        if not isinstance(provider, dict) or not isinstance(provider.get("job_id"), str):
            raise SuperDocsError("missing job id")
        return {
            "success": True,
            "data": {
                "job_id": provider["job_id"],
                "session_id": input_.sessionId,
                "status": "pending",
            },
            "error": None,
        }
    except SuperDocsError as error:
        return superdocs_failure(error, "SUPERDOCS_APPLY_FAILED")
    except Exception:
        return failure(502, "SUPERDOCS_APPLY_FAILED")


@router.get("/jobs/{job_id}")
async def job(job_id: str):
    if not job_id.strip():
        return failure(400, "MISSING_JOB_ID")
    try:
        response = await provider_request("GET", f"/v1/jobs/{quote(job_id, safe='')}")
        return {"success": True, "data": provider_json(response), "error": None}
    except SuperDocsError as error:
        return superdocs_failure(error, "SUPERDOCS_JOB_LOOKUP_FAILED")


@router.post("/approve")
async def approve(input_: ApproveRequest):
    if not input_.jobId:
        return failure(400, "MISSING_JOB_ID")
    try:
        payload = {"job_id": input_.jobId, "approved": input_.approved}
        if input_.feedback is not None:
            payload["feedback"] = input_.feedback
        if input_.changes is not None:
            payload["changes"] = [
                {
                    "change_id": change.changeId,
                    "approved": change.approved,
                    **({"feedback": change.feedback} if change.feedback is not None else {}),
                }
                for change in input_.changes
            ]
        response = await provider_request(
            "POST",
            f"/v1/chat/{quote(input_.sessionId, safe='')}/approve",
            payload,
        )
        return {"success": True, "data": provider_json(response), "error": None}
    except SuperDocsError as error:
        return superdocs_failure(error, "SUPERDOCS_APPROVE_FAILED")


@router.post("/export")
async def export(input_: ExportRequest):
    try:
        payload = {"format": input_.format}
        if input_.sessionId is not None:
            payload["session_id"] = input_.sessionId
        if input_.documentHtml is not None:
            payload["html"] = input_.documentHtml
        if input_.filename is not None:
            payload["filename"] = input_.filename
        response = await provider_request("POST", "/v1/documents/export", payload)
        content_type = response.headers.get("content-type", "")
        if "json" in content_type.casefold():
            return {"success": True, "data": provider_json(response), "error": None}
        return Response(content=response.content, media_type=content_type or "application/octet-stream")
    except SuperDocsError as error:
        return superdocs_failure(error, "SUPERDOCS_EXPORT_FAILED")
