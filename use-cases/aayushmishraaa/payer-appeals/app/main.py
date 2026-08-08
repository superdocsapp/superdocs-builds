"""Payer appeals — draft an insurance appeal letter, gated by a human.

The flow, and the reason for each step:

    denial reason + clinical fact
        -> relevance check          does the fact actually answer this denial?
        -> upload letter template   the house format, not something the model invents
        -> chat/async               approval_mode=ask_every_time, so nothing self-applies
        -> poll                     until a human decision is required
        -> REVIEW                   every proposed change shown with before/after
        -> approve or reject        item by item
        -> export .docx             only what a person approved

Everything here is fictional. Payers, members and clinical details are invented, and the UI
says so in a banner that cannot be dismissed. Real PHI must never be pasted into this.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import grounding
from .superdocs import ProposedChange, SuperDocs, SuperDocsError
from .template import appeal_template_html, build_instruction

HERE = Path(__file__).parent
WEB = HERE.parent / "web"

app = FastAPI(
    title="Payer Appeals",
    description="Draft insurance appeal letters from a denial reason and a clinical fact, "
                "with human approval before anything is exported.",
    version="0.1.0",
)

# In-memory. This is a demo, and persisting fabricated clinical text buys nothing — but note
# it means a restart loses in-flight drafts. Named here rather than discovered later.
DRAFTS: dict[str, dict[str, Any]] = {}


class DraftRequest(BaseModel):
    denial_reason: str = Field(
        ...,
        min_length=3,
        description="The payer's stated ground for denial. Fictional only.",
        examples=["CARC 197 — prior authorization/precertification absent"],
    )
    clinical_fact: str = Field(
        ...,
        min_length=3,
        description="The single clinical fact offered in rebuttal. Fictional only.",
        examples=["Prior authorization PA-2026-8823 was obtained on 2026-02-19 and was valid "
                  "on the date of service."],
    )
    patient_name: str = "Dolores Ashby"
    member_id: str = "MHP-4471902"
    claim_id: str = "CLM-2026-0417"
    payer_name: str = "Meridian Health Plan"
    provider_name: str = "Northgate Orthopaedic Associates"


class Decision(BaseModel):
    change_id: str
    approved: bool
    feedback: str = ""


class DecideRequest(BaseModel):
    decisions: list[Decision] = Field(min_length=1)
    reviewer: str = "reviewer"


def _client() -> SuperDocs:
    try:
        return SuperDocs()
    except SuperDocsError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "api_key_configured": bool(os.environ.get("SUPERDOCS_API_KEY")),
        "notice": "All data in this demo is fictional. Do not enter real patient information.",
    }


@app.post("/api/drafts")
async def create_draft(req: DraftRequest) -> dict[str, Any]:
    """Draft an appeal. Returns proposed changes awaiting a human decision."""
    client = _client()

    # Relevance is checked BEFORE drafting, and the answer travels with the draft. A model
    # asked to appeal a prior-auth denial using an unrelated clinical note will write a
    # confident letter and invent the connection; the reviewer needs to know that up front,
    # not discover it in the prose.
    relevance = grounding.check(req.denial_reason, req.clinical_fact)

    draft_id = uuid.uuid4().hex[:12]
    session_id = f"appeal-{draft_id}"

    template = appeal_template_html(
        patient_name=req.patient_name,
        member_id=req.member_id,
        claim_id=req.claim_id,
        payer_name=req.payer_name,
        provider_name=req.provider_name,
    )

    instruction = build_instruction(
        denial_reason=req.denial_reason,
        clinical_fact=req.clinical_fact,
        relevance=relevance,
    )

    try:
        started = await client.start_edit(session_id, instruction, document_html=template)
    except SuperDocsError as exc:
        if exc.is_session_busy:
            await client.clear_wedged_session(session_id)
            started = await client.start_edit(session_id, instruction, document_html=template)
        else:
            raise HTTPException(502, f"SuperDocs rejected the draft request: {exc}") from exc

    job_id = started.get("job_id", "")
    job = await client.wait_for_review(job_id)

    pending = [
        ProposedChange.from_api(c)
        for c in (job.get("metadata") or {}).get("pending_changes") or []
    ]

    # A concrete number, date or dosage that appears in the letter but in none of the inputs
    # is exactly what a payer will check and a clinician will be asked to stand behind.
    drafted_text = " ".join(c.new_html for c in pending)
    invented = grounding.unsupported_specifics(
        drafted_text, req.denial_reason, req.clinical_fact, template
    )

    DRAFTS[draft_id] = {
        "draft_id": draft_id,
        "session_id": session_id,
        "job_id": job_id,
        "request": req.model_dump(),
        "status": job.get("status"),
    }

    return {
        "draft_id": draft_id,
        "session_id": session_id,
        "job_id": job_id,
        "status": job.get("status"),
        "relevance": {
            "verdict": relevance.verdict.value,
            "reason": relevance.reason,
            "warn": relevance.should_warn,
        },
        "unsupported_specifics": invented,
        "changes": [
            {
                "change_id": c.change_id,
                "operation": c.operation,
                "old_html": c.old_html,
                "new_html": c.new_html,
                "explanation": c.explanation,
            }
            for c in pending
        ],
    }


@app.post("/api/drafts/{draft_id}/decide")
async def decide(draft_id: str, req: DecideRequest) -> dict[str, Any]:
    """THE GATE. Approve or reject each proposed change individually."""
    draft = DRAFTS.get(draft_id)
    if not draft:
        raise HTTPException(404, f"no draft {draft_id!r}")

    client = _client()
    try:
        await client.decide(
            draft["session_id"],
            draft["job_id"],
            [
                {"change_id": d.change_id, "approved": d.approved, "feedback": d.feedback}
                for d in req.decisions
            ],
        )
    except SuperDocsError as exc:
        raise HTTPException(502, str(exc)) from exc

    job = await client.wait_for_review(draft["job_id"])
    draft["status"] = job.get("status")
    draft["decided_by"] = req.reviewer

    # A large edit comes back in several rounds. If more changes are pending, the reviewer is
    # not finished — say so rather than letting them believe they have approved everything.
    more = [
        ProposedChange.from_api(c)
        for c in (job.get("metadata") or {}).get("pending_changes") or []
    ]
    return {
        "draft_id": draft_id,
        "status": draft["status"],
        "approved": sum(1 for d in req.decisions if d.approved),
        "rejected": sum(1 for d in req.decisions if not d.approved),
        "further_review_required": bool(more),
        "changes": [
            {
                "change_id": c.change_id,
                "operation": c.operation,
                "old_html": c.old_html,
                "new_html": c.new_html,
                "explanation": c.explanation,
            }
            for c in more
        ],
    }


@app.get("/api/drafts/{draft_id}/export")
async def export(draft_id: str, fmt: str = "docx") -> Response:
    """Export the approved letter. Refuses while a decision is still outstanding."""
    draft = DRAFTS.get(draft_id)
    if not draft:
        raise HTTPException(404, f"no draft {draft_id!r}")

    if draft.get("status") == "awaiting_approval":
        # The gate, enforced on the way out as well as on the way in. An export that
        # silently included un-reviewed edits would make the whole review decorative.
        raise HTTPException(
            409,
            "This draft is still awaiting a decision. Approve or reject the outstanding "
            "changes before exporting — nothing leaves here unreviewed.",
        )

    client = _client()
    try:
        content, filename, content_type = await client.export(draft["session_id"], fmt)
    except SuperDocsError as exc:
        raise HTTPException(502, str(exc)) from exc

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


if WEB.exists():
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")
