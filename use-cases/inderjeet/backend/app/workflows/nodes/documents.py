import logging
from typing import Dict, Any
from app.workflows.state import DisruptionState
from app.db.session import SessionLocal
from app.db.models import DisruptionBatch, TravelerManifest, VoucherRecord, AuditLog

logger = logging.getLogger(__name__)

# Basic localized template dictionaries
LETTER_TEMPLATES = {
    "en": "Dear {name},\n\nWe regret to inform you that your flight {cancelled} has been cancelled. We have re-accommodated you on flight {replacement}. Your updated itinerary is attached.\n\nBest regards,\nTravel Operations Team",
    "es": "Estimado/a {name},\n\nLamentamos informarle que su vuelo {cancelled} ha sido cancelado. Le hemos reubicado en el vuelo {replacement}. Adjuntamos su itinerario actualizado.\n\nAtentamente,\nEquipo de Operaciones de Viaje",
    "fr": "Cher/Chère {name},\n\nNous avons le regret de vous informer que votre vol {cancelled} a été annulé. Nous vous avons replacé sur le vol {replacement}. Votre itinéraire mis à jour est joint.\n\nCordialement,\nL'équipe des opérations de voyage"
}

def document_drafting_node(state: DisruptionState) -> Dict[str, Any]:
    """
    Drafts passenger letters and checks voucher eligibility for travel disruptions.
    Advances the state index cursor traveler-by-traveler.
    """
    batch_id = state.get("batch_id")
    affected_ids = state.get("affected_traveler_ids", [])
    index = state.get("current_traveler_index", 0)
    disruption = state.get("disruption_event", {})
    
    if not affected_ids or index >= len(affected_ids):
        return {"current_traveler_index": index}

    traveler_id = affected_ids[index]
    logger.info(f"Drafting correspondence & vouchers for traveler ID: {traveler_id}")

    db = SessionLocal()
    try:
        traveler = db.query(TravelerManifest).filter(TravelerManifest.id == traveler_id).first()
        if not traveler:
            return {"current_traveler_index": index + 1}

        # 1. Draft Explanation Letter based on Language preference
        lang = traveler.language.lower()
        if lang not in LETTER_TEMPLATES:
            lang = "en"
            
        letter_format = LETTER_TEMPLATES[lang]
        traveler.explanation_letter = letter_format.format(
            name=traveler.passenger_name,
            cancelled=disruption.get("identifier", "AA123"),
            replacement=disruption.get("replacement_identifier", "AA456")
        )

        # 2. Evaluate Voucher Eligibility
        # Eligibility rule: if disruption type is flight_cancellation, issue meal voucher ($50)
        # If disruption is hotel_closure, issue hotel claim voucher ($200)
        disruption_type = disruption.get("type", "").lower()
        
        if disruption_type == "flight_cancellation":
            traveler.voucher_status = "ELIGIBLE"
            meal_voucher = VoucherRecord(
                traveler_id=traveler.id,
                type="MEAL",
                amount=50.0
            )
            db.add(meal_voucher)
        elif disruption_type == "hotel_closure":
            traveler.voucher_status = "ELIGIBLE"
            hotel_voucher = VoucherRecord(
                traveler_id=traveler.id,
                type="HOTEL",
                amount=200.0
            )
            db.add(hotel_voucher)

        # Update execution audit logs
        log = AuditLog(
            batch_id=batch_id,
            stage="DRAFTING",
            message=f"Created localized letter ({lang}) and verified voucher for {traveler.passenger_name}."
        )
        db.add(log)
        
        # Check if this was the last traveler in the queue
        batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
        if batch and index == len(affected_ids) - 1:
            batch.status = "PENDING_APPROVAL"
            logger.info("Drafting complete for all affected travelers. Batch moves to PENDING_APPROVAL.")

        db.commit()
        return {
            "current_traveler_index": index + 1,
            "audit_logs": [{"stage": "DRAFTING", "message": f"Correspondence drafted for passenger index {index}."}]
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error in Document Drafting Node for traveler {traveler_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()
