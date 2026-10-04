"""FastAPI API endpoints for the SuperDocs Dropbox Watcher.

Provides:
- Health check with DB connectivity
- Webhook receiver for Dropbox notifications
- Job status/listing endpoints
- Admin endpoints for folder config and manual operations
"""
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Header, Request, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_db
from app.models.job import Job, JobStatus
from app.models.folder_config import FolderConfig
from app.models.client import Client
from app.models.event import Event
from app.models.known_output import KnownOutput
from app.services.dropbox_client import verify_webhook_signature, DropboxClient
from app.services.state_machine import transition, InvalidTransition
from app.services.worker import WorkerLoop, deserialize_proposed_changes
from app.services.superdocs_client import SuperDocsClient
from app.services.system_state import get_global_preview_mode, set_global_preview_mode
from app.services.isolation import path_is_under, normalize_dropbox_path
from app.services.watcher import WatcherService

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="SuperDocs Dropbox Watcher",
    description="API for the SuperDocs Dropbox folder watcher with write-back",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Health ----------

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Liveness check — also verifies the database connection."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "database": db_status}


# ---------- Dropbox Webhook ----------

@app.get("/webhook/dropbox")
async def dropbox_webhook_verify(challenge: str):
    """Dropbox webhook verification — echo back the challenge parameter.
    This is called once during webhook registration."""
    return challenge


@app.post("/webhook/dropbox")
async def dropbox_webhook_receive(
    request: Request,
    x_dropbox_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Receive Dropbox webhook notifications.

    Verifies the HMAC-SHA256 signature, then queues folder scan tasks.
    The actual file processing happens in the background worker.
    """
    body = await request.body()

    # Verify signature (only if app_secret is configured)
    if settings.dropbox_app_secret:
        if not x_dropbox_signature:
            raise HTTPException(status_code=401, detail="Missing signature header")
        if not verify_webhook_signature(x_dropbox_signature, body):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        watcher = WatcherService(DropboxClient())
        created = watcher.scan_all_folders(db)
        return {"status": "ok", "jobs_created": len(created)}
    except Exception:
        # Token missing or Dropbox down — daemon polling still covers discovery.
        return {"status": "ok", "message": "Webhook received; scan deferred to daemon"}


# ---------- Jobs API ----------

class JobResponse(BaseModel):
    id: UUID
    source_path: str
    source_rev: str
    status: str
    preview: bool
    superdocs_doc_id: Optional[str] = None
    proposed_changes: list[dict] = []
    error_message: Optional[str] = None
    retry_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


def _job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        source_path=job.source_path,
        source_rev=job.source_rev,
        status=job.status.value,
        preview=job.preview,
        superdocs_doc_id=job.superdocs_doc_id,
        proposed_changes=deserialize_proposed_changes(job.proposed_changes_json),
        error_message=job.error_message,
        retry_count=job.retry_count,
        created_at=str(job.created_at) if job.created_at else None,
        updated_at=str(job.updated_at) if job.updated_at else None,
    )


@app.get("/api/jobs")
def list_jobs(
    status: Optional[str] = None,
    client_id: Optional[UUID] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List jobs, optionally filtered by status and client."""
    query = db.query(Job).order_by(Job.created_at.desc())
    if client_id:
        query = query.filter(Job.client_id == client_id)
    if status:
        try:
            job_status = JobStatus(status)
            query = query.filter(Job.status == job_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    jobs = query.limit(limit).all()
    return [_job_to_response(j) for j in jobs]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    """Get a specific job by ID, including its full audit trail."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    events = (
        db.query(Event)
        .filter(Event.job_id == job_id)
        .order_by(Event.occurred_at.asc())
        .all()
    )

    return {
        "job": _job_to_response(job),
        "events": [
            {
                "from_state": e.from_state,
                "to_state": e.to_state,
                "actor": e.actor,
                "detail": e.detail,
                "occurred_at": str(e.occurred_at) if e.occurred_at else None,
            }
            for e in events
        ],
    }


def _make_worker() -> WorkerLoop:
    return WorkerLoop(DropboxClient(), SuperDocsClient(), worker_id="api")


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: UUID, db: Session = Depends(get_db)):
    """Approve a REVIEW_PENDING job and run export/write-back."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        transition(
            db, job, JobStatus.APPROVED, actor="user",
            detail="Manual approval via console",
        )
        db.commit()
        db.refresh(job)

        worker = _make_worker()
        job = worker.complete_approved_job(db, job)
    except InvalidTransition as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "approved",
        "job_id": str(job_id),
        "final_status": job.status.value,
    }


@app.post("/api/jobs/{job_id}/reject")
def reject_job(job_id: UUID, db: Session = Depends(get_db)):
    """Reject a job that is in REVIEW_PENDING state."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        transition(db, job, JobStatus.REJECTED, actor="user", detail="Manual rejection via console")
        db.commit()
    except InvalidTransition as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "rejected", "job_id": str(job_id)}

# ---------- Clients API ----------

class ClientCreate(BaseModel):
    name: str
    dropbox_folder_root: str

@app.get("/api/clients")
def list_clients(db: Session = Depends(get_db)):
    clients = db.query(Client).all()
    return [{"id": str(c.id), "name": c.name, "dropbox_folder_root": c.dropbox_folder_root} for c in clients]

@app.post("/api/clients", status_code=201)
def create_client(client_in: ClientCreate, db: Session = Depends(get_db)):
    client = Client(
        name=client_in.name,
        dropbox_folder_root=normalize_dropbox_path(client_in.dropbox_folder_root),
    )
    db.add(client)
    db.commit()
    return {"id": str(client.id), "name": client.name, "status": "created"}

# ---------- Folder Config API ----------

class FolderConfigCreate(BaseModel):
    client_id: UUID
    dropbox_folder_path: str
    treatment: str
    instruction_text: Optional[str] = None
    template_id: Optional[str] = None
    output_naming_pattern: str = "{basename}.superdocs.{treatment}{ext}"
    allowed_extensions: Optional[list[str]] = None
    enabled: bool = True
    preview_mode: bool = False
    debounce_seconds: int = 30
    operation_budget_per_hour: int = 20


@app.get("/api/folder-configs")
def list_folder_configs(db: Session = Depends(get_db)):
    """List all folder configurations."""
    configs = db.query(FolderConfig).all()
    return [
        {
            "id": str(c.id),
            "client_id": str(c.client_id),
            "dropbox_folder_path": c.dropbox_folder_path,
            "treatment": c.treatment,
            "enabled": c.enabled,
            "preview_mode": c.preview_mode,
            "debounce_seconds": c.debounce_seconds,
        }
        for c in configs
    ]


@app.post("/api/folder-configs", status_code=201)
def create_folder_config(config: FolderConfigCreate, db: Session = Depends(get_db)):
    """Create a new folder configuration."""
    # Verify client exists
    client = db.query(Client).filter(Client.id == config.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    folder_path = normalize_dropbox_path(config.dropbox_folder_path)
    if not path_is_under(folder_path, client.dropbox_folder_root):
        raise HTTPException(
            status_code=400,
            detail=(
                "Folder path must sit inside this client's Dropbox root "
                f"({client.dropbox_folder_root})"
            ),
        )

    folder = FolderConfig(
        client_id=config.client_id,
        dropbox_folder_path=folder_path,
        treatment=config.treatment,
        instruction_text=config.instruction_text,
        template_id=config.template_id,
        output_naming_pattern=config.output_naming_pattern,
        allowed_extensions=config.allowed_extensions,
        enabled=config.enabled,
        preview_mode=config.preview_mode,
        debounce_seconds=config.debounce_seconds,
        operation_budget_per_hour=config.operation_budget_per_hour,
    )
    db.add(folder)
    db.commit()
    return {"id": str(folder.id), "status": "created"}


# ---------- Dev seed (console demo without waiting for Dropbox poll) ----------
import hashlib
import uuid as uuid_lib

@app.post("/api/mock-drop", status_code=201)
async def mock_drop(
    folder_config_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Seed a job as if a client dropped a file. Uploads to Dropbox when a token is set."""
    config = db.query(FolderConfig).filter(FolderConfig.id == folder_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Folder config not found")

    content = await file.read()
    filename = file.filename or "dropped.bin"
    path = f"{config.dropbox_folder_path}/{filename}"
    content_hash = hashlib.sha256(content).hexdigest()
    rev = f"mock-rev-{uuid_lib.uuid4().hex[:8]}"

    try:
        dbx = DropboxClient()
        metadata = dbx.upload_file(path, content, overwrite=True)
        path = metadata.path
        rev = metadata.rev
        content_hash = metadata.content_hash
    except Exception:
        pass

    try:
        job = Job(
            client_id=config.client_id,
            folder_config_id=config.id,
            source_path=path,
            source_rev=rev,
            source_content_hash=content_hash,
            status=JobStatus.DISCOVERED,
            preview=config.preview_mode or get_global_preview_mode(),
        )
        db.add(job)
        db.flush()

        transition(db, job, JobStatus.STABILIZING, actor="mock", detail="Seeded drop")
        transition(db, job, JobStatus.QUEUED, actor="mock", detail="Queued via seeded drop")
        db.commit()

        return {"status": "created", "job_id": str(job.id)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ---------- System toggles ----------

class PreviewModeUpdate(BaseModel):
    enabled: bool


@app.get("/api/system/preview-mode")
def get_preview_mode():
    return {"enabled": get_global_preview_mode()}


@app.put("/api/system/preview-mode")
def update_preview_mode(body: PreviewModeUpdate):
    set_global_preview_mode(body.enabled)
    return {"enabled": get_global_preview_mode()}


# ---------- Admin ----------

@app.get("/api/known-outputs")
def list_known_outputs(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List known outputs (anti-loop registry). For debugging."""
    outputs = db.query(KnownOutput).order_by(KnownOutput.written_at.desc()).limit(limit).all()
    return [
        {
            "id": str(o.id),
            "job_id": str(o.job_id),
            "output_path": o.output_path,
            "output_rev": o.output_rev,
            "output_content_hash": o.output_content_hash,
            "written_at": str(o.written_at) if o.written_at else None,
        }
        for o in outputs
    ]
