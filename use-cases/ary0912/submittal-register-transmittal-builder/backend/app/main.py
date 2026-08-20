import base64
import re
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agents.runtime import workflow
from app.agents.state import SubmittalState
from app.db.session import get_db
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.schemas.review import (
    ReviewFindingRequest,
    ReviewFindingResponse,
)
from app.schemas.register import (
    GenerateRegisterRequest,
    GenerateRegisterResponse,
    OverdueRegisterResponse,
    RegisterItemResponse,
    RegisterResponse,
    RegisterStatusUpdate,
    SubmittalDetailResponse,
)
from app.services.register import (
    generate_register,
    get_overdue_submittals,
    get_register,
    update_register_status,
    update_submittal_status,
)
from app.services.review import review_finding
from app.services.transmittal import (
    build_transmittal_content,
)
from app.services.superdocs_workflow import (
    SuperDocsWorkflow,
)
from app.schemas.workflow import (
    ChatRequest,
    ChatResponse,
    RunSubmittalRequest,
    SearchResponse,
)
from app.services.search_chat import (
    chat_project,
    search_project,
)
from app.models.transmittal import Transmittal
from app.superdocs.factory import (
    get_superdocs_client,
)

from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware

from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Submittal Register & Transmittal Builder",
    version="0.1.0",
    lifespan=lifespan,
)

# ============================================================
# CORS — allow the Next.js dev server and any configured
# frontend origin.  In production, set FRONTEND_ORIGIN to
# the deployed URL.
# ============================================================

import os as _os

_frontend_origins = [
    o.strip()
    for o in _os.environ.get(
        "FRONTEND_ORIGIN",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONSTANTS
# ============================================================

PROJECT_ID = "BROD-2026"
SUBMITTAL_NUMBER = "SUB-001"
EXPORTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "exports"
)


def _export_filename(number: str) -> str:
    safe_number = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        number,
    )
    return f"{safe_number}.docx"


def _register_item_response(
    submittal: Submittal,
    db: Session | None = None,
) -> RegisterItemResponse:
    finding_count = 0
    unresolved_count = 0
    reviewed_count = 0

    if db is not None:
        findings = (
            db.query(Finding)
            .filter(Finding.submittal_id == submittal.id)
            .all()
        )
        finding_count = len(findings)
        unresolved_count = sum(
            1
            for f in findings
            if f.status in {"PENDING_REVIEW", "CLARIFICATION_REQUESTED"}
        )
        reviewed_count = finding_count - unresolved_count

    return RegisterItemResponse(
        id=submittal.id,
        project_id=submittal.project_id,
        number=submittal.number,
        title=submittal.title,
        description=submittal.description,
        specification_section=(
            submittal.specification_section
        ),
        required_by=submittal.required_by,
        required_form=submittal.required_form,
        source_evidence=submittal.source_evidence,
        specification_revision=(
            submittal.specification_revision
        ),
        status=submittal.status,
        register_status=submittal.register_status,
        due_date=submittal.due_date,
        created_at=submittal.created_at,
        updated_at=submittal.updated_at,
        finding_count=finding_count,
        unresolved_finding_count=unresolved_count,
        reviewed_finding_count=reviewed_count,
    )


# ============================================================
# HELPERS
# ============================================================

def build_thread_id(
    project_id: str,
    submittal_number: str,
) -> str:

    return (
        f"{project_id}:{submittal_number}"
    )


def build_workflow_config(
    thread_id: str,
) -> RunnableConfig:

    return RunnableConfig(
        configurable={
            "thread_id": thread_id,
        }
    )


def _job_changes(job: dict) -> list[dict]:
    changes = job.get("proposed_changes")
    if isinstance(changes, str):
        import json as _json
        try:
            parsed = _json.loads(changes)
            if isinstance(parsed, list):
                changes = parsed
        except (_json.JSONDecodeError, TypeError):
            pass
    if isinstance(changes, list):
        return changes

    changes = job.get("changes")
    if isinstance(changes, str):
        import json as _json
        try:
            parsed = _json.loads(changes)
            if isinstance(parsed, list):
                changes = parsed
        except (_json.JSONDecodeError, TypeError):
            pass
    if isinstance(changes, list):
        return changes

    metadata = job.get("metadata")
    if isinstance(metadata, dict):
        pending = metadata.get("pending_changes")
        if isinstance(pending, str):
            import json as _json
            try:
                parsed = _json.loads(pending)
                if isinstance(parsed, list):
                    pending = parsed
            except (_json.JSONDecodeError, TypeError):
                pass
        if isinstance(pending, list):
            return pending

    return []


def _job_is_ready_for_approval(job: dict) -> bool:
    status = str(
        job.get("status", job.get("state", ""))
    ).lower()
    return (
        bool(_job_changes(job))
        and status
        in {
            "completed",
            "complete",
            "awaiting_approval",
            "proposed",
            "review_required",
        }
    )


def _raise_superdocs_error(error: httpx.HTTPStatusError) -> None:
    response = error.response
    status_code = 502 if response.status_code >= 500 else response.status_code
    detail = response.text or "SuperDocs service request failed."
    raise HTTPException(
        status_code=status_code,
        detail=detail,
    ) from error


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
    }


# ============================================================
# SUBMITTAL REGISTER
# ============================================================

@app.get(
    "/projects/{project_id}/submittals",
    response_model=RegisterResponse,
)
def get_project_register(
    project_id: str,
    db: Session = Depends(get_db),
):
    items = get_register(
        db,
        project_id,
    )
    return RegisterResponse(
        project_id=project_id,
        items=[
            _register_item_response(item, db)
            for item in items
        ],
    )


@app.post(
    "/projects/{project_id}/submittals/register",
    response_model=GenerateRegisterResponse,
)
def generate_project_register(
    project_id: str,
    payload: GenerateRegisterRequest,
    db: Session = Depends(get_db),
):
    requirements = [
        req.model_dump()
        for req in payload.requirements
    ]
    items = generate_register(
        db=db,
        project_id=project_id,
        requirements=requirements,
    )
    return GenerateRegisterResponse(
        project_id=project_id,
        count=len(items),
        items=[
            _register_item_response(item, db)
            for item in items
        ],
    )


@app.patch(
    "/submittals/{submittal_number}/register-status",
    response_model=RegisterItemResponse,
)
def update_submittal_register_status(
    submittal_number: str,
    payload: RegisterStatusUpdate,
    db: Session = Depends(get_db),
):
    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.number == submittal_number
        )
        .first()
    )

    if submittal is None:
        raise HTTPException(
            status_code=404,
            detail="Submittal not found.",
        )

    try:
        updated = update_register_status(
            db,
            submittal,
            payload.status,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return _register_item_response(updated, db)


@app.get(
    "/projects/{project_id}/submittals/overdue",
    response_model=OverdueRegisterResponse,
)
def get_project_overdue_submittals(
    project_id: str,
    db: Session = Depends(get_db),
):
    items = get_overdue_submittals(
        db,
        project_id,
        date.today(),
    )
    return OverdueRegisterResponse(
        project_id=project_id,
        overdue_count=len(items),
        items=[
            _register_item_response(item, db)
            for item in items
        ],
    )


@app.get(
    "/submittals/{submittal_number}",
    response_model=SubmittalDetailResponse,
)
def get_submittal_detail(
    submittal_number: str,
    db: Session = Depends(get_db),
):
    submittal = (
        db.query(Submittal)
        .filter(Submittal.number == submittal_number)
        .first()
    )
    if submittal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Submittal {submittal_number} not found.",
        )

    findings = (
        db.query(Finding)
        .filter(Finding.submittal_id == submittal.id)
        .all()
    )

    transmittal = (
        db.query(Transmittal)
        .filter(Transmittal.submittal_id == submittal.id)
        .order_by(Transmittal.created_at.desc())
        .first()
    )

    finding_dicts = [
        {
            "id": f.id,
            "attribute": f.attribute,
            "requirement": f.requirement,
            "submitted_value": f.submitted_value,
            "result": f.result,
            "specification_evidence": f.specification_evidence,
            "submission_evidence": f.submission_evidence,
            "status": f.status,
            "reviewer": f.reviewer,
            "reviewer_comment": f.reviewer_comment,
            "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None,
        }
        for f in findings
    ]

    transmittal_dict = (
        {
            "id": transmittal.id,
            "number": transmittal.number,
            "status": transmittal.status,
            "superdocs_session_id": transmittal.superdocs_session_id,
            "superdocs_job_id": transmittal.superdocs_job_id,
            "export_url": transmittal.export_url,
            "created_at": transmittal.created_at.isoformat() if transmittal.created_at else None,
        }
        if transmittal
        else None
    )

    base = _register_item_response(submittal, db)
    return SubmittalDetailResponse(
        **base.model_dump(),
        findings=finding_dicts,
        transmittal=transmittal_dict,
    )


# ============================================================
# SEARCH & CONTEXTUAL CHAT
# ============================================================

@app.get(
    "/projects/{project_id}/search",
    response_model=SearchResponse,
)
def search_project_endpoint(
    project_id: str,
    q: str = "",
    db: Session = Depends(get_db),
):
    return search_project(db=db, project_id=project_id, query=q)


@app.post(
    "/projects/{project_id}/chat",
    response_model=ChatResponse,
)
def chat_project_endpoint(
    project_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    return chat_project(
        db=db,
        project_id=project_id,
        query=payload.query,
        context_submittal_number=payload.context_submittal_number,
    )


@app.post(
    "/projects/{project_id}/seed-demo",
)
def seed_demo_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
):
    """Seed comprehensive demo dataset with Scenario A (Flooring), Scenario B (Fire Doors), and Overdue item."""
    from datetime import date, timedelta
    requirements = [
        {
            "title": "Flooring Product Data",
            "description": "Manufacturer technical sheet for resilient vinyl flooring",
            "specification_section": "09 65 00",
            "required_by": "Flooring Subcontractor Ltd",
            "required_form": "Product data / technical sheet",
            "source_evidence": "Section 09 65 00 §2.01: Minimum thickness 3.0mm, Class A flame spread, 10yr warranty.",
            "specification_revision": "Rev 02",
            "due_date": date.today() + timedelta(days=14),
        },
        {
            "title": "Fire-Rated Stairwell Doors & Frames",
            "description": "UL 10C fire door submittal packet and shop drawings",
            "specification_section": "08 11 13",
            "required_by": "Apex Door & Hardware Specialists",
            "required_form": "Product data, shop drawings, UL certs",
            "source_evidence": "Section 08 11 13 §2.02.A: Stair enclosure assemblies minimum 90-min fire resistance.",
            "specification_revision": "Rev 01",
            "due_date": date.today() + timedelta(days=7),
        },
        {
            "title": "Structural Steel Mill Certificates",
            "description": "Mill test certificates for structural wide-flange beams",
            "specification_section": "05 12 00",
            "required_by": "Severfield Structural Steel",
            "required_form": "Certified Mill Test Reports (MTRs)",
            "source_evidence": "Section 05 12 00 §1.04.A: Submit certified mill test reports prior to steel erection.",
            "specification_revision": "Rev 01",
            "due_date": date.today() - timedelta(days=5),  # Overdue!
        },
    ]

    items = generate_register(db=db, project_id=project_id, requirements=requirements)
    return {
        "status": "seeded",
        "project_id": project_id,
        "items_count": len(items),
        "items": [_register_item_response(item, db) for item in items],
    }


# ============================================================
# RUN SUBMITTAL WORKFLOW
# ============================================================

@app.post("/runs/submittal")
def run_submittal(
    payload: RunSubmittalRequest | None = None,
    db: Session = Depends(get_db),
):
    """
    Start the submittal workflow.

    Flow:
        LangGraph → Ingest → Extract → Compare → Checkpoint → Interrupt → Await Human Review
    """
    req_project_id = (payload.project_id if payload else None) or PROJECT_ID
    req_submittal_number = (payload.submittal_number if payload else None) or SUBMITTAL_NUMBER
    req_spec_section = (payload.specification_section if payload else None) or "09 65 00"
    req_scenario = payload.scenario if payload else None
    req_title = (payload.title if payload else None) or ("Fire-Rated Stairwell Doors" if req_spec_section == "08 11 13" else "Flooring Product Data")

    # --------------------------------------------------------
    # 1. Create stable workflow thread ID
    # --------------------------------------------------------

    thread_id = build_thread_id(
        req_project_id,
        req_submittal_number,
    )

    config = build_workflow_config(
        thread_id
    )

    # --------------------------------------------------------
    # 2. Run LangGraph
    # --------------------------------------------------------

    initial_state: SubmittalState = {
        "project_id": req_project_id,
        "submittal_id": req_submittal_number,
        "specification_section": req_spec_section,
        "scenario": req_scenario,
    }
    if payload and payload.specification_data:
        initial_state["specification"] = payload.specification_data
    if payload and payload.submission_data:
        initial_state["submission"] = payload.submission_data

    result = workflow.invoke(
        initial_state,
        config=config,
    )

    # --------------------------------------------------------
    # 3. Read the persisted workflow state
    # --------------------------------------------------------

    state_snapshot = workflow.get_state(
        config
    )

    current_state = (
        state_snapshot.values
    )

    # --------------------------------------------------------
    # 4. Determine whether workflow is interrupted
    # --------------------------------------------------------

    interrupted = bool(
        state_snapshot.tasks
        and any(
            getattr(
                task,
                "interrupts",
                None,
            )
            for task in state_snapshot.tasks
        )
    )

    # --------------------------------------------------------
    # 5. Find existing Submittal
    # --------------------------------------------------------

    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.number == req_submittal_number
        )
        .first()
    )

    # --------------------------------------------------------
    # 6. Create Submittal if necessary
    # --------------------------------------------------------

    if submittal is None:
        submittal = Submittal(
            project_id=req_project_id,
            number=req_submittal_number,
            title=req_title,
            specification_section=req_spec_section,
            status="PENDING",
            register_status="UNDER_REVIEW",
        )
        db.add(submittal)
        db.flush()

    # --------------------------------------------------------
    # 7. Check existing findings
    # --------------------------------------------------------

    existing_findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    # --------------------------------------------------------
    # 8. Persist AI findings only once
    # --------------------------------------------------------

    if not existing_findings:

        workflow_findings = (
            current_state.get(
                "findings",
                [],
            )
        )

        for finding_data in (
            workflow_findings
        ):

            finding = Finding(
                # Internal database UUID.
                submittal_id=submittal.id,

                attribute=finding_data[
                    "attribute"
                ],

                requirement=finding_data[
                    "requirement"
                ],

                submitted_value=finding_data[
                    "submitted_value"
                ],

                result=finding_data[
                    "result"
                ],

                specification_evidence=(
                    finding_data[
                        "specification_evidence"
                    ]
                ),

                submission_evidence=(
                    finding_data[
                        "submission_evidence"
                    ]
                ),

                status="PENDING_REVIEW",
            )

            db.add(finding)

    # --------------------------------------------------------
    # 9. Commit application state
    # --------------------------------------------------------

    db.commit()

    db.refresh(
        submittal
    )

    # --------------------------------------------------------
    # 10. Fetch persisted findings
    # --------------------------------------------------------

    persisted_findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    # --------------------------------------------------------
    # 11. Return review state
    # --------------------------------------------------------

    return {
        "thread_id": thread_id,

        "stage": (
            "WAITING_FOR_REVIEW"
            if interrupted
            else current_state.get(
                "current_stage"
            )
        ),

        "review_status": (
            "PENDING_REVIEW"
            if interrupted
            else current_state.get(
                "review_status"
            )
        ),

        "interrupted": interrupted,

        "submittal_id": submittal.id,

        "submittal_number": (
            submittal.number
        ),

        "submittal_status": (
            submittal.status
        ),

        "findings_count": len(
            persisted_findings
        ),

        "stage_durations": (
            current_state.get("stage_durations") or {}
        ),

        "operations_count": (
            current_state.get("operations_count") or 0
        ),

        "findings": [
            {
                "id": finding.id,

                "attribute": (
                    finding.attribute
                ),

                "requirement": (
                    finding.requirement
                ),

                "submitted_value": (
                    finding.submitted_value
                ),

                "result": finding.result,

                "specification_evidence": (
                    finding.specification_evidence
                ),

                "submission_evidence": (
                    finding.submission_evidence
                ),

                "status": finding.status,

                "reviewer": (
                    finding.reviewer
                ),

                "reviewer_comment": (
                    finding.reviewer_comment
                ),

                "reviewed_at": (
                    finding.reviewed_at.isoformat()
                    if finding.reviewed_at
                    else None
                ),
            }
            for finding
            in persisted_findings
        ],
    }


# ============================================================
# GET SUBMITTAL REVIEW
# ============================================================

@app.get(
    "/submittals/{submittal_number}/review"
)
def get_submittal_review(
    submittal_number: str,
    db: Session = Depends(get_db),
):
    """
    Return the complete persisted review state
    for a submittal.
    """

    # --------------------------------------------------------
    # Find submittal by human-facing number.
    # --------------------------------------------------------

    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.number
            == submittal_number
        )
        .first()
    )

    if submittal is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Submittal "
                f"{submittal_number} "
                f"not found."
            ),
        )

    # --------------------------------------------------------
    # Find findings through internal UUID.
    # --------------------------------------------------------

    findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    return {
        "submittal": {
            "id": submittal.id,

            "number": (
                submittal.number
            ),

            "title": (
                submittal.title
            ),

            "status": (
                submittal.status
            ),

            "specification_section": (
                submittal.specification_section
            ),

            "due_date": (
                submittal.due_date.isoformat()
                if submittal.due_date
                else None
            ),
        },

        "findings": [
            {
                "id": finding.id,

                "attribute": (
                    finding.attribute
                ),

                "requirement": (
                    finding.requirement
                ),

                "submitted_value": (
                    finding.submitted_value
                ),

                "result": finding.result,

                "specification_evidence": (
                    finding.specification_evidence
                ),

                "submission_evidence": (
                    finding.submission_evidence
                ),

                "status": finding.status,

                "reviewer": (
                    finding.reviewer
                ),

                "reviewer_comment": (
                    finding.reviewer_comment
                ),

                "reviewed_at": (
                    finding.reviewed_at.isoformat()
                    if finding.reviewed_at
                    else None
                ),
            }
            for finding
            in findings
        ],
    }


# ============================================================
# REVIEW INDIVIDUAL FINDING
# ============================================================

@app.post(
    "/findings/{finding_id}/review",
    response_model=ReviewFindingResponse,
)
def review_finding_endpoint(
    finding_id: str,
    payload: ReviewFindingRequest,
    db: Session = Depends(get_db),
):
    """
    Apply a human decision to one finding.

    Supported:

        APPROVE
        REJECT
        REQUEST_CLARIFICATION
    """

    try:

        # ----------------------------------------------------
        # 1. Apply human decision.
        # ----------------------------------------------------

        finding = review_finding(
            db=db,
            finding_id=finding_id,
            reviewer=payload.reviewer,
            decision=payload.decision,
            comment=payload.comment,
        )

        # ----------------------------------------------------
        # 2. Recalculate parent register status.
        # ----------------------------------------------------

        update_submittal_status(
            db=db,
            submittal_id=finding.submittal_id,
        )

        # ----------------------------------------------------
        # 3. Safety check.
        # ----------------------------------------------------

        if finding.reviewer is None:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Reviewed finding "
                    "has no reviewer."
                ),
            )

        # ----------------------------------------------------
        # 4. Return review result.
        # ----------------------------------------------------

        return ReviewFindingResponse(
            finding_id=finding.id,

            status=finding.status,

            reviewer=finding.reviewer,

            comment=(
                finding.reviewer_comment
            ),

            reviewed_at=(
                finding.reviewed_at.isoformat()
                if finding.reviewed_at
                else ""
            ),
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


# ============================================================
# RESUME INTERRUPTED WORKFLOW
# ============================================================

@app.post(
    "/runs/{thread_id}/resume"
)
def resume_submittal_workflow(
    thread_id: str,
    db: Session = Depends(get_db),
):
    """
    Resume an interrupted LangGraph workflow.

    The business review decisions have already been
    persisted through:

        POST /findings/{finding_id}/review

    This endpoint verifies that no findings remain
    pending clarification/review and then resumes the
    LangGraph checkpoint.
    """

    # --------------------------------------------------------
    # 1. Build LangGraph configuration.
    # --------------------------------------------------------

    config = build_workflow_config(
        thread_id
    )

    # --------------------------------------------------------
    # 2. Check whether checkpoint exists.
    # --------------------------------------------------------

    state_snapshot = workflow.get_state(
        config
    )

    if not state_snapshot.values:

        raise HTTPException(
            status_code=404,
            detail=(
                f"No workflow state found "
                f"for thread '{thread_id}'."
            ),
        )

    # --------------------------------------------------------
    # 3. Find pending review items.
    # --------------------------------------------------------

    submittal_number = (
        state_snapshot.values.get(
            "submittal_id"
        )
    )

    if not submittal_number:

        raise HTTPException(
            status_code=400,
            detail=(
                "Checkpoint does not contain "
                "a submittal identifier."
            ),
        )

    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.number
            == submittal_number
        )
        .first()
    )

    if submittal is None:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Submittal "
                f"{submittal_number} "
                f"not found."
            ),
        )

    findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    pending_findings = [
        finding
        for finding in findings
        if finding.status
        in {
            "PENDING_REVIEW",
            "CLARIFICATION_REQUESTED",
        }
    ]

    # --------------------------------------------------------
    # 4. Do not allow workflow to continue while review
    #    is incomplete.
    # --------------------------------------------------------

    if pending_findings:

        return {
            "thread_id": thread_id,

            "status": (
                "PENDING_REVIEW"
            ),

            "message": (
                "Human review is not "
                "complete. Resolve all "
                "findings before resuming "
                "the workflow."
            ),

            "pending_findings": [
                {
                    "id": finding.id,

                    "attribute": (
                        finding.attribute
                    ),

                    "status": (
                        finding.status
                    ),
                }
                for finding
                in pending_findings
            ],
        }

    # --------------------------------------------------------
    # 5. Build final human-review summary.
    # --------------------------------------------------------

    human_review = {
        "reviewer_decisions": [
            {
                "finding_id": finding.id,

                "attribute": (
                    finding.attribute
                ),

                "status": (
                    finding.status
                ),

                "reviewer": (
                    finding.reviewer
                ),

                "comment": (
                    finding.reviewer_comment
                ),

                "reviewed_at": (
                    finding.reviewed_at.isoformat()
                    if finding.reviewed_at
                    else None
                ),
            }
            for finding
            in findings
        ]
    }

    # --------------------------------------------------------
    # 6. Resume LangGraph.
    #
    # This resumes the exact checkpoint that was
    # interrupted at interrupt().
    # --------------------------------------------------------

    result = workflow.invoke(
        Command(
            resume=human_review
        ),
        config=config,
    )

    # --------------------------------------------------------
    # 7. Read resumed state.
    # --------------------------------------------------------

    final_state = workflow.get_state(
        config
    )

    state_values = (
        final_state.values
    )

    return {
        "thread_id": thread_id,

        "stage": (
            state_values.get(
                "current_stage"
            )
        ),

        "review_status": (
            state_values.get(
                "review_status"
            )
        ),

        "human_review": (
            state_values.get(
                "human_review"
            )
        ),

        "message": (
            "Workflow resumed successfully."
        ),
    }

@app.post(
    "/transmittals/{submittal_number}"
)
async def create_transmittal(
    submittal_number: str,
    db: Session = Depends(get_db),
):
    """
    Build a transmittal packet from the reviewed
    submittal findings and create a SuperDocs session.
    """

    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.number
            == submittal_number
        )
        .first()
    )

    if submittal is None:

        raise HTTPException(
            status_code=404,
            detail="Submittal not found.",
        )

    # Application-level idempotency: keep one current transmittal for a
    # submittal and return it before rebuilding HTML or calling SuperDocs.
    existing = (
        db.query(Transmittal)
        .filter(
            Transmittal.submittal_id
            == submittal.id
        )
        .order_by(Transmittal.created_at.desc())
        .first()
    )

    if existing is not None:
        return {
            "transmittal_id": existing.id,
            "number": existing.number,
            "status": existing.status,
            "session_id": existing.superdocs_session_id,
            "job_id": existing.superdocs_job_id,
            "export_url": existing.export_url,
        }

    findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    if not findings:

        raise HTTPException(
            status_code=400,
            detail=(
                "Submittal has no findings."
            ),
        )

    unresolved = [
        finding
        for finding in findings
        if finding.status
        in {
            "PENDING_REVIEW",
            "CLARIFICATION_REQUESTED",
        }
    ]

    if unresolved:

        raise HTTPException(
            status_code=409,
            detail=(
                "All findings must be reviewed "
                "before creating a transmittal."
            ),
        )

    reviewer = next(
        (
            finding.reviewer
            for finding in findings
            if finding.reviewer
        ),
        "Unknown reviewer",
    )

    project = {
        "name": "Bristol Office Development",
        "project_number": (
            submittal.project_id
        ),
    }

    submittal_data = {
        "number": submittal.number,
        "title": submittal.title,
        "specification_section": (
            submittal.specification_section
        ),
    }

    findings_data = [
        {
            "attribute": finding.attribute,
            "requirement": (
                finding.requirement
            ),
            "submitted_value": (
                finding.submitted_value
            ),
            "result": finding.result,
            "specification_evidence": (
                finding.specification_evidence
            ),
            "submission_evidence": (
                finding.submission_evidence
            ),
            "status": finding.status,
            "reviewer_comment": finding.reviewer_comment,
        }
        for finding in findings
    ]

    html = build_transmittal_content(
        project=project,
        submittal=submittal_data,
        findings=findings_data,
        reviewer=reviewer,
    )

    client = get_superdocs_client()

    service = SuperDocsWorkflow(
        client
    )

    result = (
        await service.create_transmittal_document(
            filename=f"{submittal.number}-transmittal.html",
            html=html,
        )
    )

    if not result.get("session_id"):
        raise HTTPException(
            status_code=502,
            detail="SuperDocs upload did not return session_id.",
        )

    transmittal = Transmittal(
        project_id=submittal.project_id,
        submittal_id=submittal.id,
        number=(
            f"TR-{submittal.number}"
        ),
        status="UPLOADED",
        superdocs_session_id=(
            result["session_id"]
        ),
    )

    db.add(transmittal)

    db.commit()

    db.refresh(transmittal)

    return {
        "transmittal_id": transmittal.id,
        "number": transmittal.number,
        "status": transmittal.status,
        "session_id": (
            result["session_id"]
        ),
        "html": html,
    }

@app.post(
    "/transmittals/{transmittal_id}/edit"
)
async def edit_transmittal(
    transmittal_id: str,
    message: str,
    db: Session = Depends(get_db),
):
    transmittal = (
        db.query(Transmittal)
        .filter(
            Transmittal.id
            == transmittal_id
        )
        .first()
    )

    if transmittal is None:

        raise HTTPException(
            status_code=404,
            detail="Transmittal not found.",
        )

    if not transmittal.superdocs_session_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "Transmittal has no "
                "SuperDocs session."
            ),
        )

    if transmittal.status == "EXPORTED":
        raise HTTPException(
            status_code=409,
            detail="An exported transmittal cannot be edited.",
        )

    if transmittal.status == "PROCESSING_EDIT":
        raise HTTPException(
            status_code=409,
            detail="A SuperDocs edit is already processing.",
        )

    # For this vertical slice we regenerate the
    # authoritative HTML from the persisted register
    # before sending the edit request.

    submittal = (
        db.query(Submittal)
        .filter(
            Submittal.id
            == transmittal.submittal_id
        )
        .first()
    )

    if submittal is None:

        raise HTTPException(
            status_code=404,
            detail="Submittal not found.",
        )

    findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id
            == submittal.id
        )
        .all()
    )

    reviewer = next(
        (
            finding.reviewer
            for finding in findings
            if finding.reviewer
        ),
        "Unknown reviewer",
    )

    html = build_transmittal_content(
        project={
            "name": (
                "Bristol Office Development"
            ),
            "project_number": (
                submittal.project_id
            ),
        },
        submittal={
            "number": submittal.number,
            "title": submittal.title,
            "specification_section": (
                submittal.specification_section
            ),
        },
        findings=[
            {
                "attribute": finding.attribute,
                "requirement": (
                    finding.requirement
                ),
                "submitted_value": (
                    finding.submitted_value
                ),
                "result": finding.result,
                "specification_evidence": (
                    finding.specification_evidence
                ),
                "submission_evidence": (
                    finding.submission_evidence
                ),
                "status": finding.status,
                "reviewer_comment": finding.reviewer_comment,
            }
            for finding in findings
        ],
        reviewer=reviewer,
    )

    client = get_superdocs_client()

    service = SuperDocsWorkflow(
        client
    )

    try:
        result = await service.request_edit(
            session_id=transmittal.superdocs_session_id,
            html=html,
            message=message,
        )
    except httpx.HTTPStatusError as error:
        _raise_superdocs_error(error)

    job_id = result.get("job_id")
    if not job_id:
        raise HTTPException(
            status_code=502,
            detail="SuperDocs edit did not return a job_id.",
        )

    transmittal.status = "PROCESSING_EDIT"

    transmittal.superdocs_job_id = job_id

    db.commit()

    return {
        "transmittal_id": transmittal.id,
        "status": (
            transmittal.status
        ),
        "session_id": (
            transmittal.superdocs_session_id
        ),
        "job_id": job_id,
    }


@app.get(
    "/transmittals/{transmittal_id}/job"
)
async def get_transmittal_job(
    transmittal_id: str,
    db: Session = Depends(get_db),
):
    transmittal = (
        db.query(Transmittal)
        .filter(Transmittal.id == transmittal_id)
        .first()
    )

    if transmittal is None:
        raise HTTPException(
            status_code=404,
            detail="Transmittal not found.",
        )

    if not transmittal.superdocs_job_id:
        raise HTTPException(
            status_code=409,
            detail="Transmittal has no SuperDocs job.",
        )

    service = SuperDocsWorkflow(get_superdocs_client())
    try:
        job = await service.get_job(transmittal.superdocs_job_id)
    except httpx.HTTPStatusError as error:
        _raise_superdocs_error(error)

    changes = _job_changes(job)
    if (
        transmittal.status == "PROCESSING_EDIT"
        and _job_is_ready_for_approval(job)
    ):
        transmittal.status = "AWAITING_APPROVAL"
        db.commit()

    return {
        "transmittal_id": transmittal.id,
        "job_id": transmittal.superdocs_job_id,
        "status": job.get("status", job.get("state")),
        "proposed_changes": changes,
        "job": job,
    }

@app.post(
    "/transmittals/{transmittal_id}/approve"
)
async def approve_transmittal_edit(
    transmittal_id: str,
    change_id: str | None = None,
    approved: bool = True,
    db: Session = Depends(get_db),
):
    transmittal = (
        db.query(Transmittal)
        .filter(
            Transmittal.id
            == transmittal_id
        )
        .first()
    )

    if transmittal is None:

        raise HTTPException(
            status_code=404,
            detail="Transmittal not found.",
        )

    if not transmittal.superdocs_session_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "No SuperDocs session."
            ),
        )

    if transmittal.status != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=(
                "SuperDocs job must be ready for approval "
                "before approving or rejecting it."
            ),
        )

    if not transmittal.superdocs_job_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "No pending SuperDocs job."
            ),
        )

    client = get_superdocs_client()

    service = SuperDocsWorkflow(
        client
    )

    try:
        job = await service.get_job(
            transmittal.superdocs_job_id
        )
    except httpx.HTTPStatusError as error:
        _raise_superdocs_error(error)

    changes = _job_changes(job)
    if not _job_is_ready_for_approval(job):
        raise HTTPException(
            status_code=409,
            detail="SuperDocs job is not ready for approval.",
        )

    if change_id is None and changes:
        change_id = changes[0].get("change_id")

    try:
        result = await service.approve(
            session_id=transmittal.superdocs_session_id,
            job_id=transmittal.superdocs_job_id,
            change_id=change_id,
            approved=approved,
        )
    except httpx.HTTPStatusError as error:
        _raise_superdocs_error(error)

    if approved:

        transmittal.status = (
            "EDIT_APPROVED"
        )

    else:

        transmittal.status = (
            "EDIT_REJECTED"
        )

    db.commit()

    return {
        "transmittal_id": (
            transmittal.id
        ),
        "approved": approved,
        "status": transmittal.status,
        "result": result,
    }

@app.post(
    "/transmittals/{transmittal_id}/export"
)
async def export_transmittal(
    transmittal_id: str,
    db: Session = Depends(get_db),
):
    transmittal = (
        db.query(Transmittal)
        .filter(
            Transmittal.id
            == transmittal_id
        )
        .first()
    )

    if transmittal is None:

        raise HTTPException(
            status_code=404,
            detail="Transmittal not found.",
        )

    if transmittal.status != "EDIT_APPROVED":

        raise HTTPException(
            status_code=409,
            detail=(
                "Transmittal must have an "
                "approved SuperDocs edit before export."
            ),
        )

    if not transmittal.superdocs_session_id:

        raise HTTPException(
            status_code=409,
            detail=(
                "No SuperDocs session."
            ),
        )

    client = get_superdocs_client()

    service = SuperDocsWorkflow(
        client
    )

    try:
        result = await service.export(
            session_id=transmittal.superdocs_session_id,
            html=None,
            format="docx",
            filename=_export_filename(transmittal.number),
        )
    except httpx.HTTPStatusError as error:
        _raise_superdocs_error(error)

    content_base64 = result.get("content_base64")
    if content_base64:
        try:
            content = base64.b64decode(
                content_base64,
                validate=True,
            )
        except (ValueError, TypeError) as error:
            raise HTTPException(
                status_code=502,
                detail="SuperDocs returned invalid DOCX content.",
            ) from error

        EXPORTS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )
        export_path = EXPORTS_DIR / _export_filename(
            transmittal.number
        )
        export_path.write_bytes(content)

    transmittal.export_url = (
        f"/transmittals/{transmittal.id}/download"
    )
    transmittal.status = "EXPORTED"

    db.commit()

    return {
        "transmittal_id": (
            transmittal.id
        ),
        "status": (
            transmittal.status
        ),
        "format": "docx",
        "export": result,
    }


@app.get(
    "/transmittals/{transmittal_id}/download"
)
async def download_transmittal(
    transmittal_id: str,
    db: Session = Depends(get_db),
):
    transmittal = (
        db.query(Transmittal)
        .filter(
            Transmittal.id
            == transmittal_id
        )
        .first()
    )

    if transmittal is None:
        raise HTTPException(
            status_code=404,
            detail="Transmittal not found.",
        )

    if transmittal.status != "EXPORTED":
        raise HTTPException(
            status_code=409,
            detail="Transmittal has not been exported.",
        )

    export_path = EXPORTS_DIR / _export_filename(
        transmittal.number
    )

    if not export_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Exported document not found.",
        )

    return FileResponse(
        path=str(export_path),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=_export_filename(transmittal.number),
    )
