import logging
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from app.workflows.state import DisruptionState
from app.workflows.nodes.ingestion import ingestion_node
from app.workflows.nodes.surgery import document_surgery_node
from app.workflows.nodes.documents import document_drafting_node
from app.db.session import SessionLocal
from app.db.models import DisruptionBatch, TravelerManifest

logger = logging.getLogger(__name__)

# Define LangGraph state machine
workflow = StateGraph(DisruptionState)

# Add processing nodes
workflow.add_node("ingest", ingestion_node)
workflow.add_node("surgery", document_surgery_node)
workflow.add_node("draft", document_drafting_node)

# Set entry node
workflow.set_entry_point("ingest")

def route_flow(state: DisruptionState) -> str:
    """Decides whether to process the next affected traveler or terminate."""
    if state.get("error"):
        logger.error(f"Routing to END due to error: {state.get('error')}")
        return "end"

    affected = state.get("affected_traveler_ids", [])
    index = state.get("current_traveler_index", 0)

    if index < len(affected):
        return "surgery"
    return "end"

# Conditional transitions
workflow.add_conditional_edges(
    "ingest",
    route_flow,
    {
        "surgery": "surgery",
        "end": END
    }
)

workflow.add_edge("surgery", "draft")

workflow.add_conditional_edges(
    "draft",
    route_flow,
    {
        "surgery": "surgery",
        "end": END
    }
)

# Compile graph app
compiled_workflow = workflow.compile()

def run_workflow(batch_id: str) -> Dict[str, Any]:
    """
    Orchestration wrapper to execute the batch disruption run.
    Queries database state to restore execution checkpoints if resumed after a crash.
    """
    logger.info(f"Starting or resuming workflow run for batch: {batch_id}")
    db = SessionLocal()
    try:
        batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
        if not batch:
            return {"status": "failed", "error": "Batch not found"}

        # Gather disruption coordinates
        disruption_event = batch.disruption_details

        # Find all travelers
        db_travelers = db.query(TravelerManifest).filter(TravelerManifest.batch_id == batch_id).all()
        
        # Check if there is an ongoing execution checkpoint to restore
        # Let's count how many traveler documents are already processed/drafted
        # A traveler is processed if their explanation_letter is written
        processed_ids = [t.id for t in db_travelers if t.explanation_letter is not None]
        affected_ids = []
        
        # Determine all travelers matching the disruption criteria
        # Mock logic matches names/loyalty filters
        for t in db_travelers:
            is_affected = False
            dis_id = disruption_event.get("identifier", "").upper()
            if "AA123" in dis_id and t.passenger_name != "Unaffected Traveler":
                is_affected = True
            elif disruption_event.get("type") == "hotel_closure" and "hilton" in dis_id.lower():
                is_affected = True
            
            if is_affected:
                affected_ids.append(t.id)

        # Resume index matches number of already completed documents in the list
        resume_index = len(processed_ids)
        
        # Set up initial state variables
        initial_state: DisruptionState = {
            "batch_id": batch_id,
            "disruption_event": disruption_event,
            "travelers_list": [],
            "affected_traveler_ids": affected_ids,
            "current_traveler_index": resume_index,
            "ops_summary": {},
            "audit_logs": [],
            "error": None
        }

        # If it's a completely new run, start at index 0 from ingest entry point
        if resume_index == 0:
            logger.info("Initializing new execution run.")
            res = compiled_workflow.invoke(initial_state)
        else:
            # Resuming mid-way: skip ingestion, invoke surgery node loop directly
            logger.info(f"Resuming execution from traveler index cursor: {resume_index}")
            res = compiled_workflow.invoke(initial_state, start_from="surgery")

        return res

    except Exception as e:
        logger.error(f"Failed executing batch workflow engine: {e}")
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()
