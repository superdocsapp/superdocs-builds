from pathlib import Path
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from redline_engine import RedlineEngine


app = FastAPI(
    title="SuperDocs Contract Redline Desk"
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------

BASE_DIR = Path(__file__).parent

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

WORD_ADDIN_DIR = BASE_DIR / "word-addin"
WORD_SRC_DIR = WORD_ADDIN_DIR / "src"

CONTRACT = DATA_DIR / "sample_contract.docx"
PLAYBOOK = DATA_DIR / "playbook.json"

STATE_FILE = DATA_DIR / "review_state.json"


# ---------------------------------------------------------
# ENGINE
# ---------------------------------------------------------

engine = RedlineEngine(PLAYBOOK)


# ---------------------------------------------------------
# REVIEW STATE
# ---------------------------------------------------------

current_proposals = []


def save_state():
    """Persist the current proposal state to disk."""

    STATE_FILE.parent.mkdir(
        exist_ok=True
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            current_proposals,
            f,
            indent=2
        )


def load_state():

    global current_proposals

    if not STATE_FILE.exists():
        current_proposals = []
        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            current_proposals = json.load(f)

    except Exception:

        current_proposals = []


# Load previous review state when server starts.
load_state()


# ---------------------------------------------------------
# MODELS
# ---------------------------------------------------------

class Decision(BaseModel):

    proposal_id: int
    decision: str


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.get("/")
def home():

    return {
        "app": "SuperDocs Contract Redline Desk",
        "status": "running"
    }


# ---------------------------------------------------------
# WORD ADD-IN
# ---------------------------------------------------------

@app.get("/taskpane.html")
def taskpane():

    return FileResponse(
        WORD_SRC_DIR / "taskpane.html",
        media_type="text/html"
    )


@app.get("/taskpane.js")
def taskpane_js():

    return FileResponse(
        WORD_SRC_DIR / "taskpane.js",
        media_type="application/javascript"
    )


# ---------------------------------------------------------
# REVIEW
# ---------------------------------------------------------

@app.get("/review")
def review_contract():

    global current_proposals

    # If no saved review exists,
    # create a new review.
    if not current_proposals:

        current_proposals = engine.review(
            CONTRACT
        )

        save_state()

    return {
        "contract": CONTRACT.name,
        "proposals": current_proposals
    }


# ---------------------------------------------------------
# APPROVE / REJECT
# ---------------------------------------------------------

@app.post("/decision")
def decide(decision: Decision):

    global current_proposals

    proposal = next(
        (
            p
            for p in current_proposals
            if p["id"] == decision.proposal_id
        ),
        None
    )

    if proposal is None:

        raise HTTPException(
            status_code=404,
            detail="Proposal not found."
        )

    if decision.decision not in {
        "approved",
        "rejected"
    }:

        raise HTTPException(
            status_code=400,
            detail=(
                "Decision must be "
                "approved or rejected."
            )
        )

    proposal["status"] = decision.decision

    save_state()

    return {
        "proposal": proposal,
        "message": (
            f"Proposal {decision.decision}"
        )
    }


# ---------------------------------------------------------
# EXPORT
# ---------------------------------------------------------

@app.post("/export")
def export_contract():

    global current_proposals

    if not current_proposals:

        current_proposals = engine.review(
            CONTRACT
        )

        save_state()

    # -----------------------------------------------------
    # HUMAN GATE
    # -----------------------------------------------------

    pending = [
        proposal
        for proposal in current_proposals
        if proposal["status"] == "pending"
    ]

    if pending:

        raise HTTPException(
            status_code=403,
            detail=(
                "Pending proposals must be "
                "approved or rejected "
                "before export."
            )
        )

    # -----------------------------------------------------
    # EXPORT
    # -----------------------------------------------------

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    output_file = (
        OUTPUT_DIR /
        "redlined_contract.docx"
    )

    engine.apply_approved_changes(
        CONTRACT,
        current_proposals,
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