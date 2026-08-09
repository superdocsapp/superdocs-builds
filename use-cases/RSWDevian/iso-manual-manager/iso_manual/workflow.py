from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import uuid
from typing import Any

from .model import Manual, ManualError, parse_mermaid, validate_manual
from .store import ManualStore
from .exporters import export_bytes


class ExportBlocked(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ManualManager:
    def __init__(self, store: ManualStore):
        self.store = store

    def create(self, manual: Manual) -> dict[str, Any]:
        validate_manual(manual)
        self.store.save_manual(manual)
        return {"manual_id": manual.manual_id, "revision": manual.revision, "content_hash": manual.content_hash(), "status": manual.status}

    def propose(self, manual_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        manual = self.store.get_manual(manual_id)
        if manual is None:
            raise ManualError("manual not found")
        proposal_id = str(uuid.uuid4())
        try:
            proposed = self._apply_plan(manual, plan)
            validate_manual(proposed)
            self._assert_consistency(proposed, plan["section_id"], plan["diagram_id"])
            state = "awaiting_review"
        except (KeyError, ManualError) as error:
            proposed = manual
            state = "blocked"
            plan = {**plan, "refusal": str(error)}
        self.store.save_proposal(proposal_id, manual_id, manual.revision, {"requested": plan, "proposed": proposed.to_dict()}, state)
        return {"proposal_id": proposal_id, "manual_id": manual_id, "base_revision": manual.revision, "state": state, "proposed": proposed.to_dict(), "refusal": plan.get("refusal")}

    def decide(self, proposal_id: str, decision: str, approver: str) -> dict[str, Any]:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise ManualError("proposal not found")
        if proposal["state"] != "awaiting_review":
            raise ManualError("proposal is not awaiting review")
        if decision not in {"approved", "rejected"} or not approver:
            raise ManualError("decision must be approved or rejected with an approver")
        if decision == "rejected":
            self.store.decide_proposal(proposal_id, "rejected", {"approver": approver, "timestamp": _now()})
            return {"proposal_id": proposal_id, "state": "rejected", "applied": False}
        manual = self.store.get_manual(proposal["manual_id"])
        if manual is None or manual.revision != proposal["base_revision"]:
            raise ExportBlocked("STALE_PROPOSAL", "manual changed since proposal; start a fresh review")
        proposed = Manual.from_dict(proposal["plan"]["proposed"])
        proposed.revision = manual.revision + 1
        proposed.revision_history = [*manual.revision_history, {"revision": proposed.revision, "author": approver, "reason": proposal["plan"]["requested"].get("reason", "approved update"), "changed_sections": [proposal["plan"]["requested"]["section_id"]], "timestamp": _now()}]
        proposed.status = "review-ready"
        self.store.save_manual(proposed)
        self.store.decide_proposal(proposal_id, "approved", {"approver": approver, "timestamp": _now(), "applied_revision": proposed.revision})
        return {"proposal_id": proposal_id, "state": "approved", "applied": True, "revision": proposed.revision, "content_hash": proposed.content_hash()}

    def export(self, manual_id: str, proposal_id: str, format_name: str = "json") -> dict[str, Any]:
        proposal = self.store.get_proposal(proposal_id)
        manual = self.store.get_manual(manual_id)
        if manual is None or proposal is None or proposal["manual_id"] != manual_id:
            raise ExportBlocked("NOT_FOUND", "manual or proposal not found")
        if proposal["state"] != "approved":
            raise ExportBlocked("REVIEW_GATE_BLOCKED", "export requires an approved paired proposal")
        if proposal["decision"].get("applied_revision") != manual.revision:
            raise ExportBlocked("STALE_PROPOSAL", "proposal does not describe the current manual revision")
        mime_type, artifact = export_bytes(manual, format_name)
        return {"format": format_name, "mime_type": mime_type, "manual": manual.to_dict(), "artifact": artifact, "manual_hash": manual.content_hash(), "disclaimer": "Review-ready draft - not ISO certified", "exported_at": _now()}

    def _apply_plan(self, manual: Manual, plan: dict[str, Any]) -> Manual:
        section_id, diagram_id = plan["section_id"], plan["diagram_id"]
        section = next(section for section in manual.sections if section["section_id"] == section_id)
        diagram = next(diagram for diagram in manual.diagrams if diagram.diagram_id == diagram_id)
        if section.get("diagram_ref") != diagram_id:
            raise ManualError("section and diagram are not linked")
        changed_sections = plan.get("changed_sections", [section_id])
        changed_diagrams = plan.get("changed_diagrams", [diagram_id])
        if changed_sections != [section_id] or changed_diagrams != [diagram_id]:
            raise ManualError("proposal scope includes objects outside the declared section and diagram")
        proposed = deepcopy(manual)
        proposed_section = next(item for item in proposed.sections if item["section_id"] == section_id)
        proposed_section["body_blocks"] = deepcopy(plan["body_blocks"])
        proposed_diagram = parse_mermaid(diagram_id, plan["diagram_source"])
        proposed.diagrams = [proposed_diagram if item.diagram_id == diagram_id else item for item in proposed.diagrams]
        return proposed

    def _assert_consistency(self, manual: Manual, section_id: str, diagram_id: str) -> None:
        section = next(item for item in manual.sections if item["section_id"] == section_id)
        diagram = next(item for item in manual.diagrams if item.diagram_id == diagram_id)
        prose_steps = {block["step_id"] for block in section["body_blocks"] if block.get("type") == "step"}
        diagram_steps = set(diagram.nodes)
        if prose_steps != diagram_steps:
            raise ManualError(f"prose and diagram step IDs differ: prose={sorted(prose_steps)} diagram={sorted(diagram_steps)}")
        if any(source not in diagram.nodes or target not in diagram.nodes for source, target in diagram.edges):
            raise ManualError("diagram contains an edge to an unknown node")
