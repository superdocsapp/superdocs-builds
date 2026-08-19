import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .superdocs_client import SuperDocsClient
from .policy_builder import (
    build_policy_document,
    build_endorsement_instruction,
)


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="InsureCraft",
    description="Insurance Policy and Endorsement Builder",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SUPERDOCS CLIENT
# ============================================================

client = SuperDocsClient()


# ============================================================
# MODELS
# ============================================================


class PolicyRequest(BaseModel):
    named_insured: str
    policy_number: str
    territory: str

    effective_date: str = ""
    expiry_date: str = ""

    liability_limit: str
    deductible: str

    coverage_forms: list[str] = Field(
        default_factory=list
    )

    endorsements: list[str] = Field(
        default_factory=list
    )


class ReviewRequest(BaseModel):
    document_html: str
    instruction: str


class ApprovalChange(BaseModel):
    change_id: str | None = None
    approved: bool
    feedback: str = ""


class ApprovalRequest(BaseModel):
    session_id: str
    job_id: str
    approved: bool

    changes: list[ApprovalChange] = Field(
        default_factory=list
    )


class EndorsementRequest(BaseModel):
    endorsement_name: str
    existing_wording: str
    amendment_instruction: str


# ============================================================
# HEALTH
# ============================================================


@app.get("/")
def root():
    return {
        "application": "InsureCraft",
        "status": "running",
        "description": (
            "Insurance Policy and Endorsement Builder"
        ),
    }


@app.get("/health")
def health():

    try:
        result = client.get_sessions()

        return {
            "status": "healthy",
            "superdocs": "connected",
            "sessions": result,
        }

    except Exception as exc:

        print(
            "SuperDocs health check failed:",
            repr(exc),
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "SuperDocs connection failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# POLICY BUILD
# ============================================================


@app.post("/policy/build")
def build_policy(request: PolicyRequest):

    try:

        # ----------------------------------------
        # Basic validation
        # ----------------------------------------

        if not request.named_insured.strip():
            raise HTTPException(
                status_code=400,
                detail="Named insured is required.",
            )

        if not request.policy_number.strip():
            raise HTTPException(
                status_code=400,
                detail="Policy number is required.",
            )

        if not request.territory.strip():
            raise HTTPException(
                status_code=400,
                detail="Territory is required.",
            )

        if not request.liability_limit.strip():
            raise HTTPException(
                status_code=400,
                detail="Liability limit is required.",
            )

        if not request.deductible.strip():
            raise HTTPException(
                status_code=400,
                detail="Deductible is required.",
            )

        # ----------------------------------------
        # Build document
        # ----------------------------------------

        html = build_policy_document(
            request.model_dump()
        )

        if not html or not html.strip():
            raise HTTPException(
                status_code=500,
                detail=(
                    "Policy builder returned "
                    "empty document HTML."
                ),
            )

        return {
            "status": "success",
            "document_html": html,
        }

    except HTTPException:
        raise

    except Exception as exc:

        print(
            "Policy build error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Policy build failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# POLICY REVIEW
# ============================================================


@app.post("/policy/review")
def review_policy(request: ReviewRequest):

    # ----------------------------------------
    # Validate request
    # ----------------------------------------

    if not request.document_html.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Document HTML cannot be empty."
            ),
        )

    if not request.instruction.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Review instruction cannot be empty."
            ),
        )

    # ----------------------------------------
    # Create a unique session
    # ----------------------------------------

    session_id = (
        f"insurecraft-{uuid.uuid4()}"
    )

    print("================================")
    print("INSURECRAFT POLICY REVIEW")
    print("Session:", session_id)
    print(
        "Document HTML length:",
        len(request.document_html),
    )
    print(
        "Instruction:",
        request.instruction,
    )
    print("================================")

    try:

        # ----------------------------------------
        # Send document to SuperDocs
        # ----------------------------------------

        result = client.chat_async(
            message=request.instruction,
            session_id=session_id,
            document_html=request.document_html,
            approval_mode="ask_every_time",
        )

        print(
            "SuperDocs review response:",
            result,
        )

        if not isinstance(result, dict):

            raise RuntimeError(
                "SuperDocs returned an invalid response."
            )

        # ----------------------------------------
        # Return result to task pane
        # ----------------------------------------

        return {
            **result,
            "session_id": session_id,
        }

    except HTTPException:
        raise

    except Exception as exc:

        print(
            "SuperDocs review error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "SuperDocs review failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# JOB STATUS
# ============================================================


@app.get("/jobs/{session_id}")
def job_status(session_id: str):

    if not session_id.strip():

        raise HTTPException(
            status_code=400,
            detail="Session ID is required.",
        )

    print("================================")
    print("GET JOB STATUS")
    print("Session:", session_id)
    print("================================")

    try:

        result = client.get_session_jobs(
            session_id=session_id
        )

        return result

    except Exception as exc:

        print(
            "Job status error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not retrieve SuperDocs "
                f"job status: {str(exc)}"
            ),
        )


# ============================================================
# APPROVAL
# ============================================================


@app.post("/approve")
def approve(request: ApprovalRequest):

    if not request.session_id.strip():

        raise HTTPException(
            status_code=400,
            detail="Session ID is required.",
        )

    if not request.job_id.strip():

        raise HTTPException(
            status_code=400,
            detail="Job ID is required.",
        )

    print("================================")
    print("SUPERDOCS APPROVAL")
    print("Session:", request.session_id)
    print("Job:", request.job_id)
    print("Approved:", request.approved)
    print(
        "Number of changes:",
        len(request.changes),
    )
    print("================================")

    try:

        # ----------------------------------------
        # Forward only valid change IDs
        # ----------------------------------------

        changes = []

        for change in request.changes:

            if not change.change_id:
                continue

            changes.append(
                {
                    "change_id": change.change_id,
                    "approved": change.approved,
                    "feedback": change.feedback,
                }
            )

        print(
            "Changes being forwarded:",
            changes,
        )

        # ----------------------------------------
        # Send approval to SuperDocs
        # ----------------------------------------

        result = client.approve_changes(
            session_id=request.session_id,
            job_id=request.job_id,
            approved=request.approved,
            changes=changes,
        )

        print(
            "SuperDocs approval response:",
            result,
        )

        if not isinstance(result, dict):

            raise RuntimeError(
                "SuperDocs returned an invalid "
                "approval response."
            )

        return result

    except HTTPException:
        raise

    except Exception as exc:

        print(
            "Approval error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "SuperDocs approval failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# ENDORSEMENT
# ============================================================


@app.post("/endorsement/draft")
def draft_endorsement(
    request: EndorsementRequest
):

    # ----------------------------------------
    # Validate input
    # ----------------------------------------

    if not request.endorsement_name.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Endorsement name is required."
            ),
        )

    if not request.existing_wording.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Existing wording is required."
            ),
        )

    if not request.amendment_instruction.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Amendment instruction is required."
            ),
        )

    # ----------------------------------------
    # Build SuperDocs instruction
    # ----------------------------------------

    instruction = build_endorsement_instruction(
        endorsement_name=request.endorsement_name,
        existing_wording=request.existing_wording,
        amendment_instruction=(
            request.amendment_instruction
        ),
    )

    # ----------------------------------------
    # Create session
    # ----------------------------------------

    session_id = (
        "insurecraft-endorsement-"
        f"{uuid.uuid4()}"
    )

    print("================================")
    print("INSURECRAFT ENDORSEMENT")
    print("Session:", session_id)
    print(
        "Endorsement:",
        request.endorsement_name,
    )
    print("================================")

    try:

        result = client.chat_async(
            message=instruction,
            session_id=session_id,
            document_html=request.existing_wording,
            approval_mode="ask_every_time",
        )

        print(
            "SuperDocs endorsement response:",
            result,
        )

        if not isinstance(result, dict):

            raise RuntimeError(
                "SuperDocs returned an invalid "
                "endorsement response."
            )

        return {
            **result,
            "session_id": session_id,
        }

    except HTTPException:
        raise

    except Exception as exc:

        print(
            "Endorsement error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "SuperDocs endorsement failed: "
                f"{str(exc)}"
            ),
        )


# ============================================================
# EXPORT
# ============================================================


@app.post("/export/{session_id}")
def export_document(session_id: str):

    if not session_id.strip():

        raise HTTPException(
            status_code=400,
            detail="Session ID is required.",
        )

    print("================================")
    print("SUPERDOCS EXPORT")
    print("Session:", session_id)
    print("================================")

    try:

        result = client.export_document(
            session_id=session_id
        )

        print(
            "Export response:",
            result,
        )

        if not isinstance(result, dict):

            raise RuntimeError(
                "SuperDocs returned an invalid "
                "export response."
            )

        return result

    except HTTPException:
        raise

    except Exception as exc:

        print(
            "Export error:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "SuperDocs export failed: "
                f"{str(exc)}"
            ),
        )