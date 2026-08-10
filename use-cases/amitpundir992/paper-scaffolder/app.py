"""FastAPI entry point for the Paper Scaffolder vertical slice."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse

from paper_scaffolder.models import PaperInputs, SectionStatus
from paper_scaffolder.service import ManuscriptService, SectionNotFoundError
from paper_scaffolder.superdocs import (
    SuperDocsAuthenticationError,
    SuperDocsConfigurationError,
    SuperDocsError,
    SuperDocsHttpAdapter,
    SuperDocsMalformedResponseError,
    SuperDocsNetworkError,
    SuperDocsNotFoundError,
    SuperDocsRequestError,
    SuperDocsSettings,
    SuperDocsTimeoutError,
)
from paper_scaffolder.superdocs_workflow import (
    DecisionConflictError,
    SuperDocsWorkflowService,
)
from paper_scaffolder.template_parser import TemplateStructureError
from paper_scaffolder.validation import InputValidationError


class ScaffoldRequest(BaseModel):
    research_question: str = Field(max_length=2_000)
    methodology: str = Field(default="", max_length=12_000)
    dataset_description: str = Field(default="", max_length=12_000)
    journal_template: str = Field(max_length=20_000)

    def to_domain(self) -> PaperInputs:
        return PaperInputs(
            research_question=self.research_question,
            methodology=self.methodology,
            dataset_description=self.dataset_description,
            journal_template=self.journal_template,
        )


class SectionRequest(ScaffoldRequest):
    section_id: str = Field(min_length=1, max_length=120)


class SuperDocsUploadRequest(ScaffoldRequest):
    generated_section_ids: list[str] = Field(default_factory=list, max_length=100)


class SuperDocsEditRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    document_html: str | None = Field(default=None, max_length=50_000_000)
    instruction: str = Field(min_length=1, max_length=100_000)


class SuperDocsDecisionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    job_id: str = Field(min_length=1, max_length=256)
    change_id: str = Field(min_length=1, max_length=256)
    approved: bool
    feedback: str = Field(default="", max_length=10_000)


class SuperDocsExportRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    file_format: str = Field(default="docx", pattern="^(docx|pdf|html|markdown|txt|doc)$")
    filename: str = Field(default="paper-scaffold", min_length=1, max_length=200)


app = FastAPI(
    title="Paper Scaffolder",
    description="Grounded manuscript skeletons derived from supplied journal instructions.",
    version="0.2.0",
)
service = ManuscriptService()
_INDEX = Path(__file__).parent / "static" / "index.html"


def _build_superdocs_workflow() -> tuple[SuperDocsWorkflowService | None, str | None]:
    try:
        settings = SuperDocsSettings.from_environment()
    except SuperDocsConfigurationError as exc:
        return None, str(exc)
    return SuperDocsWorkflowService(SuperDocsHttpAdapter(settings)), None


superdocs_workflow, superdocs_configuration_message = _build_superdocs_workflow()


def _domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InputValidationError):
        return HTTPException(
            status_code=422,
            detail={"code": "invalid_input", "fields": exc.errors},
        )
    if isinstance(exc, TemplateStructureError):
        return HTTPException(
            status_code=422,
            detail={"code": "invalid_template_structure", "message": str(exc)},
        )
    if isinstance(exc, SectionNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "section_not_found", "message": str(exc)},
        )
    return HTTPException(status_code=500, detail={"code": "unexpected_error"})


def _superdocs_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SuperDocsConfigurationError):
        status = 503
    elif isinstance(exc, SuperDocsAuthenticationError):
        status = 401
    elif isinstance(exc, SuperDocsNotFoundError):
        status = 404
    elif isinstance(exc, SuperDocsTimeoutError):
        status = 504
    elif isinstance(
        exc, (SuperDocsNetworkError, SuperDocsMalformedResponseError)
    ):
        status = 502
    elif isinstance(exc, SuperDocsRequestError):
        status = 502
    else:
        status = 500
    code = exc.code if isinstance(exc, SuperDocsError) else "superdocs_error"
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": str(exc)},
    )


def _require_superdocs() -> SuperDocsWorkflowService:
    if superdocs_workflow is None:
        raise SuperDocsConfigurationError(
            superdocs_configuration_message
            or "SuperDocs is not configured on the server."
        )
    return superdocs_workflow


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_INDEX)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/scaffolds")
def create_scaffold(request: ScaffoldRequest) -> dict[str, object]:
    try:
        return service.create_scaffold(request.to_domain()).to_dict()
    except (InputValidationError, TemplateStructureError) as exc:
        raise _domain_error(exc) from exc


@app.post("/api/sections/generate")
def generate_section(request: SectionRequest) -> dict[str, object]:
    try:
        return service.generate_section(
            request.to_domain(), request.section_id
        ).to_dict()
    except (InputValidationError, TemplateStructureError, SectionNotFoundError) as exc:
        raise _domain_error(exc) from exc


@app.get("/api/superdocs/config")
def superdocs_config() -> dict[str, object]:
    return {
        "configured": superdocs_workflow is not None,
        "message": (
            "SuperDocs is configured on the server."
            if superdocs_workflow is not None
            else superdocs_configuration_message
        ),
    }


@app.post("/api/superdocs/upload")
def superdocs_upload(request: SuperDocsUploadRequest) -> dict[str, object]:
    try:
        workflow = _require_superdocs()
        inputs = request.to_domain()
        skeleton = service.create_scaffold(inputs)
        generated: dict[str, str] = {}
        for section_id in dict.fromkeys(request.generated_section_ids):
            result = service.generate_section(inputs, section_id)
            if result.section.status is SectionStatus.GENERATED:
                generated[section_id] = result.section.content
        return workflow.upload_scaffold(skeleton, generated).to_dict()
    except (InputValidationError, TemplateStructureError, SectionNotFoundError) as exc:
        raise _domain_error(exc) from exc
    except SuperDocsError as exc:
        raise _superdocs_error(exc) from exc


@app.post("/api/superdocs/edits")
def superdocs_edit(request: SuperDocsEditRequest) -> dict[str, object]:
    if not request.instruction.strip():
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_instruction", "message": "An edit instruction is required."},
        )
    try:
        return _require_superdocs().send_edit_instruction(
            session_id=request.session_id,
            document_html=request.document_html,
            instruction=request.instruction,
        ).to_dict()
    except SuperDocsError as exc:
        raise _superdocs_error(exc) from exc


@app.get("/api/superdocs/jobs/{job_id}")
def superdocs_job(job_id: str) -> dict[str, object]:
    try:
        return _require_superdocs().get_job(job_id=job_id).to_dict()
    except SuperDocsError as exc:
        raise _superdocs_error(exc) from exc


@app.post("/api/superdocs/decisions")
def superdocs_decision(request: SuperDocsDecisionRequest) -> dict[str, object]:
    try:
        return _require_superdocs().decide_change(
            session_id=request.session_id,
            job_id=request.job_id,
            change_id=request.change_id,
            approved=request.approved,
            feedback=request.feedback,
        ).to_dict()
    except DecisionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "decision_conflict", "message": str(exc)},
        ) from exc
    except SuperDocsError as exc:
        raise _superdocs_error(exc) from exc


@app.post("/api/superdocs/export")
def superdocs_export(request: SuperDocsExportRequest) -> Response:
    try:
        exported = _require_superdocs().export_document(
            session_id=request.session_id,
            file_format=request.file_format,
            filename=request.filename,
        )
    except SuperDocsError as exc:
        raise _superdocs_error(exc) from exc
    return Response(
        content=exported.content,
        media_type=exported.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"'
        },
    )
