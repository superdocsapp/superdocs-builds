import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import documents, extraction, templates
from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import Template, TemplateCondition

app = FastAPI(title="AI Word Template Filler", version="0.1.0")

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(templates.router)
app.include_router(extraction.router)
app.include_router(documents.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _seed_templates_from_disk() -> None:
    """Register every templates/<category>/schema.json on disk as a Template row.

    Keeps the DB template registry in sync with the filesystem so the app is
    usable immediately after `psql -f schema.sql` with no manual seeding step.
    """
    templates_dir = settings.templates_dir
    if not templates_dir.exists():
        return

    db = SessionLocal()
    try:
        for category_dir in sorted(templates_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            schema_path = category_dir / "schema.json"
            if not schema_path.exists():
                continue

            schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
            template_name = schema_data.get("name", schema_data.get("template_id", category_dir.name))

            docx_candidates = sorted(category_dir.glob("*.docx"))
            file_path = str(docx_candidates[0]) if docx_candidates else ""

            template = db.execute(
                select(Template).where(Template.name == template_name)
            ).scalar_one_or_none()

            if template is None:
                template = Template(
                    name=template_name,
                    category=schema_data.get("category", "General"),
                    description=schema_data.get("description"),
                    file_path=file_path,
                    schema_json=schema_data,
                )
                db.add(template)
            else:
                template.schema_json = schema_data
                template.file_path = file_path or template.file_path

            db.flush()

            db.query(TemplateCondition).filter(TemplateCondition.template_id == template.id).delete()
            for condition in schema_data.get("conditions", []):
                db.add(
                    TemplateCondition(
                        template_id=template.id,
                        condition_key=condition["condition_key"],
                        operator=condition.get("operator", "=="),
                        expected_value=condition.get("expected_value"),
                        action=condition.get("action", "include"),
                    )
                )

        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    try:
        _seed_templates_from_disk()
    except Exception as exc:  # noqa: BLE001 - don't let seeding failures block startup
        print(f"[startup] Skipping template seeding: {exc}")
