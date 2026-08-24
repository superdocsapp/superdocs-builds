from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from redline_engine import RedlineEngine


app = FastAPI(title="SuperDocs Contract Redline Desk")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

CONTRACT = DATA_DIR / "sample_contract.docx"
PLAYBOOK = DATA_DIR / "playbook.json"

engine = RedlineEngine(PLAYBOOK)


class Decision(BaseModel):
    proposal_id: int
    decision: str


@app.get("/")
def home():
    return {
        "app": "SuperDocs Contract Redline Desk",
        "status": "running"
    }


@app.get("/review")
def review_contract():

    proposals = engine.review(CONTRACT)

    return {
        "contract": CONTRACT.name,
        "proposals": proposals
    }


@app.post("/decision")
def decide(decision: Decision):

    proposals = engine.review(CONTRACT)

    proposal = next(
        (
            p for p in proposals
            if p["id"] == decision.proposal_id
        ),
        None
    )

    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found"
        )

    if decision.decision not in {"approved", "rejected"}:
        raise HTTPException(
            status_code=400,
            detail="Decision must be approved or rejected"
        )

    proposal["status"] = decision.decision

    return {
        "proposal": proposal,
        "message": f"Proposal {decision.decision}"
    }


@app.post("/export")
def export_contract():

    proposals = engine.review(CONTRACT)

    # SECURITY / HUMAN-GATE CHECK
    # Nothing is exported unless explicitly approved.
    if any(
        proposal["status"] == "pending"
        for proposal in proposals
    ):
        raise HTTPException(
            status_code=403,
            detail="Pending proposals must be approved or rejected before export."
        )

    OUTPUT_DIR.mkdir(exist_ok=True)

    output_file = OUTPUT_DIR / "redlined_contract.docx"

    engine.apply_approved_changes(
        CONTRACT,
        proposals,
        output_file
    )

    return FileResponse(
        output_file,
        filename="redlined_contract.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    )