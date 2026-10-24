from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import DocumentRun, Gap, Record, Template
from app.schemas.documents import DocumentRunCreate, DocumentRunOut, ReviewRequest
from app.services.gap_detector import detect_gaps

router = APIRouter(prefix="/api/document-runs", tags=["documents"])


@router.post("", response_model=DocumentRunOut)
def create_document_run(payload: DocumentRunCreate, db: Session = Depends(get_db)):
    template = db.get(Template, payload.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    record = Record(
        template_id=template.id,
        source_type=payload.source_type,
        raw_data=payload.raw_data,
        normalized_data=payload.normalized_data,
    )
    db.add(record)
    db.flush()

    field_schema = template.schema_json.get("fields", {})
    gaps = detect_gaps(payload.normalized_data, field_schema)

    document_run = DocumentRun(template_id=template.id, record_id=record.id, status="draft")
    db.add(document_run)
    db.flush()

    for gap in gaps:
        db.add(Gap(document_run_id=document_run.id, field_key=gap["field"], reason=gap["reason"]))

    db.commit()
    db.refresh(document_run)
    return document_run


@router.get("/{run_id}", response_model=DocumentRunOut)
def get_document_run(run_id: UUID, db: Session = Depends(get_db)):
    document_run = db.get(DocumentRun, run_id)
    if document_run is None:
        raise HTTPException(status_code=404, detail="Document run not found.")
    return document_run


@router.post("/{run_id}/review", response_model=DocumentRunOut)
def review_document_run(run_id: UUID, payload: ReviewRequest, db: Session = Depends(get_db)):
    document_run = db.get(DocumentRun, run_id)
    if document_run is None:
        raise HTTPException(status_code=404, detail="Document run not found.")

    document_run.review_data = {
        "applied_changes": payload.applied_changes,
        "resolved_gaps": payload.resolved_gaps,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    document_run.status = payload.status

    for field_key, value in payload.resolved_gaps.items():
        gap = (
            db.query(Gap)
            .filter(Gap.document_run_id == document_run.id, Gap.field_key == field_key)
            .first()
        )
        if gap is not None:
            gap.resolved = True
            gap.resolved_value = value
            gap.resolved_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(document_run)
    return document_run
