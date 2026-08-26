"""Intake: upload contracts + a new rate card, choose effective date +
template, optional dry-run, and kick off analysis for every contract.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.backend.case_view import to_case_summary
from app.backend.schemas import RunSummaryOut
from app.backend.store import Run, store
from src.amendment_case import build_case
from src.extraction.rate_tables import extract_rate_entries
from src.extraction.text_extraction import extract_document_text

router = APIRouter()

_UPLOAD_ROOT = Path("data/uploads")
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("/runs", response_model=RunSummaryOut)
async def create_run(
    idempotency_key: str = Form(...),
    proposed_effective_date: str = Form(...),
    template_name: str = Form("amendment_letter_template.md"),
    dry_run: bool = Form(False),
    reference_date_override: str | None = Form(None),
    contracts: list[UploadFile] = None,  # type: ignore[assignment]
    old_rate_card: UploadFile = None,  # type: ignore[assignment]
    new_rate_card: UploadFile = None,  # type: ignore[assignment]
):
    existing = store.get_idempotent_response(idempotency_key)
    if existing is not None:
        return existing

    if not contracts:
        raise HTTPException(
            status_code=422,
            detail={
                "what": "no contract files were uploaded",
                "likely_cause": "the intake form's 'contracts' field was empty",
                "next_action": "attach at least one partner contract file and resubmit",
            },
        )
    if new_rate_card is None:
        raise HTTPException(
            status_code=422,
            detail={
                "what": "no new rate card was uploaded",
                "likely_cause": "the intake form's 'new_rate_card' field was empty",
                "next_action": "attach the proposed new rate-card CSV and resubmit",
            },
        )

    try:
        effective_date = datetime.strptime(proposed_effective_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "what": f"could not parse proposed_effective_date '{proposed_effective_date}'",
                "likely_cause": "the date was not in YYYY-MM-DD format",
                "next_action": "resubmit with proposed_effective_date=YYYY-MM-DD",
            },
        ) from exc

    reference_date = (
        datetime.strptime(reference_date_override, "%Y-%m-%d").date()
        if reference_date_override
        else date.today()
    )

    run_id = str(uuid.uuid4())
    run_dir = _UPLOAD_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    new_rate_card_bytes = await new_rate_card.read()
    new_rate_card_path = run_dir / (new_rate_card.filename or "new_rate_card.csv")
    new_rate_card_path.write_bytes(new_rate_card_bytes)
    new_entries = extract_rate_entries(
        str(new_rate_card_path), extract_document_text(str(new_rate_card_path))
    )

    if old_rate_card is not None:
        old_bytes = await old_rate_card.read()
        old_rate_card_path = run_dir / (old_rate_card.filename or "old_rate_card.csv")
        old_rate_card_path.write_bytes(old_bytes)
        old_entries = extract_rate_entries(
            str(old_rate_card_path), extract_document_text(str(old_rate_card_path))
        )
    else:
        old_entries = []

    run = Run(
        run_id=run_id,
        dry_run=dry_run,
        proposed_effective_date=proposed_effective_date,
        template_name=template_name,
    )

    for upload in contracts:
        content = await upload.read()
        contract_path = run_dir / (upload.filename or f"contract_{uuid.uuid4().hex}.md")
        contract_path.write_bytes(content)

        case_id = str(uuid.uuid4())
        try:
            case = build_case(
                case_id=case_id,
                contract_path=str(contract_path),
                old_rate_entries=old_entries,
                new_rate_entries=new_entries,
                reference_date=reference_date,
                proposed_effective_date=effective_date,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured failure, not swallowed
            raise HTTPException(
                status_code=500,
                detail={
                    "what": f"analysis pipeline failed for uploaded contract '{upload.filename}'",
                    "likely_cause": str(exc),
                    "next_action": "confirm the file is a readable UTF-8 text/markdown contract and resubmit",
                },
            ) from exc

        run.cases[case_id] = case

    store.save_run(run)
    response = RunSummaryOut(
        run_id=run.run_id,
        dry_run=run.dry_run,
        proposed_effective_date=run.proposed_effective_date,
        cases=[to_case_summary(c) for c in run.cases.values()],
    )
    store.save_idempotent_response(idempotency_key, response)
    return response
