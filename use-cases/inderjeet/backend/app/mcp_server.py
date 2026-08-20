import json
import logging
from typing import Dict, Any, List, Optional
from app.db.session import SessionLocal
from app.db.models import DisruptionBatch, TravelerManifest, AuditLog
from app.workflows.engine import run_workflow

logger = logging.getLogger(__name__)

class MCPServer:
    """
    Exposes the Disruption Re-Issue Engine capabilities as machine-callable tools
    via the Model Context Protocol (MCP) spec.
    """
    def __init__(self):
        self.tools = {
            "trigger_disruption_batch": self.trigger_disruption_batch,
            "get_batch_status": self.get_batch_status,
            "submit_approval_decision": self.submit_approval_decision
        }

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Entry point to invoke tools programmatically."""
        if name not in self.tools:
            return json.dumps({"error": f"Tool '{name}' not found."})
        try:
            res = self.tools[name](**arguments)
            return json.dumps(res)
        except Exception as e:
            logger.error(f"Error executing MCP tool '{name}': {e}")
            return json.dumps({"error": str(e)})

    def trigger_disruption_batch(self, disruption_details_json: str, manifest_json: str) -> Dict[str, Any]:
        """
        Triggers a new disruption processing run.
        Exposes tool: trigger_disruption_batch
        """
        db = SessionLocal()
        try:
            details = json.loads(disruption_details_json)
            manifest = json.loads(manifest_json)

            # Create new batch record
            batch = DisruptionBatch(
                disruption_details=details,
                status="INGESTED"
            )
            db.add(batch)
            db.flush() # Populate batch.id

            # Create traveler records
            for entry in manifest:
                t = TravelerManifest(
                    batch_id=batch.id,
                    passenger_name=entry.get("passenger_name"),
                    email=entry.get("email"),
                    language=entry.get("language", "en"),
                    loyalty_status=entry.get("loyalty_status", "STANDARD")
                )
                db.add(t)

            log = AuditLog(
                batch_id=batch.id,
                stage="MCP",
                message="Batch created and initialized via MCP tool trigger."
            )
            db.add(log)
            db.commit()

            # Execute LangGraph workflow asynchronously or synchronously for MVP/CLI tool
            run_workflow(batch.id)

            return {
                "batch_id": batch.id,
                "status": "processing",
                "message": "Batch processing initiated successfully."
            }
        except Exception as e:
            db.rollback()
            return {"error": f"Failed to trigger batch: {e}"}
        finally:
            db.close()

    def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """
        Returns status, operation cost, and current stage of the batch.
        Exposes tool: get_batch_status
        """
        db = SessionLocal()
        try:
            batch = db.query(DisruptionBatch).filter(DisruptionBatch.id == batch_id).first()
            if not batch:
                return {"error": f"Batch {batch_id} not found."}

            travelers = db.query(TravelerManifest).filter(TravelerManifest.batch_id == batch_id).all()
            
            travelers_data = []
            for t in travelers:
                travelers_data.append({
                    "id": t.id,
                    "passenger_name": t.passenger_name,
                    "approval_status": t.approval_status,
                    "voucher_status": t.voucher_status,
                    "cost_usd": t.cost_usd
                })

            return {
                "batch_id": batch_id,
                "status": batch.status,
                "total_cost_usd": batch.total_cost_usd,
                "total_operations_spent": batch.total_operations_spent,
                "travelers": travelers_data
            }
        finally:
            db.close()

    def submit_approval_decision(self, batch_id: str, traveler_id: str, decision: str, letter_text: Optional[str] = None) -> Dict[str, Any]:
        """
        Submits human-in-the-loop decision (APPROVED or REJECTED) on a traveler bundle.
        Exposes tool: submit_approval_decision
        """
        if decision.upper() not in ["APPROVED", "REJECTED"]:
            return {"error": "Decision must be 'APPROVED' or 'REJECTED'."}

        db = SessionLocal()
        try:
            t = db.query(TravelerManifest).filter(
                TravelerManifest.id == traveler_id,
                TravelerManifest.batch_id == batch_id
            ).first()

            if not t:
                return {"error": f"Traveler {traveler_id} not found in batch {batch_id}."}

            t.approval_status = decision.upper()
            if letter_text:
                t.explanation_letter = letter_text

            log = AuditLog(
                batch_id=batch_id,
                stage="MCP_APPROVAL",
                message=f"Passenger {t.passenger_name} set to {decision.upper()} via machine client."
            )
            db.add(log)
            db.commit()

            return {
                "traveler_id": traveler_id,
                "status": t.approval_status,
                "message": f"Successfully recorded {decision} choice."
            }
        except Exception as e:
            db.rollback()
            return {"error": str(e)}
        finally:
            db.close()
