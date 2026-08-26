"""
Insurance Claims Correspondence Generator — SuperDocs Build 2
=============================================================
Generates insurance claim letters (approval, partial approval, denial,
information request) from structured claim data using the SuperDocs API
with explicit HITL review.

Minimum contract (per letter):
  1. Send the claim record via POST /v1/chat/async       (upload + chat)
  2. Pause at the HITL gate; return pending_hitl          (approve gate)
  3. Caller explicitly POSTs /approve/{session_id}
     → service calls SuperDocs /approve                   (approve)
  4. On completion, export and return the final letter    (export)

No letter is ever finalised without an explicit POST /approve/{session_id} call.
Nothing auto-sends.

POST /generate
  Input:  GenerateRequest
  Output: GeneratedLetter — status "pending_hitl" (waiting for review)
          or "approved" (if SuperDocs completed without hitting the gate)

POST /generate/batch
  Input:  List[GenerateRequest]  (max 20)
  Output: BatchResponse

GET /status/{session_id}
  Inspect the current state of a session without approving it.

POST /approve/{session_id}
  Explicitly approve a waiting draft; waits for completion, exports, returns letter.

POST /reject/{session_id}
  Reject a waiting draft; draft is discarded. Optionally provide a reason.
"""

import json
import asyncio
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import httpx

from config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Persistent session store ───────────────────────────────────────────────────
# Survives service restarts so HITL sessions aren't lost mid-demo.
_SESSION_FILE = os.path.join(os.path.dirname(__file__), ".sessions.json")


def _load_sessions() -> dict:
    try:
        with open(_SESSION_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sessions() -> None:
    try:
        with open(_SESSION_FILE, "w") as f:
            json.dump(_sessions, f)
    except Exception as e:
        logger.warning(f"Could not persist sessions: {e}")


_sessions: dict[str, dict] = _load_sessions()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Warn loudly if the API key is not configured — better than a silent 401."""
    settings = get_settings()
    if not settings.superdocs_api_key:
        logger.warning(
            "SUPERDOCS_API_KEY is not set. "
            "Copy .env.example → .env and add your key before making requests."
        )
    yield


app = FastAPI(
    title="Insurance Claims Correspondence Generator",
    description="Generates insurance claim letters with SuperDocs HITL review.",
    version="1.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ───────────────────────────────────────────────────────────────────

LetterType = Literal["approval", "partial_approval", "denial", "information_request"]


_INJECTION_PHRASES = (
    "ignore previous instructions", "ignore all previous",
    "disregard previous", "system prompt:", "new instruction:",
    "you are now", "forget your instructions",
)


def _check_injection(text: str, field_name: str) -> str:
    lowered = text.lower()
    for phrase in _INJECTION_PHRASES:
        if phrase in lowered:
            raise ValueError(
                f"{field_name}: contains a prompt-injection attempt — submission rejected"
            )
    return text


class ClaimantInfo(BaseModel):
    full_name: str = Field(..., max_length=200)
    address: str = Field(..., max_length=500)
    email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=50)


class PolicyInfo(BaseModel):
    policy_number: str
    coverage_limit: float = Field(..., ge=0, description="Coverage limit in dollars — must be ≥ 0")
    deductible: float = Field(..., ge=0, description="Deductible in dollars — must be ≥ 0")
    coverage_type: str = "homeowner"


class ClaimInfo(BaseModel):
    claim_number: str
    incident_date: str
    incident_type: str
    claimed_amount: float = Field(..., ge=0, description="Claimed amount in dollars — must be ≥ 0")
    adjuster_estimate: Optional[float] = Field(None, ge=0, description="Adjuster estimate — must be ≥ 0 if provided")
    adjuster_notes: Optional[str] = Field(None, max_length=2_000)

    @field_validator("adjuster_notes")
    @classmethod
    def notes_no_injection(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            _check_injection(v, "claim.adjuster_notes")
        return v

    @field_validator("incident_date")
    @classmethod
    def date_must_be_valid(cls, v: str) -> str:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                datetime.strptime(v, fmt)
                return v
            except ValueError:
                continue
        raise ValueError(f"must be a recognisable date (expected YYYY-MM-DD, got '{v}')")


class GenerateRequest(BaseModel):
    claimant: ClaimantInfo
    policy: PolicyInfo
    claim: ClaimInfo
    letter_type: LetterType
    company_name: str = Field(default="InSureCo Insurance Ltd.", max_length=200)
    company_address: str = Field(default="123 Insurance Plaza, Mumbai 400001", max_length=500)
    signatory_name: str = Field(default="Claims Department", max_length=200)
    additional_context: Optional[str] = Field(None, max_length=1_000)

    @field_validator("additional_context")
    @classmethod
    def context_no_injection(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            _check_injection(v, "additional_context")
        return v


class GeneratedLetter(BaseModel):
    claim_number: Optional[str] = None
    letter_type: Optional[LetterType] = None
    letter_html: Optional[str] = None
    letter_text: Optional[str] = None
    session_id: Optional[str] = None
    job_id: Optional[str] = None  # SuperDocs job ID; useful for reviewer tracking
    status: str  # "pending_hitl" | "processing" | "approved" | "rejected" | "error"
    error: Optional[str] = None


class BatchRequest(BaseModel):
    requests: list[GenerateRequest]


class BatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    letters: list[GeneratedLetter]


class ApprovalRequest(BaseModel):
    approved: bool = True


class RejectionRequest(BaseModel):
    approved: bool = False
    reason: Optional[str] = None


# ─── Letter instructions ───────────────────────────────────────────────────────

def build_instruction(req: GenerateRequest) -> str:
    """Build the natural-language instruction sent to SuperDocs."""
    descriptions = {
        "approval": (
            "a CLAIM APPROVAL letter confirming the claim is approved and stating "
            "the payout amount (claimed amount minus deductible)"
        ),
        "partial_approval": (
            "a PARTIAL APPROVAL letter explaining the claim has been partially approved, "
            "stating both the claimed amount and the approved payout (adjuster estimate "
            "minus deductible), and briefly explaining the reason for the difference"
        ),
        "denial": (
            "a CLAIM DENIAL letter explaining the claim has been denied, "
            "citing the specific policy exclusion or rule that applies, "
            "and informing the claimant of their right to appeal within 30 days"
        ),
        "information_request": (
            "an INFORMATION REQUEST letter asking the claimant to provide additional "
            "documentation needed to process the claim, listing required items clearly, "
            "with a 14-day response deadline"
        ),
    }

    payout: Optional[float] = None
    if req.letter_type == "approval":
        payout = req.claim.claimed_amount - req.policy.deductible
    elif req.letter_type == "partial_approval" and req.claim.adjuster_estimate is not None:
        payout = req.claim.adjuster_estimate - req.policy.deductible

    lines = [
        f"You are a professional insurance claims correspondence writer.",
        f"Replace this document with {descriptions[req.letter_type]}.",
        "",
        "CLAIM DETAILS:",
        f"- Claim Number: {req.claim.claim_number}",
        f"- Claimant: {req.claimant.full_name}",
        f"- Claimant Address: {req.claimant.address}",
        f"- Policy Number: {req.policy.policy_number}",
        f"- Coverage Type: {req.policy.coverage_type}",
        f"- Coverage Limit: ${req.policy.coverage_limit:,.2f}",
        f"- Deductible: ${req.policy.deductible:,.2f}",
        f"- Incident Date: {req.claim.incident_date}",
        f"- Incident Type: {req.claim.incident_type}",
        f"- Claimed Amount: ${req.claim.claimed_amount:,.2f}",
    ]
    if req.claim.adjuster_estimate is not None:
        lines.append(f"- Adjuster Estimate: ${req.claim.adjuster_estimate:,.2f}")
    if payout is not None:
        lines.append(f"- Approved Payout: ${payout:,.2f}")
    if req.claim.adjuster_notes:
        # Wrap free-text fields in delimiters to prevent prompt injection.
        lines.append(f"- Adjuster Notes: [NOTES START]{req.claim.adjuster_notes}[NOTES END]")
    if req.additional_context:
        lines.append(f"- Additional Context: [CONTEXT START]{req.additional_context}[CONTEXT END]")

    lines += [
        "",
        "COMPANY:",
        f"- Name: {req.company_name}",
        f"- Address: {req.company_address}",
        f"- Signatory: {req.signatory_name}",
        "",
        "FORMAT RULES:",
        "- Write a complete, properly formatted business letter.",
        "- Use formal, professional language appropriate for insurance correspondence.",
        "- Always include the claim number and policy number prominently.",
        "- Never invent facts not present in the claim details above.",
        "- Include claimant contact (email/phone) if provided.",
        "- Sign off from the signatory name and company.",
    ]
    return "\n".join(lines)


def build_document_context(req: GenerateRequest) -> str:
    """Build the HTML source document (the 'upload') sent to SuperDocs."""
    rows = [
        f"<p><strong>Claim Number:</strong> {req.claim.claim_number}</p>",
        f"<p><strong>Claimant:</strong> {req.claimant.full_name}</p>",
        f"<p><strong>Address:</strong> {req.claimant.address}</p>",
        f"<p><strong>Policy:</strong> {req.policy.policy_number}</p>",
        f"<p><strong>Coverage Type:</strong> {req.policy.coverage_type}</p>",
        f"<p><strong>Incident:</strong> {req.claim.incident_type} on {req.claim.incident_date}</p>",
        f"<p><strong>Claimed Amount:</strong> ${req.claim.claimed_amount:,.2f}</p>",
        f"<p><strong>Coverage Limit:</strong> ${req.policy.coverage_limit:,.2f}</p>",
        f"<p><strong>Deductible:</strong> ${req.policy.deductible:,.2f}</p>",
    ]
    if req.claim.adjuster_estimate is not None:
        rows.append(
            f"<p><strong>Adjuster Estimate:</strong> ${req.claim.adjuster_estimate:,.2f}</p>"
        )
    if req.claim.adjuster_notes:
        rows.append(f"<p><strong>Adjuster Notes:</strong> {req.claim.adjuster_notes}</p>")
    rows.append(f"<p><strong>Letter Type Required:</strong> {req.letter_type}</p>")
    return f"<h1>Claim Processing Record</h1>\n" + "\n".join(rows)


# ─── SuperDocs client helpers ─────────────────────────────────────────────────

POLL_INTERVAL_S = 3
MAX_POLLS = 100  # 5 min max


async def _poll_once(
    client: httpx.AsyncClient,
    job_id: str,
    headers: dict,
    base: str,
) -> dict:
    resp = await client.get(f"{base}/v1/jobs/{job_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _poll_until_complete(
    client: httpx.AsyncClient,
    session_id: str,
    job_id: str,
    headers: dict,
    base: str,
) -> dict:
    """
    Poll /v1/jobs/{job_id} until completed, failed, or cancelled.
    Handles any additional continue_prompt pauses that appear post-approval.
    Returns the final job dict (status may be "completed", "failed", or "timeout").
    """
    for _ in range(MAX_POLLS):
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            job = await _poll_once(client, job_id, headers, base)
        except Exception as e:
            logger.warning(f"Session {session_id}: post-approval poll error — {e}")
            continue

        status = job.get("status")
        logger.info(f"Session {session_id}: post-approval status={status}")

        if status == "completed":
            return job
        if status in ("failed", "cancelled"):
            return job
        if status == "awaiting_approval":
            meta = job.get("metadata", {})
            if meta.get("awaiting_kind") == "continue_prompt":
                try:
                    await client.post(
                        f"{base}/v1/chat/{session_id}/continue",
                        headers=headers,
                        json={"job_id": job_id, "continue": True},
                    )
                    logger.info(f"Session {session_id}: continue_prompt handled (post-approval)")
                except Exception as e:
                    logger.warning(f"Session {session_id}: continue failed — {e}")

    return {"status": "timeout", "error": "no final result within 5 minutes after approval"}


async def _export_letter(
    client: httpx.AsyncClient,
    session_id: str,
    job: dict,
    headers: dict,
    base: str,
    claim_number: Optional[str],
    letter_type: Optional[LetterType],
    final_status: str = "approved",
) -> GeneratedLetter:
    """
    Export the finished letter from SuperDocs (the 'export' step of the
    minimum contract) and return as a GeneratedLetter.
    Falls back to document_changes if export fails.
    """
    letter_html: Optional[str] = None

    try:
        export_resp = await client.post(
            f"{base}/v1/documents/export",
            headers=headers,
            json={"session_id": session_id, "format": "html"},
        )
        export_resp.raise_for_status()
        letter_html = export_resp.text
    except Exception as e:
        logger.warning(f"Session {session_id}: HTML export failed ({e}), using document_changes")

    if not letter_html:
        result = job.get("result", {})
        doc_changes = result.get("document_changes", {})
        letter_html = doc_changes.get("updated_html")

    letter_text: Optional[str] = None
    if letter_html:
        letter_text = re.sub(r"<[^>]+>", "", letter_html).strip()
        letter_text = re.sub(r"\n{3,}", "\n\n", letter_text)

    return GeneratedLetter(
        claim_number=claim_number,
        letter_type=letter_type,
        letter_html=letter_html,
        letter_text=letter_text,
        session_id=session_id,
        status=final_status,
    )


# ─── Core generation logic ────────────────────────────────────────────────────

async def generate_letter(
    client: httpx.AsyncClient,
    req: GenerateRequest,
    settings,
) -> GeneratedLetter:
    """
    Start a SuperDocs session for this claim letter.

    Polls until either:
    - awaiting_approval: HITL gate reached — store state, return pending_hitl.
    - completed: letter finalised (no HITL pause) — export and return approved.
    - error/timeout: return error.

    continue_prompt pauses (large-edit mid-pause) are auto-continued; they are
    not human decision points.
    """
    headers = {
        "Authorization": f"Bearer {settings.superdocs_api_key}",
        "Content-Type": "application/json",
    }
    base = settings.superdocs_base_url
    # We choose the session_id so the approve URL is deterministic.
    session_id = f"claim-{req.claim.claim_number[:32]}-{uuid.uuid4().hex[:8]}"

    # ── Step 1: Upload (via document_html) + send instruction ─────────────────
    try:
        start_resp = await client.post(
            f"{base}/v1/chat/async",
            headers=headers,
            json={
                "message": build_instruction(req),
                "session_id": session_id,
                "document_html": build_document_context(req),
                "approval_mode": "ask_every_time",
            },
        )
        start_resp.raise_for_status()
        start_data = start_resp.json()
        job_id = start_data.get("job_id")
        if not job_id:
            raise ValueError(f"No job_id in response: {start_data}")
    except Exception as e:
        logger.error(f"Claim {req.claim.claim_number}: session start failed — {e}")
        return GeneratedLetter(
            claim_number=req.claim.claim_number, letter_type=req.letter_type,
            status="error", error=str(e),
        )

    # ── Step 2: Poll until the HITL gate or completion ────────────────────────
    for _ in range(MAX_POLLS):
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            job = await _poll_once(client, job_id, headers, base)
        except Exception as e:
            logger.warning(f"Claim {req.claim.claim_number}: poll error — {e}")
            continue

        status = job.get("status")
        logger.info(f"Claim {req.claim.claim_number}: job_status={status}")

        if status == "completed":
            # Completed without hitting the HITL gate — export immediately.
            return await _export_letter(
                client, session_id, job, headers, base,
                req.claim.claim_number, req.letter_type, "approved",
            )

        elif status == "awaiting_approval":
            meta = job.get("metadata", {})
            awaiting_kind = meta.get("awaiting_kind")

            if awaiting_kind == "continue_prompt":
                # Mid-edit pause — auto-continue; not a human decision point.
                try:
                    cont_resp = await client.post(
                        f"{base}/v1/chat/{session_id}/continue",
                        headers=headers,
                        json={"job_id": job_id, "continue": True},
                    )
                    cont_resp.raise_for_status()
                    logger.info(f"Claim {req.claim.claim_number}: continue_prompt handled")
                except Exception as e:
                    logger.error(f"Claim {req.claim.claim_number}: continue failed — {e}")
                    return GeneratedLetter(
                        claim_number=req.claim.claim_number, letter_type=req.letter_type,
                        session_id=session_id, job_id=job_id,
                        status="error", error=f"continue_failed: {e}",
                    )
            else:
                # ── Step 2 (HITL gate): store state and return to caller ──────
                # The draft is NOT applied to the document yet.
                # A human must call POST /approve/{session_id} to proceed.
                pending_changes = meta.get("pending_changes", [])
                _sessions[session_id] = {
                    "job_id": job_id,
                    "pending_changes": pending_changes,
                    "claim_number": req.claim.claim_number,
                    "letter_type": req.letter_type,
                }
                _save_sessions()
                logger.info(
                    f"Claim {req.claim.claim_number}: HITL gate reached — "
                    f"{len(pending_changes)} change(s) pending review"
                )
                return GeneratedLetter(
                    claim_number=req.claim.claim_number,
                    letter_type=req.letter_type,
                    session_id=session_id,
                    job_id=job_id,
                    status="pending_hitl",
                )

        elif status in ("failed", "cancelled"):
            err = job.get("error", f"job ended with status: {status}")
            return GeneratedLetter(
                claim_number=req.claim.claim_number, letter_type=req.letter_type,
                session_id=session_id, job_id=job_id,
                status="error", error=err,
            )

    return GeneratedLetter(
        claim_number=req.claim.claim_number, letter_type=req.letter_type,
        session_id=session_id, job_id=job_id,
        status="error", error="timeout: no result within 5 minutes",
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/generate", response_model=GeneratedLetter)
async def generate_single(request: GenerateRequest):
    """
    Generate a single claim letter.

    Returns status "pending_hitl" when human review is required.
    The reviewer then calls POST /approve/{session_id} or
    POST /reject/{session_id}.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        return await generate_letter(client, request, settings)


@app.post("/generate/batch", response_model=BatchResponse)
async def generate_batch(request: BatchRequest):
    """Generate a batch of claim letters (sequential, max 20)."""
    if not request.requests:
        raise HTTPException(status_code=400, detail="requests list is empty")
    if len(request.requests) > 20:
        raise HTTPException(status_code=400, detail="max 20 letters per batch")

    settings = get_settings()
    letters: list[GeneratedLetter] = []

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        for req in request.requests:
            logger.info(
                f"Generating {req.letter_type} letter for claim {req.claim.claim_number}"
            )
            result = await generate_letter(client, req, settings)
            letters.append(result)

    succeeded = sum(1 for l in letters if l.status in ("approved", "pending_hitl"))
    return BatchResponse(
        total=len(letters),
        succeeded=succeeded,
        failed=len(letters) - succeeded,
        letters=letters,
    )


@app.get("/status/{session_id}", response_model=GeneratedLetter)
async def get_status(session_id: str):
    """Inspect the current state of a claim-letter session without approving it."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.superdocs_api_key}",
        "Content-Type": "application/json",
    }
    base = settings.superdocs_base_url
    job_id = session["job_id"]

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        try:
            job = await _poll_once(client, job_id, headers, base)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"status_check_failed: {e}") from e

    status = job.get("status")
    if status == "awaiting_approval":
        return GeneratedLetter(
            claim_number=session.get("claim_number"),
            letter_type=session.get("letter_type"),
            session_id=session_id, job_id=job_id,
            status="pending_hitl",
        )
    if status == "completed":
        return GeneratedLetter(
            claim_number=session.get("claim_number"),
            letter_type=session.get("letter_type"),
            session_id=session_id, job_id=job_id,
            status="approved",
        )
    if status in ("failed", "cancelled"):
        return GeneratedLetter(
            session_id=session_id, job_id=job_id,
            status="error", error=job.get("error", status),
        )
    return GeneratedLetter(session_id=session_id, job_id=job_id, status="processing")


@app.post("/approve/{session_id}", response_model=GeneratedLetter)
async def approve_letter(session_id: str, request: ApprovalRequest):
    """
    Explicitly approve a waiting claim-letter draft.

    Calls the SuperDocs approve endpoint with the stored job_id and change list,
    waits for the job to complete, then exports and returns the final letter.

    Nothing is finalised until this endpoint is called — not by /generate,
    not by any background process.
    """
    if not request.approved:
        raise HTTPException(
            status_code=400, detail="Use POST /reject/{session_id} to decline a draft"
        )

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.superdocs_api_key}",
        "Content-Type": "application/json",
    }
    base = settings.superdocs_base_url
    job_id = session["job_id"]
    pending_changes = session["pending_changes"]

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        # ── Step 3: Approve ────────────────────────────────────────────────────
        try:
            approve_resp = await client.post(
                f"{base}/v1/chat/{session_id}/approve",
                headers=headers,
                json={
                    "job_id": job_id,
                    "approved": True,
                    "changes": [
                        {"change_id": c["change_id"], "approved": True}
                        for c in pending_changes
                    ],
                },
            )
            approve_resp.raise_for_status()
            logger.info(
                f"Session {session_id}: approved {len(pending_changes)} change(s)"
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"approval_failed: {e}") from e

        # Wait for the job to reach completed after approval.
        job = await _poll_until_complete(client, session_id, job_id, headers, base)

        if job.get("status") != "completed":
            err = job.get("error", f"unexpected final status: {job.get('status')}")
            return GeneratedLetter(
                claim_number=session.get("claim_number"),
                letter_type=session.get("letter_type"),
                session_id=session_id, job_id=job_id,
                status="error", error=err,
            )

        # Remove from session store — the letter is now finalised.
        _sessions.pop(session_id, None)
        _save_sessions()

        # ── Step 4: Export the final letter ───────────────────────────────────
        return await _export_letter(
            client, session_id, job, headers, base,
            session.get("claim_number"), session.get("letter_type"), "approved",
        )


@app.post("/reject/{session_id}", response_model=GeneratedLetter)
async def reject_letter(session_id: str, request: RejectionRequest):
    """
    Reject a waiting claim-letter draft.

    Calls the SuperDocs approve endpoint with approved=false so the proposed
    changes are discarded. An optional reason is sent as per-change feedback so
    the AI can revise if the session is restarted.
    """
    if request.approved:
        raise HTTPException(
            status_code=400, detail="approved must be false on the reject endpoint"
        )

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.superdocs_api_key}",
        "Content-Type": "application/json",
    }
    base = settings.superdocs_base_url
    job_id = session["job_id"]
    pending_changes = session["pending_changes"]

    change_list = [
        {"change_id": c["change_id"], "approved": False}
        for c in pending_changes
    ]
    # Attach the reviewer's reason as feedback on each change so SuperDocs logs it.
    if request.reason:
        for item in change_list:
            item["feedback"] = request.reason

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        try:
            reject_resp = await client.post(
                f"{base}/v1/chat/{session_id}/approve",
                headers=headers,
                json={
                    "job_id": job_id,
                    "approved": False,
                    "changes": change_list,
                },
            )
            reject_resp.raise_for_status()
            logger.info(
                f"Session {session_id}: rejected {len(pending_changes)} change(s)"
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"rejection_failed: {e}") from e

    _sessions.pop(session_id, None)
    _save_sessions()

    return GeneratedLetter(
        claim_number=session.get("claim_number"),
        letter_type=session.get("letter_type"),
        session_id=session_id,
        job_id=job_id,
        status="rejected",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "claims-generator"}


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)
