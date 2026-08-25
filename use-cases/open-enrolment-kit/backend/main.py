from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import glob
import logging
import threading
import time
import uuid
import json
import requests
from dotenv import load_dotenv

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from database import init_db, save_document
from services import generate_superdocs_instructions
from models import JobApprovalRequest

from agent_graph import app as graph_app

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SuperDocs Open-Enrolment Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPERDOCS_API_KEY = os.getenv("SUPERDOCS_API_KEY")
SUPERDOCS_BASE_URL = "https://api.superdocs.app"

def get_sd_headers():
    return {
        "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
        "Content-Type": "application/json"
    }

class DocumentHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            logger.info(f"New document detected (incremental update): {event.src_path}")
            doc_id = "doc_" + str(uuid.uuid4())[:8]
            save_document(doc_id, event.src_path, "ingested")
            
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            logger.info(f"Document modified (incremental update): {event.src_path}")
            pass

def start_watcher():
    observer = Observer()
    data_path = os.path.join(os.path.dirname(__file__), "../data")
    observer.schedule(DocumentHandler(), data_path, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        logger.error(f"Watcher stopped: {e}")
        observer.stop()
    observer.join()

@app.on_event("startup")
def on_startup():
    init_db()
    watcher_thread = threading.Thread(target=start_watcher, daemon=True)
    watcher_thread.start()
    logger.info("File watcher started on ../data")

def run_agent_graph(initial_state, config):
    try:
        graph_app.invoke(initial_state, config)
    except Exception as e:
        logger.error(f"Graph execution failed: {e}")

@app.post("/api/generate_enrollment")
def generate_enrollment():
    if not SUPERDOCS_API_KEY:
        raise HTTPException(status_code=500, detail="SUPERDOCS_API_KEY missing from .env")

    data_dir = os.path.join(os.path.dirname(__file__), "../data")
    plan_2025_path = f"{data_dir}/plan_2025.json"
    plan_2026_path = f"{data_dir}/plan_2026.json"
    
    with open(f"{data_dir}/employees.json", "r") as f:
        employees = json.load(f)
    
    base_doc_path = f"{data_dir}/enrolment_guide_2025.md"
    upload_res = requests.post(
        f"{SUPERDOCS_BASE_URL}/v1/documents/upload",
        headers={"Authorization": f"Bearer {SUPERDOCS_API_KEY}"},
        files={"file": ("enrolment_guide_2025.md", open(base_doc_path, "rb"), "text/markdown")},
        data={"session_id": "global-enrollment"}
    )
    if upload_res.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to upload base document to SuperDocs API")
    
    base_html = upload_res.json().get("html")
    jobs = []
    
    for emp in employees:
        instructions = generate_superdocs_instructions(plan_2025_path, plan_2026_path, employee=emp)
        job_id = "job_" + str(uuid.uuid4())[:8]
        session_id = f"enrollment-{emp['employee_id']}-{job_id}"
        
        initial_state = {
            "job_id": job_id,
            "document_id": session_id,
            "instructions": instructions,
            "base_html": base_html,
            "superdocs_job_id": None,
            "superdocs_session_id": session_id,
            "status": "starting",
            "pending_changes": [],
            "user_approval_payload": [],
            "final_output": None
        }
        config = {"configurable": {"thread_id": job_id}}
        

        t = threading.Thread(target=run_agent_graph, args=(initial_state, config))
        t.start()
        
        jobs.append({
            "type": "employee_enrollment", 
            "employee_id": emp["employee_id"], 
            "employee_name": emp["name"], 
            "job_id": job_id
        })
            
    faq_path = f"{data_dir}/manager_faq_2025.md"
    if os.path.exists(faq_path):
        faq_upload = requests.post(
            f"{SUPERDOCS_BASE_URL}/v1/documents/upload",
            headers={"Authorization": f"Bearer {SUPERDOCS_API_KEY}"},
            files={"file": ("manager_faq_2025.md", open(faq_path, "rb"), "text/markdown")},
            data={"session_id": "global-faq"}
        )
        if faq_upload.status_code == 200:
            faq_html = faq_upload.json().get("html")
            faq_instructions = generate_superdocs_instructions(plan_2025_path, plan_2026_path)
            
            job_id = "job_" + str(uuid.uuid4())[:8]
            session_id = f"faq-{job_id}"
            initial_state = {
                "job_id": job_id,
                "document_id": session_id,
                "instructions": faq_instructions,
                "base_html": faq_html,
                "superdocs_job_id": None,
                "superdocs_session_id": session_id,
                "status": "starting",
                "pending_changes": [],
                "user_approval_payload": [],
                "final_output": None
            }
            config = {"configurable": {"thread_id": job_id}}
            

            t = threading.Thread(target=run_agent_graph, args=(initial_state, config))
            t.start()
            
            jobs.append({
                "type": "manager_faq", 
                "job_id": job_id
            })

    return {"message": "Enrollment generation jobs started via LangGraph", "jobs": jobs}

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    config = {"configurable": {"thread_id": job_id}}
    state_tuple = graph_app.get_state(config)
    
    if not state_tuple or not hasattr(state_tuple, 'values') or not state_tuple.values:

        return {
            "job_id": job_id,
            "document_id": "unknown",
            "status": "starting",
            "proposed_changes": []
        }
        
    state = state_tuple.values
    status = state.get("status", "starting")
    
    proposed_changes = []
    if status in ["awaiting_approval", "approved"]:
        pending = state.get("pending_changes", [])
        for p in pending:
            explanation = p.get("ai_explanation", "")
            operation = p.get("operation", "edit").capitalize()
            proposed_changes.append({
                "id": p.get("change_id"),
                "section": f"{operation} - {explanation}" if explanation else operation,
                "original": p.get("old_html") or "",
                "proposed": p.get("new_html") or ""
            })
            

    frontend_status = "pending" if status == "awaiting_approval" else status
    if frontend_status == "invoked":
        frontend_status = "in_progress"
    
    return {
        "job_id": job_id,
        "document_id": state.get("superdocs_session_id", "document"),
        "status": frontend_status,
        "proposed_changes": proposed_changes
    }

@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, request: JobApprovalRequest):
    config = {"configurable": {"thread_id": job_id}}
    state_tuple = graph_app.get_state(config)
    
    if not state_tuple or not hasattr(state_tuple, 'values') or not state_tuple.values:
        raise HTTPException(status_code=404, detail="Job not found in LangGraph state")
        

    payload = []
    approved_count = 0
    for item in request.items:
        payload.append({
            "item_id": item.item_id,
            "status": item.status
        })
        if item.status == "approved":
            approved_count += 1
            
    graph_app.update_state(
        config,
        {"user_approval_payload": payload}
    )
    


    t = threading.Thread(target=run_agent_graph, args=(None, config))
    t.start()
        
    return {
        "message": "Job approved and graph resumed",
        "status": "approved",
        "job_id": job_id,
        "approved_items_count": approved_count,
    }

@app.post("/api/export/{document_id}")
def export_document(document_id: str):
    return {"message": "Export initiated", "download_url": f"http://localhost:8000/static/{document_id}.pdf"}
