import os
import uuid
import time
import json
import requests
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import SubstitutionRun
from app.config import settings

router = APIRouter()

# SuperDocs Endpoint & Headers
SUPERDOCS_API_URL = "https://api.superdocs.app"
HEADERS = {
    "Authorization": f"Bearer {settings.SUPERDOCS_API_KEY}"
}

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def upload_document_to_superdocs(file_path: str, filename: str) -> str:
    """Uploads a document to SuperDocs, polls the documents catalog, and returns its durable UUID with retries."""
    temp_session_id = f"temp_session_{uuid.uuid4()}"
    url = f"{SUPERDOCS_API_URL}/v1/documents/upload?index=true"
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"session_id": temp_session_id}
                res = requests.post(url, headers=HEADERS, files=files, data=data)
                
                if res.status_code in [502, 503, 504] and attempt < max_retries - 1:
                    print(f"SuperDocs upload got {res.status_code}. Retrying in {2 ** attempt}s...")
                    time.sleep(2 ** attempt)
                    continue
                    
                if not res.ok:
                    raise Exception(f"Failed to upload document to SuperDocs: {res.text}")
                break
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"SuperDocs upload got exception: {e}. Retrying in {2 ** attempt}s...")
                time.sleep(2 ** attempt)
                continue
            raise e
            
    # Poll /v1/documents to fetch the durable UUID matching this unique title
    title_to_match = os.path.splitext(filename)[0]
    list_url = f"{SUPERDOCS_API_URL}/v1/documents"
    
    for _ in range(5):
        time.sleep(1)
        res_list = requests.get(list_url, headers=HEADERS)
        if res_list.ok:
            docs = res_list.json().get("documents", [])
            for doc in docs:
                if doc.get("title") == title_to_match:
                    return doc.get("document_id")
                    
    raise Exception(f"Failed to find permanent durable UUID for uploaded file: {filename}")


def upload_attachment_to_superdocs(file_path: str, filename: str, session_id: str) -> str:
    """Uploads an attachment reference file to SuperDocs, polls until parsed, and returns attachment ID with retries."""
    url = f"{SUPERDOCS_API_URL}/v1/attachments/upload"
    
    max_retries = 3
    job_id = None
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"session_id": session_id}
                res = requests.post(url, headers=HEADERS, files=files, data=data)
                
                if res.status_code in [502, 503, 504] and attempt < max_retries - 1:
                    print(f"SuperDocs attachment upload got {res.status_code}. Retrying in {2 ** attempt}s...")
                    time.sleep(2 ** attempt)
                    continue
                    
                if not res.ok:
                    raise Exception(f"Failed to upload attachment to SuperDocs: {res.text}")
                job_data = res.json()
                job_id = job_data.get("job_id")
                break
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"SuperDocs attachment upload got exception: {e}. Retrying in {2 ** attempt}s...")
                time.sleep(2 ** attempt)
                continue
            raise e
        
    # Poll for completion of attachment indexing
    poll_url = f"{SUPERDOCS_API_URL}/v1/jobs/{job_id}"
    for _ in range(30):  # 60s timeout
        time.sleep(2)
        poll_res = requests.get(poll_url, headers=HEADERS)
        if poll_res.ok:
            poll_data = poll_res.json()
            if poll_data.get("status") == "completed":
                return job_id
            elif poll_data.get("status") == "failed":
                raise Exception("SuperDocs failed to parse attachment.")
    raise Exception("Timed out waiting for attachment ingestion.")


def initialize_superdocs_session(session_id: str, document_ids: List[str]):
    """Links multiple durable documents to a single session with retries."""
    url = f"{SUPERDOCS_API_URL}/v1/sessions/init"
    payload = {
        "session_id": session_id,
        "document_ids": document_ids
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = requests.post(url, headers=HEADERS, json=payload)
            if res.status_code in [502, 503, 504] and attempt < max_retries - 1:
                print(f"SuperDocs session init got {res.status_code}. Retrying in {2 ** attempt}s...")
                time.sleep(2 ** attempt)
                continue
                
            if not res.ok:
                raise Exception(f"Failed to initialize multi-document session: {res.text}")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"SuperDocs session init got exception: {e}. Retrying in {2 ** attempt}s...")
                time.sleep(2 ** attempt)
                continue
            raise e


def execute_substitution_analysis(run_id: str, db_session: Session):
    """Background task to run comparison and stage edits in SuperDocs."""
    run = db_session.query(SubstitutionRun).filter(SubstitutionRun.id == uuid.UUID(run_id)).first()
    if not run:
        return
        
    try:
        run.status = "analyzing"
        db_session.add(run)
        db_session.commit()
        
        # Extract exact document titles for the prompt
        spec_name = run.spec_filename or "spec_093000_tiling.txt"
        sched_name = run.schedule_filename or "finish_schedule.txt"
        spec_title = os.path.splitext(spec_name)[0]
        schedule_title = os.path.splitext(sched_name)[0]
        
        # Query SuperDocs server to fetch exact active titles (which contain the unique UUID suffixes)
        if run.spec_doc_id:
            spec_res = requests.get(f"{SUPERDOCS_API_URL}/v1/documents/{run.spec_doc_id}", headers=HEADERS)
            if spec_res.ok:
                spec_title = spec_res.json().get("title", spec_title)
        if run.schedule_doc_id:
            sched_res = requests.get(f"{SUPERDOCS_API_URL}/v1/documents/{run.schedule_doc_id}", headers=HEADERS)
            if sched_res.ok:
                sched_title = sched_res.json().get("title", schedule_title)
        
        prompt = (
            "You are a professional project architect. Compare the attached contractor substitution product cut sheet "
            f"against the Specification Section document (titled '{spec_title}'). Follow these rules carefully:\n"
            "1. Extract every performance requirement from the Specification Section (e.g. technical metrics, ratings, manufacturers, wear/durability standards, materials).\n"
            "2. Cross-reference them line-by-line against the values listed in the proposed product cut sheet.\n"
            "3. Formulate a structured comparison table showing required value, proposed product value, spec clause, and compliance status (Met / Not Met / Unclear).\n"
            "4. Draft a formal architect's response letter (Accepting or Rejecting the substitution based on whether all specs are met). "
            "If any requirement is NOT met, reject the substitution request with specific technical grounds.\n"
            f"5. If the substitution is ACCEPTED, update the Specification Section document (titled '{spec_title}') to substitute product references and manufacturers. "
            f"Also update the Finish Schedule document (titled '{schedule_title}') to replace manufacturer/product fields for this room or material.\n"
            "If the substitution is REJECTED, do not make any edits to the specification or schedule documents."
        )
        
        # Trigger async AI chat job in SuperDocs
        url = f"{SUPERDOCS_API_URL}/v1/chat/async"
        payload = {
            "session_id": run.session_id,
            "message": prompt,
            "approval_mode": "ask_every_time",
            "response_mode": "compact"
        }
        res = requests.post(url, headers=HEADERS, json=payload)
        if not res.ok:
            raise Exception(f"SuperDocs chat creation failed: {res.text}")
            
        job_data = res.json()
        job_id = job_data.get("job_id")
        
        # Save job_id immediately
        run.job_id = job_id
        db_session.add(run)
        db_session.commit()
        
        # Poll for awaiting_approval
        poll_url = f"{SUPERDOCS_API_URL}/v1/jobs/{job_id}"
        reply_text = ""
        pending_changes = []
        
        for _ in range(90):  # 180s timeout
            time.sleep(2)
            # Fetch latest run status from DB to check if killed mid-run (resilience behavior)
            db_session.refresh(run)
            if run.status == "failed":
                print("Job was terminated by user.")
                return
                
            poll_res = requests.get(poll_url, headers=HEADERS)
            if poll_res.ok:
                poll_data = poll_res.json()
                status = poll_data.get("status")
                
                # Check for intermediate changes and result
                metadata = poll_data.get("metadata", {}) or {}
                result = poll_data.get("result", {}) or {}
                
                # Fetch response text
                reply_text = ""
                if isinstance(result, dict) and "response" in result:
                    reply_text = result.get("response", "")
                if not reply_text:
                    reply_text = poll_data.get("reply_text", "")
                    
                # Fetch pending changes
                pending_changes = metadata.get("pending_changes", [])
                if not pending_changes and isinstance(result, dict):
                    doc_changes = result.get("document_changes", {}) or {}
                    pending_changes = doc_changes.get("pending_changes", [])
                if not pending_changes:
                    pending_changes = []
                
                if status == "awaiting_approval":
                    run.status = "awaiting_approval"
                    break
                elif status == "completed":
                    run.status = "awaiting_approval"  # Force review even if AI auto-completed
                    break
                elif status == "failed":
                    raise Exception("SuperDocs AI processing failed.")
        else:
            raise Exception("Timed out waiting for SuperDocs review analysis.")
            
        # Parse proposed change descriptions and content
        # Proposed changes might require a second JSON parse as per the integration guidelines
        parsed_changes = []
        for change in pending_changes:
            if isinstance(change, str):
                try:
                    change = json.loads(change)
                except Exception:
                    pass
            
            # Extract content if nested or stringified
            proposed = change.get("proposed")
            if isinstance(proposed, str):
                try:
                    proposed = json.loads(proposed)
                    change["proposed"] = proposed
                except Exception:
                    pass
            parsed_changes.append(change)
            
        # Extract report vs letter from response text
        report = reply_text
        letter = ""
        if "response letter" in reply_text.lower() or "dear" in reply_text.lower():
            # Attempt to split
            parts = reply_text.split("Response Letter")
            if len(parts) > 1:
                report = parts[0].strip()
                letter = parts[1].strip()
                
        run.comparison_report = report
        run.response_letter = letter
        run.pending_changes = parsed_changes
        db_session.add(run)
        db_session.commit()
        
    except Exception as e:
        print(f"Error in substitution execution: {e}")
        run.status = "failed"
        run.comparison_report = f"Analysis failed: {str(e)}"
        db_session.add(run)
        db_session.commit()


@router.post("/upload")
def upload_files(
    background_tasks: BackgroundTasks,
    spec: UploadFile = File(...),
    cutsheet: UploadFile = File(...),
    schedule: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Save files locally
        spec_path = os.path.join(UPLOAD_DIR, f"spec_{uuid.uuid4()}_{spec.filename}")
        with open(spec_path, "wb") as f:
            f.write(spec.file.read())
            
        cutsheet_path = os.path.join(UPLOAD_DIR, f"cutsheet_{uuid.uuid4()}_{cutsheet.filename}")
        with open(cutsheet_path, "wb") as f:
            f.write(cutsheet.file.read())
            
        schedule_path = os.path.join(UPLOAD_DIR, f"schedule_{uuid.uuid4()}_{schedule.filename}")
        with open(schedule_path, "wb") as f:
            f.write(schedule.file.read())
            
        # Upload Spec & Schedule with unique filenames to SuperDocs to ensure precise title matching
        ext_spec = os.path.splitext(spec.filename)[1]
        name_spec = os.path.splitext(spec.filename)[0]
        unique_spec_filename = f"{name_spec}_{uuid.uuid4().hex[:6]}{ext_spec}"
        
        ext_sched = os.path.splitext(schedule.filename)[1]
        name_sched = os.path.splitext(schedule.filename)[0]
        unique_sched_filename = f"{name_sched}_{uuid.uuid4().hex[:6]}{ext_sched}"
        
        spec_id = upload_document_to_superdocs(spec_path, unique_spec_filename)
        schedule_id = upload_document_to_superdocs(schedule_path, unique_sched_filename)
        
        # Link documents in session
        session_id = f"sub_session_{uuid.uuid4()}"
        initialize_superdocs_session(session_id, [spec_id, schedule_id])
        
        # Upload Cut Sheet as session attachment reference
        upload_attachment_to_superdocs(cutsheet_path, cutsheet.filename, session_id)
        
        # Create DB record
        run = SubstitutionRun(
            session_id=session_id,
            status="uploading",
            spec_doc_id=spec_id,
            schedule_doc_id=schedule_id,
            cutsheet_filename=cutsheet.filename,
            spec_filename=spec.filename,
            schedule_filename=schedule.filename
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        
        # Queue analysis
        background_tasks.add_task(execute_substitution_analysis, str(run.id), db)
        
        return {"id": str(run.id), "status": "processing"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest files: {str(e)}")


@router.post("/approve/{run_id}")
def approve_substitution(run_id: str, request: Request, db: Session = Depends(get_db)):
    run = db.query(SubstitutionRun).filter(SubstitutionRun.id == uuid.UUID(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
        
    try:
        # Construct the changes array for approval
        changes_payload = []
        pending = run.pending_changes or []
        for ch in pending:
            if isinstance(ch, dict) and "change_id" in ch:
                changes_payload.append({
                    "change_id": ch.get("change_id"),
                    "approved": True
                })
                
        # Call SuperDocs approve endpoint to commit all staged changes
        url = f"{SUPERDOCS_API_URL}/v1/chat/{run.session_id}/approve"
        payload = {
            "approved": True,
            "job_id": run.job_id,
            "changes": changes_payload
        }
        res = requests.post(url, headers=HEADERS, json=payload)
        if not res.ok:
            if "not awaiting approval" in res.text.lower():
                pass
            else:
                raise Exception(f"Failed to commit changes in SuperDocs: {res.text}")
            
        # Poll for completion of the job to fetch final comparison report & response letter
        poll_url = f"{SUPERDOCS_API_URL}/v1/jobs/{run.job_id}"
        reply_text = ""
        for _ in range(60):  # 120s timeout
            time.sleep(2)
            poll_res = requests.get(poll_url, headers=HEADERS)
            if poll_res.ok:
                poll_data = poll_res.json()
                status = poll_data.get("status")
                if status == "completed":
                    result = poll_data.get("result", {}) or {}
                    reply_text = result.get("response", "") if isinstance(result, dict) else ""
                    break
                elif status == "failed":
                    raise Exception("SuperDocs job failed after approval.")
        else:
            raise Exception("Timed out waiting for SuperDocs job completion after approval.")
            
        # Extract report vs letter from response text
        report = reply_text
        letter = ""
        if "response letter" in reply_text.lower() or "dear" in reply_text.lower():
            # Attempt to split
            parts = reply_text.split("Response Letter")
            if len(parts) > 1:
                report = parts[0].strip()
                letter = parts[1].strip()
                
        run.comparison_report = report
        run.response_letter = letter
            
        # Trigger Document Exports
        export_url = f"{SUPERDOCS_API_URL}/v1/documents/export"
        
        # Export Specification Section
        spec_export = requests.post(export_url, headers=HEADERS, json={
            "session_id": run.session_id,
            "document_id": run.spec_doc_id,
            "format": "docx"
        })
        
        spec_url = None
        if spec_export.ok:
            spec_filename = f"updated_spec_{run.id}.docx"
            spec_file_path = os.path.join(UPLOAD_DIR, spec_filename)
            with open(spec_file_path, "wb") as f:
                f.write(spec_export.content)
            base_url = str(request.base_url).rstrip("/")
            spec_url = f"{base_url}/api/substitution/download/{spec_filename}"
        
        # Export Finish Schedule
        sched_export = requests.post(export_url, headers=HEADERS, json={
            "session_id": run.session_id,
            "document_id": run.schedule_doc_id,
            "format": "docx"
        })
        
        sched_url = None
        if sched_export.ok:
            sched_filename = f"updated_schedule_{run.id}.docx"
            sched_file_path = os.path.join(UPLOAD_DIR, sched_filename)
            with open(sched_file_path, "wb") as f:
                f.write(sched_export.content)
            base_url = str(request.base_url).rstrip("/")
            sched_url = f"{base_url}/api/substitution/download/{sched_filename}"
        
        run.status = "approved"
        db.add(run)
        db.commit()
        
        return {
            "status": "approved",
            "spec_download_url": spec_url,
            "schedule_download_url": sched_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject/{run_id}")
def reject_substitution(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SubstitutionRun).filter(SubstitutionRun.id == uuid.UUID(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
        
    try:
        # Construct the changes array for rejection
        changes_payload = []
        pending = run.pending_changes or []
        for ch in pending:
            if isinstance(ch, dict) and "change_id" in ch:
                changes_payload.append({
                    "change_id": ch.get("change_id"),
                    "approved": False
                })
                
        # Call SuperDocs approve endpoint to discard all staged changes
        url = f"{SUPERDOCS_API_URL}/v1/chat/{run.session_id}/approve"
        payload = {
            "approved": False,
            "job_id": run.job_id,
            "changes": changes_payload
        }
        res = requests.post(url, headers=HEADERS, json=payload)
        if not res.ok:
            if "not awaiting approval" in res.text.lower():
                pass
            else:
                raise Exception(f"Failed to discard changes in SuperDocs: {res.text}")
            
        # Poll for completion of the job to fetch final comparison report & response letter
        poll_url = f"{SUPERDOCS_API_URL}/v1/jobs/{run.job_id}"
        reply_text = ""
        for _ in range(60):  # 120s timeout
            time.sleep(2)
            poll_res = requests.get(poll_url, headers=HEADERS)
            if poll_res.ok:
                poll_data = poll_res.json()
                status = poll_data.get("status")
                if status == "completed":
                    result = poll_data.get("result", {}) or {}
                    reply_text = result.get("response", "") if isinstance(result, dict) else ""
                    break
                elif status == "failed":
                    raise Exception("SuperDocs job failed after rejection.")
        else:
            raise Exception("Timed out waiting for SuperDocs job completion after rejection.")
            
        # Extract report vs letter from response text
        report = reply_text
        letter = ""
        if "response letter" in reply_text.lower() or "dear" in reply_text.lower():
            # Attempt to split
            parts = reply_text.split("Response Letter")
            if len(parts) > 1:
                report = parts[0].strip()
                letter = parts[1].strip()
                
        run.comparison_report = report
        run.response_letter = letter
        run.status = "rejected"
        db.add(run)
        db.commit()
        return {"status": "rejected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(SubstitutionRun).order_by(SubstitutionRun.created_at.desc()).all()
    return [{
        "id": str(r.id),
        "status": r.status,
        "spec_filename": r.spec_filename,
        "cutsheet_filename": r.cutsheet_filename,
        "schedule_filename": r.schedule_filename,
        "created_at": r.created_at
    } for r in runs]


@router.get("/runs/{run_id}")
def get_run_details(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SubstitutionRun).filter(SubstitutionRun.id == uuid.UUID(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
        
    return {
        "id": str(run.id),
        "status": run.status,
        "spec_filename": run.spec_filename,
        "cutsheet_filename": run.cutsheet_filename,
        "schedule_filename": run.schedule_filename,
        "comparison_report": run.comparison_report,
        "response_letter": run.response_letter,
        "pending_changes": run.pending_changes,
        "created_at": run.created_at
    }


@router.get("/download/{filename}")
def download_file(filename: str):
    """Serves the generated updated document file."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
