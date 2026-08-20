import logging
import json
from typing import Dict, Any
from app.workflows.state import DisruptionState
from app.services.superdocs import SuperDocsClient
from app.db.session import SessionLocal
from app.db.models import DisruptionBatch, TravelerManifest, AuditLog

logger = logging.getLogger(__name__)

def document_surgery_node(state: DisruptionState) -> Dict[str, Any]:
    """
    Executes surgical itinerary edits via the SuperDocs service.
    Processes traveler-by-traveler, matching the cursor index in state
    to allow resume-after-crash behavior.
    """
    batch_id = state.get("batch_id")
    affected_ids = state.get("affected_traveler_ids", [])
    index = state.get("current_traveler_index", 0)
    disruption = state.get("disruption_event", {})
    
    if not affected_ids or index >= len(affected_ids):
        logger.info(f"No travelers to process or index {index} out of bounds.")
        return {"current_traveler_index": index}

    traveler_id = affected_ids[index]
    logger.info(f"Surgically editing itinerary for traveler ID: {traveler_id} (Index {index}/{len(affected_ids)})")

    # Ingest rules and formulate specific edit instructions
    new_flight = disruption.get("replacement_identifier", "AA456")
    cancelled_flight = disruption.get("identifier", "AA123")
    
    instruction = (
        f"Replace the cancelled Flight {cancelled_flight} in this itinerary "
        f"with the re-booked Flight {new_flight} departing at 2:30 PM. "
        f"Ensure unaffected itinerary details are kept identical."
    )

    db = SessionLocal()
    client = SuperDocsClient()
    
    try:
        traveler = db.query(TravelerManifest).filter(TravelerManifest.id == traveler_id).first()
        if not traveler:
            return {"current_traveler_index": index + 1}

        # 1. Upload mock/actual itinerary document
        original_content = b"Mock itinerary data details flight coordinates AA123 departs London Heathrow 10:00 AM."
        upload_res = client.upload_document(original_content, f"itinerary_{traveler.passenger_name.replace(' ', '_')}.txt")
        doc_id = upload_res.get("document_id")

        # 2. Call SuperDocs edit
        edit_res = client.send_edit_instruction(doc_id, instruction)
        proposed_changes = edit_res.get("proposed_changes")
        
        # Save temporary proposed changes/session references to db so frontend can show the diff
        traveler.updated_itinerary_url = f"{settings_override_url()}/review/{doc_id}"
        
        # Track simulated or actual operation cost
        op_count = 1
        cost_est = 0.05  # $0.05 per operation
        
        traveler.operations_spent += op_count
        traveler.cost_usd += cost_est

        # Update batch summary total spent
        batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
        if batch:
            batch.total_operations_spent += op_count
            batch.total_cost_usd += cost_est
            batch.status = "DRAFTING_IN_PROGRESS"

        # Log audit entry
        log = AuditLog(
            batch_id=batch_id,
            stage="SURGERY",
            message=f"Itinerary surgery completed for {traveler.passenger_name}. proposed Session: {doc_id}."
        )
        db.add(log)
        db.commit()

        logger.info(f"Surgery complete for passenger {traveler.passenger_name}.")
        return {
            "current_traveler_index": index + 1,
            "audit_logs": [{"stage": "SURGERY", "message": f"Completed surgical edit for traveler index {index}."}]
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error in Surgery Node for traveler {traveler_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()

def settings_override_url() -> str:
    # Helper to return base API url
    from app.core.config import settings
    return settings.SUPERDOCS_BASE_URL
