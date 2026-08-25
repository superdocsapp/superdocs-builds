"""
EngageFlow FastAPI Main Application Server
Integrates SuperDocs Client, Document Extractor, State Comparator, and Report Generator into REST endpoints.
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from typing import List, Dict, Any, Optional
import os
import shutil

from app.models import ProjectState
from app.superdocs_client import SuperDocsClient
from app.services.extractor import DocumentExtractor
from app.services.comparator import StateComparator
from app.services.generator import ReportGenerator

app = FastAPI(
    title="EngageFlow API",
    description="Steering Committee Report Automation Engine built on SuperDocs API",
    version="1.0.0"
)

# Enable CORS for Next.js frontend (localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"

superdocs_client = SuperDocsClient()
extractor = DocumentExtractor()
comparator = StateComparator()
generator = ReportGenerator()

@app.get("/health")
def health_check():
    """Health check for EngageFlow backend and SuperDocs API connection."""
    superdocs_status = "connected"
    try:
        sd_health = superdocs_client.health_check()
    except Exception as e:
        superdocs_status = f"disconnected ({str(e)})"

    return {
        "status": "healthy",
        "service": "EngageFlow Backend",
        "superdocs_api": superdocs_status
    }

@app.get("/api/periods")
def list_available_periods():
    """Lists available sample data periods."""
    periods = []
    if SAMPLE_DATA_DIR.exists():
        for pdir in sorted(SAMPLE_DATA_DIR.glob("period_*")):
            periods.append({
                "period_id": pdir.name,
                "name": pdir.name.replace("_", " ").title(),
                "file_count": len(list(pdir.glob("*.md")))
            })
    return {"periods": periods}

@app.post("/api/generate-report")
def generate_engagement_report(payload: Dict[str, Any] = Body(...)):
    """
    Core EngageFlow Pipeline Endpoint:
    1. Loads current period documents (e.g. period_2) & previous report (period_1).
    2. Uploads documents to live SuperDocs API.
    3. Creates a SuperDocs analysis run.
    4. Extracts current & previous project state.
    5. Computes period-over-period movements (delta engine).
    6. Synthesizes Steering Committee Report.
    7. Returns generated report, project state, and SuperDocs run metadata.
    """
    current_period = payload.get("current_period", "period_2")
    previous_period = payload.get("previous_period", "period_1")

    curr_path = SAMPLE_DATA_DIR / current_period
    prev_path = SAMPLE_DATA_DIR / previous_period

    if not curr_path.exists():
        raise HTTPException(status_code=404, detail=f"Current period folder {current_period} not found.")

    # Extract states
    curr_state = extractor.extract_from_folder(curr_path, f"{current_period.replace('_', ' ').title()}")
    prev_state = extractor.extract_from_folder(prev_path, f"{previous_period.replace('_', ' ').title()}") if prev_path.exists() else curr_state

    # Derive movements
    compared_state = comparator.compare_states(prev_state, curr_state)

    # Generate Steering Committee Report
    report_md = generator.generate_report(compared_state)

    # SuperDocs Integration
    uploaded_doc_ids = []
    superdocs_run = None
    try:
        # Upload docx versions to SuperDocs
        for docx_file in curr_path.glob("*.docx"):
            up_res = superdocs_client.upload_document(docx_file)
            if "id" in up_res:
                uploaded_doc_ids.append(up_res["id"])

        if uploaded_doc_ids:
            superdocs_run = superdocs_client.create_run(uploaded_doc_ids)
    except Exception as e:
        print(f"Warning: SuperDocs integration step encountered issue: {e}")

    return {
        "success": True,
        "project_name": compared_state.project_name,
        "overall_status": compared_state.overall_status,
        "report_markdown": report_md,
        "compared_state": compared_state.model_dump(),
        "superdocs_integration": {
            "uploaded_doc_ids": uploaded_doc_ids,
            "superdocs_run": superdocs_run
        }
    }

@app.post("/api/superdocs/approve")
def approve_superdocs_finding(payload: Dict[str, Any] = Body(...)):
    """Approves a finding in SuperDocs run."""
    run_id = payload.get("run_id")
    finding_id = payload.get("finding_id")
    if not run_id or not finding_id:
        raise HTTPException(status_code=400, detail="Missing run_id or finding_id")

    try:
        res = superdocs_client.approve_finding(run_id, finding_id)
        return {"success": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/superdocs/finalize")
def finalize_superdocs_run(payload: Dict[str, Any] = Body(...)):
    """Finalizes human review process in SuperDocs run."""
    run_id = payload.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id")

    try:
        res = superdocs_client.finalize_run(run_id)
        return {"success": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
