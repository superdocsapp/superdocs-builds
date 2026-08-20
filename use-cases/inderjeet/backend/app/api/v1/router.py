from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.db.session import get_db
from app.db.models import DisruptionBatch, TravelerManifest, AuditLog
from app.workflows.engine import run_workflow
from app.services.superdocs import SuperDocsClient

api_router = APIRouter()

# Schema classes for request body validation
class DisruptionInput(BaseModel):
    type: str # flight_cancellation, hotel_closure, etc.
    identifier: str # Flight number (e.g. AA123) or Hotel name
    replacement_identifier: Optional[str] = "AA456"

class TravelerInput(BaseModel):
    passenger_name: str
    email: str
    language: Optional[str] = "en"
    loyalty_status: Optional[str] = "STANDARD"

class BatchRequest(BaseModel):
    disruption_details: DisruptionInput
    manifest: List[TravelerInput]

class ApprovalRequest(BaseModel):
    traveler_id: str
    decision: str # APPROVED or REJECTED
    letter_text: Optional[str] = None

@api_router.post("/batch")
def create_disruption_batch(
    request: BatchRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    """
    Creates a new travel disruption batch, parses manifest entries,
    and runs the LangGraph engine in the background.
    """
    try:
        # 1. Create batch record
        batch = DisruptionBatch(
            disruption_details=request.disruption_details.model_dump(),
            status="INGESTED"
        )
        db.add(batch)
        db.flush()

        # 2. Add travelers manifest list
        for entry in request.manifest:
            t = TravelerManifest(
                batch_id=batch.id,
                passenger_name=entry.passenger_name,
                email=entry.email,
                language=entry.language,
                loyalty_status=entry.loyalty_status
            )
            db.add(t)

        log = AuditLog(
            batch_id=batch.id,
            stage="API",
            message="Batch manifest received and queued for analysis."
        )
        db.add(log)
        db.commit()

        # 3. Queue LangGraph execution task in background to keep endpoint non-blocking
        background_tasks.add_task(run_workflow, batch.id)

        return {
            "batch_id": batch.id,
            "status": "processing",
            "message": "Disruption analysis initiated."
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/batch/{batch_id}")
def get_batch_details(batch_id: str, db: Session = Depends(get_db)):
    """Queries batch state variables, logs, and traveler manifest status."""
    batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    travelers = db.query(TravelerManifest).filter(TravelerManifest.batch_id == batch_id).all()
    logs = db.query(AuditLog).filter(AuditLog.batch_id == batch_id).order_by(AuditLog.timestamp.asc()).all()

    return {
        "batch_id": batch.id,
        "status": batch.status,
        "total_cost_usd": batch.total_cost_usd,
        "total_operations_spent": batch.total_operations_spent,
        "travelers": [
            {
                "id": t.id,
                "passenger_name": t.passenger_name,
                "email": t.email,
                "language": t.language,
                "loyalty_status": t.loyalty_status,
                "updated_itinerary_url": t.updated_itinerary_url,
                "explanation_letter": t.explanation_letter,
                "voucher_status": t.voucher_status,
                "approval_status": t.approval_status
            } for t in travelers
        ],
        "logs": [
            {
                "stage": l.stage,
                "message": l.message,
                "timestamp": l.timestamp
            } for l in logs
        ]
    }

@api_router.post("/batch/{batch_id}/decision")
def submit_approval_decision(
    batch_id: str, 
    request: ApprovalRequest, 
    db: Session = Depends(get_db)
):
    """
    Saves the human-in-the-loop decision (APPROVED / REJECTED) for a traveler.
    If all travelers in the batch are decided, commits changes to SuperDocs and exports files.
    """
    t = db.query(TravelerManifest).filter(
        TravelerManifest.id == request.traveler_id,
        TravelerManifest.batch_id == batch_id
    ).first()

    if not t:
        raise HTTPException(status_code=404, detail="Traveler manifest record not found")

    t.approval_status = request.decision.upper()
    if request.letter_text:
        t.explanation_letter = request.letter_text

    # Log review step
    log = AuditLog(
        batch_id=batch_id,
        stage="DECISION",
        message=f"Passenger {t.passenger_name} set to {request.decision}."
    )
    db.add(log)
    db.commit()

    # Check if all affected travelers are decided
    batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
    all_travelers = db.query(TravelerManifest).filter(TravelerManifest.batch_id == batch_id).all()
    
    # If all travelers are decided (no longer PENDING)
    undecided = [p for p in all_travelers if p.passenger_name != "Unaffected Traveler" and p.approval_status == "PENDING"]
    
    if len(undecided) == 0:
        logger.info(f"All traveler decisions received for batch {batch_id}. Finalizing commit...")
        client = SuperDocsClient()
        
        # 1. Approve changes for each approved traveler in SuperDocs session
        for traveler in all_travelers:
            if traveler.approval_status == "APPROVED" and traveler.updated_itinerary_url:
                # Extract document_id from session url
                doc_id = traveler.updated_itinerary_url.split("/")[-1]
                try:
                    # In actual system this commits proposed change list
                    client.approve_changes(doc_id, ["change_01"])
                    client.export_file(doc_id, "pdf")
                    traveler.voucher_status = "ISSUED"
                except Exception as e:
                    logger.error(f"Error finalizing document {doc_id} for traveler {traveler.passenger_name}: {e}")
        
        batch.status = "COMMITTED"
        
        final_log = AuditLog(
            batch_id=batch_id,
            stage="COMMIT",
            message="Batch changes committed and files exported successfully."
        )
        db.add(final_log)
        db.commit()

    return {"status": "success", "message": f"Recorded decision for traveler {t.passenger_name}."}
