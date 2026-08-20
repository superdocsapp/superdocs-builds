"""Fail-closed local review decision application and recovery state."""
from __future__ import annotations
from typing import Any
from .staging import proposal_slot, critical_change_allowed

def apply_decisions(proposals: list[dict[str, Any]], decisions: dict[str, bool], mapping: dict[str, dict[str, Any]], *, document_id: str, base_version: Any) -> dict[str, Any]:
    seen=set(); approved=[]; rejected=[]
    for proposal in proposals:
        change_id=proposal.get("change_id")
        if not change_id or change_id in seen: raise ValueError("duplicate proposal change_id")
        seen.add(change_id)
        slot=proposal_slot(proposal, mapping)
        if proposal.get("document_id") != document_id or str(proposal.get("base_version")) != str(base_version): raise ValueError("stale approval or wrong document")
        allowed, reason=critical_change_allowed(slot, proposal.get("old_html", ""), proposal.get("new_html", ""))
        decision=bool(decisions.get(change_id, False)) and allowed
        (approved if decision else rejected).append({"change_id":change_id,"slot_id":slot,"reason":reason})
    return {"approved":approved,"rejected":rejected,"approved_content_once":len(approved)==len({x["change_id"] for x in approved}),"rejected_content_absent":not any(x["change_id"] in {a["change_id"] for a in approved} for x in rejected)}
