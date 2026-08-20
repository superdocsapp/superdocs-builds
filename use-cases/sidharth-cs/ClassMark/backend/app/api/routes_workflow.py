"""Workflow routes: start a review on a submission, drive it through the
native-HITL loop, attach, return, verify. One route per state transition —
the orchestrator guards each transition's preconditions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.routes_auth import require_auth
from app.workflow.orchestrator import (
    DEFAULT_REVIEW_INSTRUCTION,
    create_workflow,
    get_workflow,
)
from app.workflow.review_config import ReviewConfiguration

router = APIRouter()


class StartWorkflowRequest(BaseModel):
    course_id: str
    course_name: str = ""
    coursework_id: str
    assignment_title: str = ""
    submission_id: str


class DecideRequest(BaseModel):
    chunk_id: str
    decision: str  # "approved" | "rejected"


class ReviewRequest(ReviewConfiguration):
    pass


def _token_provider(request: Request):
    async def provider() -> str:
        return await require_auth(request)

    return provider


def _workflow_or_404(request: Request, workflow_id: str):
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(404, f"no workflow with id {workflow_id}")
    return workflow


@router.get("/api/workflow/recommended-instruction")
async def recommended_instruction():
    """The builder-derived default for API consumers and compatibility.

    The React UI no longer composes or sends instructions; it sends only the
    semantic review configuration to the backend, preventing instruction
    drift from reintroducing annotation-contaminated replacements.
    """
    return {"instruction": DEFAULT_REVIEW_INSTRUCTION}


@router.post("/api/workflow/start")
async def start_workflow(body: StartWorkflowRequest, request: Request):
    token = await require_auth(request)
    _ = token  # presence check; provider refreshes per call
    workflow = create_workflow(
        course_id=body.course_id,
        course_name=body.course_name,
        coursework_id=body.coursework_id,
        assignment_title=body.assignment_title,
        submission_id=body.submission_id,
        classroom=request.app.state.classroom_client,
        drive=request.app.state.drive_client,
        superdocs=request.app.state.superdocs_client,
        access_token_provider=_token_provider(request),
        owner_session_id=request.session.get("session_id", ""),
    )
    data = await workflow.retrieve_submission()
    return data.model_dump()


@router.post("/api/workflow/{workflow_id}/upload")
async def upload_to_superdocs(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.upload_to_superdocs()).model_dump()


@router.post("/api/workflow/{workflow_id}/review")
async def start_review(workflow_id: str, body: ReviewRequest, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.start_review(body)).model_dump()


@router.post("/api/workflow/{workflow_id}/decide")
async def decide(workflow_id: str, body: DecideRequest, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.decide(body.chunk_id, body.decision)).model_dump()


@router.post("/api/workflow/{workflow_id}/submit-approval")
async def submit_approval(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.submit_approval()).model_dump()


@router.post("/api/workflow/{workflow_id}/export")
async def export_reviewed(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.export_reviewed()).model_dump()


@router.post("/api/workflow/{workflow_id}/upload-drive")
async def upload_to_drive(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.upload_to_drive()).model_dump()


@router.post("/api/workflow/{workflow_id}/attach")
async def attach(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.attach_to_submission()).model_dump()


@router.post("/api/workflow/{workflow_id}/return")
async def return_submission(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.return_submission()).model_dump()


@router.post("/api/workflow/{workflow_id}/verify")
async def verify(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    return (await workflow.verify()).model_dump()


@router.get("/api/workflow/{workflow_id}/state")
async def workflow_state(workflow_id: str, request: Request):
    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    # Workflow state is bound to the session that created it — another
    # authenticated session must not read it (User B must never see
    # User A's Classroom submission workflow).
    if workflow.data.owner_session_id != request.session.get("session_id", ""):
        raise HTTPException(403, "this workflow belongs to another session")
    return workflow.data.model_dump()


@router.get("/api/workflow/{workflow_id}/export/download")
async def download_export(workflow_id: str, request: Request):
    """The exact SuperDocs-exported DOCX bytes, downloadable only:
    - by an authenticated session
    - that owns this workflow (no cross-workflow artifact access)
    - once export genuinely completed (never before, never while blocked)"""
    from fastapi import Response

    await require_auth(request)
    workflow = _workflow_or_404(request, workflow_id)
    if workflow.data.owner_session_id != request.session.get("session_id", ""):
        raise HTTPException(403, "this workflow belongs to another session")
    artifact = workflow.export_bytes()
    if artifact is None:
        raise HTTPException(
            409,
            "reviewed document is not available for download yet — "
            "export must complete first (native SuperDocs approval required)",
        )
    bytes_, filename = artifact
    return Response(
        content=bytes_,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
