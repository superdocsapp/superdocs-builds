from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from docrelay.api.dependencies import machine_operations
from docrelay.core.config import Settings
from docrelay.domain.enums import ConflictChoice, WriteAuthorizationState
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.persistence.database import Database
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    GoogleBaselineCapture,
)
from docrelay.services.machine import RunSummary
from docrelay.services.superdocs_workflow import (
    DecisionInput,
    ExportNotReady,
    ExportView,
    ProposalView,
    RunView,
    SelectedBaselineChanged,
    SourceNotFound,
    SuperDocsBaseline,
    SuperDocsNotConfigured,
    SuperDocsWorkflow,
)
from docrelay.services.write_planning import DryRunView
from docrelay.services.writeback import WriteBackView

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class RunAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartRunRequest(RunAPIModel):
    source_id: UUID
    baseline_capture_id: UUID
    instruction: str = Field(min_length=1, max_length=20_000)
    model_tier: Literal["core", "turbo", "pro", "max"] | None = None
    thinking_depth: Literal["fast", "balanced", "deep"] | None = None


class DecisionRequest(RunAPIModel):
    proposal_id: UUID
    approve: bool
    feedback: str | None = Field(default=None, max_length=10_000)


class SubmitDecisionsRequest(RunAPIModel):
    decisions: tuple[DecisionRequest, ...] = Field(min_length=1)


class ContinueRequest(RunAPIModel):
    should_continue: bool


class ResumeRequest(RunAPIModel):
    allow_definitive_retry: bool = False


class ProposalsResponse(RunAPIModel):
    run_id: UUID
    proposals: tuple[ProposalView, ...]


class RunSummariesResponse(RunAPIModel):
    runs: tuple[RunSummary, ...]


class DryRunRequest(RunAPIModel):
    proposal_id: UUID | None = None


class ConflictDecisionRequest(RunAPIModel):
    choice: ConflictChoice


class WriteAuthorizationRequest(RunAPIModel):
    file_id: str = Field(min_length=1, max_length=255)

    @field_validator("file_id")
    @classmethod
    def validate_file_id(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 33 for character in value):
            raise ValueError("file_id must be one opaque Google file identifier")
        return value


class WriteAuthorizationResponse(RunAPIModel):
    run_id: UUID
    state: WriteAuthorizationState
    checked_at: datetime
    action: Literal["AUTHORIZE_THIS_DOCUMENT_FOR_WRITE_BACK"] = (
        "AUTHORIZE_THIS_DOCUMENT_FOR_WRITE_BACK"
    )


def _orchestrator(request: Request) -> SuperDocsWorkflow:
    return machine_operations(request).runs()


@router.post("", response_model=RunView, status_code=status.HTTP_201_CREATED)
async def start_run(
    request: Request,
    payload: Annotated[StartRunRequest, Body()],
) -> RunView:
    orchestrator = _orchestrator(request)
    google_runtime: GoogleRuntime | None = request.app.state.google_runtime
    if google_runtime is None:
        raise SuperDocsNotConfigured(
            "Google and SuperDocs must both be configured to start a production run"
        )
    database: Database = request.app.state.database
    settings: Settings = request.app.state.settings
    async with database.sessions() as session:
        selected = await session.scalar(
            select(GoogleBaselineCapture)
            .join(
                CloudDocument,
                CloudDocument.id == GoogleBaselineCapture.cloud_document_id,
            )
            .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
            .where(
                GoogleBaselineCapture.id == payload.baseline_capture_id,
                GoogleBaselineCapture.cloud_document_id == payload.source_id,
                CloudConnection.owner_subject == settings.docrelay_owner_subject,
            )
        )
        if selected is None:
            raise SourceNotFound("selected immutable Google baseline was not found")
        google = GoogleConnectionService(
            session=session,
            runtime=google_runtime,
            owner_subject=settings.docrelay_owner_subject,
            state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
            refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
            baseline_max_attempts=settings.google_baseline_max_attempts,
        )
        recaptured = await google.recapture_registered_source(payload.source_id)

    result = recaptured.result
    if (
        result.revision_id != selected.provider_revision_id
        or result.native_raw_sha256 != selected.native_raw_sha256
        or result.native_canonical_sha256 != selected.native_canonical_sha256
    ):
        raise SelectedBaselineChanged(
            "the selected Google baseline is no longer the current immutable revision"
        )
    superdocs_baseline = SuperDocsBaseline(
        cloud_document_id=recaptured.document.id,
        provider_revision_id=result.revision_id,
        source_format=recaptured.document.mime_type,
        captured_at=result.captured_at,
        native_raw_sha256=result.native_raw_sha256,
        native_canonical_sha256=result.native_canonical_sha256,
        exported_docx_sha256=result.exported_docx_sha256,
        canonical_schema_version=result.canonicalizer_version,
        capability_evidence=recaptured.capture.capability_evidence,
        provider_evidence=recaptured.capture.provider_evidence
        | {
            "selected_baseline_capture_id": str(selected.id),
            "selected_capture_docx_sha256": selected.exported_docx_sha256,
            "per_run_docx_sha256": result.exported_docx_sha256,
        },
        docx_bytes=result.docx_bytes,
        filename=f"docrelay-source-{recaptured.document.id}.docx",
    )
    return await orchestrator.start_run(
        baseline=superdocs_baseline,
        instruction=payload.instruction,
        model_tier=payload.model_tier,
        thinking_depth=payload.thinking_depth,
    )


@router.get("", response_model=RunSummariesResponse)
async def list_runs(request: Request) -> RunSummariesResponse:
    return RunSummariesResponse(runs=await machine_operations(request).list_run_summaries())


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: UUID, request: Request) -> RunView:
    return await machine_operations(request).get_run(run_id)


@router.get("/{run_id}/summary", response_model=RunSummary)
async def get_run_summary(run_id: UUID, request: Request) -> RunSummary:
    return await machine_operations(request).get_run_summary(run_id)


@router.post("/{run_id}/resume", response_model=RunView)
async def resume_run(
    run_id: UUID,
    request: Request,
    payload: Annotated[ResumeRequest | None, Body()] = None,
) -> RunView:
    return await machine_operations(request).resume_run(
        run_id,
        allow_definitive_retry=payload.allow_definitive_retry if payload else False,
    )


@router.get("/{run_id}/proposals", response_model=ProposalsResponse)
async def list_proposals(run_id: UUID, request: Request) -> ProposalsResponse:
    proposals = await machine_operations(request).list_proposals(run_id)
    return ProposalsResponse(run_id=run_id, proposals=proposals)


@router.post("/{run_id}/decisions", response_model=RunView)
async def submit_decisions(
    run_id: UUID,
    request: Request,
    payload: Annotated[SubmitDecisionsRequest, Body()],
) -> RunView:
    return await machine_operations(request).submit_review_decisions(
        run_id,
        tuple(
            DecisionInput(
                proposal_id=item.proposal_id,
                approve=item.approve,
                feedback=item.feedback,
            )
            for item in payload.decisions
        ),
    )


@router.post("/{run_id}/continue", response_model=RunView)
async def submit_continue(
    run_id: UUID,
    request: Request,
    payload: Annotated[ContinueRequest, Body()],
) -> RunView:
    return await machine_operations(request).submit_continue(
        run_id,
        should_continue=payload.should_continue,
    )


@router.get("/{run_id}/export", response_model=ExportView)
async def get_export(run_id: UUID, request: Request) -> ExportView:
    view = await _orchestrator(request).get_run(run_id)
    if view.export is None:
        raise ExportNotReady("reviewed SuperDocs export metadata is not ready")
    return view.export


@router.get("/{run_id}/export/content")
async def download_export(run_id: UUID, request: Request) -> Response:
    artifact = await machine_operations(request).get_export(run_id)
    return Response(
        content=artifact.content,
        media_type=artifact.metadata.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="docrelay-reviewed-{run_id}.docx"',
            "X-Content-SHA256": artifact.metadata.sha256,
        },
    )


@router.post("/{run_id}/dry-run", response_model=DryRunView)
async def create_dry_run(
    run_id: UUID,
    request: Request,
    payload: Annotated[DryRunRequest | None, Body()] = None,
) -> DryRunView:
    return await machine_operations(request).create_dry_run(
        run_id,
        proposal_id=payload.proposal_id if payload else None,
    )


@router.post("/{run_id}/write-back", response_model=WriteBackView)
async def write_back(run_id: UUID, request: Request) -> WriteBackView:
    return await machine_operations(request).write_back(run_id)


@router.post(
    "/{run_id}/write-authorization",
    response_model=WriteAuthorizationResponse,
)
async def verify_write_authorization(
    run_id: UUID,
    request: Request,
    payload: Annotated[WriteAuthorizationRequest, Body()],
) -> WriteAuthorizationResponse:
    link = await machine_operations(request).verify_write_authorization(
        run_id, picker_file_id=payload.file_id
    )
    return WriteAuthorizationResponse(
        run_id=run_id,
        state=link.write_authorization_state,
        checked_at=link.write_authorization_checked_at,
    )


@router.post("/{run_id}/conflict-decision", response_model=WriteBackView)
async def decide_write_conflict(
    run_id: UUID,
    request: Request,
    payload: Annotated[ConflictDecisionRequest, Body()],
) -> WriteBackView:
    return await machine_operations(request).decide_write_conflict(run_id, choice=payload.choice)
