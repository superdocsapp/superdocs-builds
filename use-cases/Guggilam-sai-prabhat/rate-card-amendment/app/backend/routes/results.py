"""Results: export the approved contract + amendment letter, and the
consolidated control report (including excluded/escalated cases).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.backend.case_view import render_amendment_letter
from app.backend.lookups import get_case_or_404, get_run_or_404
from app.backend.schemas import ControlReportOut, ControlReportRowOut, ExportOut, ExportRequestIn
from app.backend.store import store
from app.backend.superdocs_dependency import get_superdocs_http_client
from src.amendment_case import Failure, rejected_change_ids, unresolved_change_ids
from src.case_state import CaseState
from src.integrations.superdocs_client import SuperDocsError, export_document

router = APIRouter()


@router.post("/runs/{run_id}/cases/{case_id}/export", response_model=ExportOut)
async def export_case(
    run_id: str,
    case_id: str,
    payload: ExportRequestIn,
    client: httpx.AsyncClient = Depends(get_superdocs_http_client),
):
    existing = store.get_idempotent_response(payload.idempotency_key)
    if existing is not None:
        return existing

    run = get_run_or_404(run_id)
    case = get_case_or_404(run, case_id)

    if case.state == CaseState.PARTIALLY_APPROVED:
        raise HTTPException(
            status_code=409,
            detail={
                "what": f"case '{case_id}' has unresolved or rejected pending changes and cannot be fully exported",
                "likely_cause": (
                    f"unresolved change_ids: {unresolved_change_ids(case)}; "
                    f"rejected change_ids: {rejected_change_ids(case)}"
                ),
                "next_action": "resolve every pending change via POST .../decisions before exporting, or export only once all changes are approved",
            },
        )

    if case.state != CaseState.APPROVED:
        raise HTTPException(
            status_code=409,
            detail={
                "what": f"case '{case_id}' is in state '{case.state.value}', not ready to export",
                "likely_cause": "the case must reach 'approved' (all proposed changes approved) before export",
                "next_action": "check GET .../review and resolve any pending decisions first",
            },
        )

    try:
        if case.superdocs_session_id is not None:
            exported_contract = await export_document(client, case.superdocs_session_id, payload.format)
        else:
            # No SuperDocs changes were needed (e.g. rates already matched) —
            # export the untouched original contract text.
            with open(case.analysis.document_id, "r", encoding="utf-8") as handle:
                exported_contract = handle.read()
    except SuperDocsError as exc:
        case.fail(Failure(**exc.to_dict()))
        raise HTTPException(status_code=502, detail=exc.to_dict()) from exc

    exported_letter = render_amendment_letter(case)
    case.exported_contract_text = exported_contract
    case.exported_letter_text = exported_letter
    case.set_state(CaseState.EXPORTED)

    result = ExportOut(
        case_id=case.case_id,
        state=case.state.value,
        exported_contract_text=exported_contract,
        exported_letter_text=exported_letter,
    )
    store.save_idempotent_response(payload.idempotency_key, result)
    return result


def _to_control_row(case) -> ControlReportRowOut:
    eligibility = case.analysis.eligibility
    return ControlReportRowOut(
        case_id=case.case_id,
        partner_name=case.analysis.partner_contract.partner_name,
        contract_identifier=case.analysis.partner_contract.contract_identifier,
        state=case.state.value,
        eligibility_status=eligibility.status.value,
        amendment_mechanism=eligibility.amendment_mechanism,
        pricing_lock_active=eligibility.pricing_lock_active,
        mutual_consent_required=eligibility.mutual_consent_required,
        requires_human_escalation=eligibility.requires_human_escalation,
        prompt_injection_present=eligibility.prompt_injection_present,
        exported=case.state == CaseState.EXPORTED,
    )


@router.get("/runs/{run_id}/control-report", response_model=ControlReportOut)
async def get_control_report(run_id: str):
    run = get_run_or_404(run_id)
    rows = [_to_control_row(c) for c in run.cases.values()]
    excluded = [
        r
        for r in rows
        if r.state in (CaseState.BLOCKED.value, CaseState.REQUIRES_REVIEW.value, CaseState.FAILED.value)
    ]
    return ControlReportOut(run_id=run_id, rows=rows, excluded_or_escalated=excluded)
