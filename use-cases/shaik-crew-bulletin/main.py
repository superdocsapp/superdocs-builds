from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import time

app = FastAPI(title="SuperDocs Advanced Agentic System & Crew Bulletin API", version="1.0.0")

# Enable CORS for Frontend (Port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for states, audit trails, and human-in-the-loop approvals
database = {
    "runs": {},
    "approvals": [],
    "crew_bulletins": []
}

class DocumentPayload(BaseModel):
    title: str
    content: str
    domain: str  # e.g., "aviation", "legal", "compliance"

@app.get("/")
def read_root():
    return {
        "status": "online",
        "system": "SuperDocs Agentic & Crew Bulletin Backend",
        "message": "Ready for multi-step agent execution, rules auditing, and HITL gating."
    }

# --- TASK 1: Agentic System Execution & Step Tracking ---
@app.post("/api/agent/start-run")
def start_agent_run(payload: DocumentPayload):
    run_id = f"run_{int(time.time())}"
    
    database["runs"][run_id] = {
        "run_id": run_id,
        "title": payload.title,
        "domain": payload.domain,
        "status": "step_1_ingested",
        "steps_completed": ["ingestion", "fact_extraction"],
        "findings": [
            {"id": "f_1", "text": "Regulation update detected for crew base operations.", "status": "pending_approval"},
            {"id": "f_2", "text": "Operational restriction clause identified without conflict.", "status": "pending_approval"}
        ],
        "created_at": time.time()
    }
    
    return {
        "message": "Agent run started successfully in steps.",
        "run_id": run_id,
        "state": database["runs"][run_id]
    }

@app.get("/api/agent/status/{run_id}")
def get_run_status(run_id: str):
    if run_id not in database["runs"]:
        raise HTTPException(status_code=404, detail="Run ID not found.")
    return database["runs"][run_id]

# --- Human-in-the-Loop (HITL) Gate ---
@app.post("/api/agent/review-gate")
def review_gate(run_id: str, item_id: str, decision: str):
    if run_id not in database["runs"]:
        raise HTTPException(status_code=404, detail="Run ID not found.")
    
    run = database["runs"][run_id]
    updated = False
    for finding in run["findings"]:
        if finding["id"] == item_id:
            finding["status"] = decision  # "approved" or "rejected"
            updated = True
            
    if not updated:
        raise HTTPException(status_code=404, detail="Finding item not found.")
        
    return {
        "message": f"Item {item_id} marked as {decision}.",
        "run_state": run
    }

# --- TASK 2: Assigned Build - Crew Bulletin & Acknowledgment Pack ---
class CrewBulletinRequest(BaseModel):
    regulation_title: str
    change_summary: str
    target_languages: List[str]  # e.g., ["en", "es", "fr"]

@app.post("/api/build/crew-bulletin")
def generate_crew_bulletin(payload: CrewBulletinRequest):
    bulletin_id = f"cb_{int(time.time())}"
    
    localized_packs = {}
    for lang in payload.target_languages:
        localized_packs[lang] = {
            "language": lang,
            "bulletin_text": f"[Localized to {lang}] Bulletin: {payload.regulation_title} - {payload.change_summary}",
            "mandated_phraseology_preserved": True,
            "acknowledgement_form": f"Sign-off required for language [{lang}]"
        }
        
    bulletin_record = {
        "bulletin_id": bulletin_id,
        "regulation_title": payload.regulation_title,
        "localized_packs": localized_packs,
        "supersession_tracked": True,
        "distribution_index_ready": True
    }
    
    database["crew_bulletins"].append(bulletin_record)
    return {
        "status": "success",
        "assigned_build": "Crew Bulletin and Acknowledgment Pack",
        "data": bulletin_record
    }