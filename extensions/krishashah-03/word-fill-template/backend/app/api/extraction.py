from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Template
from app.parsers.csv_parser import CSVParseError, parse_csv_input
from app.parsers.json_parser import JSONParseError, parse_json_input
from app.parsers.text_parser import TextParseError, parse_text_input
from app.schemas.extraction import ExtractRequest, ExtractResponse, ValidateRequest
from app.services.ai_extractor import AIExtractionError, extract_fields_with_ai
from app.services.gap_detector import detect_gaps
from app.services.normalization import normalize_record
from app.services.template_engine import build_template_result
from app.services.validator import validate_record

router = APIRouter(prefix="/api", tags=["extraction"])


def _load_template(db: Session, template_id: UUID) -> Template:
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


def _field_schema(template: Template) -> dict:
    return template.schema_json.get("fields", {})


def _conditions(template: Template) -> list[dict]:
    return [
        {
            "condition_key": condition.condition_key,
            "operator": condition.operator,
            "expected_value": condition.expected_value,
            "action": condition.action,
        }
        for condition in template.conditions
    ]


def _run_pipeline(field_schema: dict, conditions: list[dict], raw_data: dict) -> dict:
    normalized_data, normalization_errors = normalize_record(raw_data, field_schema)

    validation_issues = validate_record(normalized_data, field_schema)
    for field, message in normalization_errors.items():
        validation_issues.append({"field": field, "message": message})

    gaps = detect_gaps(normalized_data, field_schema)
    template_result = build_template_result(field_schema, conditions, normalized_data, gaps)

    return {
        "normalized_data": normalized_data,
        "validation_issues": validation_issues,
        "gaps": gaps,
        "conditions": template_result["conditions"],
        "proposed_changes": template_result["proposed_changes"],
    }


@router.post("/extract", response_model=ExtractResponse)
async def extract(payload: ExtractRequest, db: Session = Depends(get_db)):
    template = _load_template(db, payload.template_id)
    field_schema = _field_schema(template)
    conditions = _conditions(template)

    try:
        if payload.input_type == "json":
            raw_data = parse_json_input(payload.content)
        elif payload.input_type == "csv":
            if not isinstance(payload.content, str):
                raise CSVParseError("CSV input must be a string.")
            raw_data = parse_csv_input(payload.content)
        else:
            if not isinstance(payload.content, str):
                raise TextParseError("Text input must be a string.")
            text = parse_text_input(payload.content)
            raw_data = await extract_fields_with_ai(field_schema, text)
    except (JSONParseError, CSVParseError, TextParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = _run_pipeline(field_schema, conditions, raw_data)

    return ExtractResponse(source_type=payload.input_type, raw_data=raw_data, **result)


@router.post("/validate", response_model=ExtractResponse)
def validate(payload: ValidateRequest, db: Session = Depends(get_db)):
    template = _load_template(db, payload.template_id)
    field_schema = _field_schema(template)
    conditions = _conditions(template)

    result = _run_pipeline(field_schema, conditions, payload.normalized_data)

    return ExtractResponse(source_type="revalidation", raw_data=payload.normalized_data, **result)
