from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from .core import ClaimValidationError, Patent, amend_claim, claims_from_list, delete_claim, diff_claim_sets
from .exporters import export_bytes
from .store import ClaimStore


class ExportBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimManager:
    """Chat-driven amend/delete workflow over one patent's claim set.

    A proposal is a single review item: reviewer approves or rejects it as a
    whole. Approval never silently rewrites a dependent claim's text — the
    transitive dependents an amendment touches are computed once (`core.amend_claim`)
    and carried on the proposal and into `revision_history` so they stay visible
    at every stage, matching the brief: flagged, never silently left inconsistent.
    """

    def __init__(self, store: ClaimStore) -> None:
        self.store = store

    def create(self, patent: Patent) -> dict[str, Any]:
        self.store.save_patent(patent)
        return {"patent_id": patent.patent_id, "revision": patent.revision, "content_hash": patent.content_hash(), "status": patent.status}

    def propose(self, patent_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        patent = self.store.get_patent(patent_id)
        if patent is None:
            raise ClaimValidationError("patent not found")
        proposal_id = str(uuid.uuid4())
        flagged: list[int] = []
        refusal = None
        try:
            action = plan.get("action")
            claim_number = plan["claim_number"]
            if action == "amend":
                proposed_claims, flagged = amend_claim(patent.claims, claim_number, plan["new_text"])
            elif action == "delete":
                proposed_claims = delete_claim(patent.claims, claim_number)
            else:
                raise ClaimValidationError("action must be 'amend' or 'delete'")
            diff = diff_claim_sets(patent.claims, proposed_claims)
            state = "awaiting_review"
        except (KeyError, ClaimValidationError) as error:
            proposed_claims = patent.claims
            diff = []
            state = "blocked"
            refusal = str(error)
        self.store.save_proposal(proposal_id, patent_id, patent.revision, {
            "requested": plan, "proposed_claims": proposed_claims.as_list(),
            "diff": diff, "flagged_dependents": flagged, "refusal": refusal,
        }, state)
        return {
            "proposal_id": proposal_id, "patent_id": patent_id, "base_revision": patent.revision,
            "state": state, "diff": diff, "flagged_dependents": flagged,
            "proposed_claims": proposed_claims.as_list(), "refusal": refusal,
        }

    def decide(self, proposal_id: str, decision: str, approver: str) -> dict[str, Any]:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise ClaimValidationError("proposal not found")
        if proposal["state"] != "awaiting_review":
            raise ClaimValidationError("proposal is not awaiting review")
        if decision not in {"approved", "rejected"} or not approver:
            raise ClaimValidationError("decision must be approved or rejected with an approver")
        if decision == "rejected":
            self.store.decide_proposal(proposal_id, "rejected", {"approver": approver, "timestamp": _now()})
            return {"proposal_id": proposal_id, "state": "rejected", "applied": False}
        patent = self.store.get_patent(proposal["patent_id"])
        if patent is None or patent.revision != proposal["base_revision"]:
            raise ExportBlocked("STALE_PROPOSAL", "patent changed since proposal; start a fresh review")
        proposed_claims = claims_from_list(proposal["plan"]["proposed_claims"])
        requested = proposal["plan"]["requested"]
        new_patent = Patent(
            patent_id=patent.patent_id, title=patent.title, applicant=patent.applicant,
            revision=patent.revision + 1, status="review-ready", claims=proposed_claims,
            revision_history=[*patent.revision_history, {
                "revision": patent.revision + 1, "author": approver, "action": requested.get("action"),
                "claim_number": requested.get("claim_number"), "flagged_dependents": proposal["plan"]["flagged_dependents"],
                "reason": requested.get("reason", ""), "timestamp": _now(),
            }],
        )
        self.store.save_patent(new_patent)
        self.store.decide_proposal(proposal_id, "approved", {"approver": approver, "timestamp": _now(), "applied_revision": new_patent.revision})
        return {
            "proposal_id": proposal_id, "state": "approved", "applied": True, "revision": new_patent.revision,
            "content_hash": new_patent.content_hash(), "flagged_dependents": proposal["plan"]["flagged_dependents"],
        }

    def export(self, patent_id: str, proposal_id: str, format_name: str = "json") -> dict[str, Any]:
        proposal = self.store.get_proposal(proposal_id)
        patent = self.store.get_patent(patent_id)
        if patent is None or proposal is None or proposal["patent_id"] != patent_id:
            raise ExportBlocked("NOT_FOUND", "patent or proposal not found")
        if proposal["state"] != "approved":
            raise ExportBlocked("REVIEW_GATE_BLOCKED", "export requires an approved proposal")
        if proposal["decision"].get("applied_revision") != patent.revision:
            raise ExportBlocked("STALE_PROPOSAL", "proposal does not describe the current patent revision")
        mime_type, artifact = export_bytes(patent, format_name)
        return {
            "format": format_name, "mime_type": mime_type, "patent": patent.to_dict(), "artifact": artifact,
            "patent_hash": patent.content_hash(), "disclaimer": "Draft for attorney review - not a filed or certified document",
            "exported_at": _now(),
        }
