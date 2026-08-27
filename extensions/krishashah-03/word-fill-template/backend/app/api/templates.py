from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Template
from app.schemas.templates import TemplateConditionOut, TemplateDetail, TemplateFieldDef, TemplateSummary

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateSummary])
def list_templates(db: Session = Depends(get_db)):
    templates = db.execute(select(Template).where(Template.is_active.is_(True))).scalars().all()
    return templates


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(template_id: UUID, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    fields_raw = template.schema_json.get("fields", {})
    fields = {key: TemplateFieldDef(**value) for key, value in fields_raw.items()}

    return TemplateDetail(
        id=template.id,
        name=template.name,
        category=template.category,
        description=template.description,
        version=template.version,
        is_active=template.is_active,
        file_path=template.file_path,
        fields=fields,
        conditions=[TemplateConditionOut.model_validate(c) for c in template.conditions],
    )
