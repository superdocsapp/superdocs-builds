from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .models import CorrectivePlan, CoverageReport, Violation
from .offline import generate_offline_plan
from .review import Decision, ReviewItem, undecided_codes
from .superdocs_client import VALID_EXPORT_FORMATS
from .template import build_plan_template_html
from .verifier import verify_coverage


class DraftRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    restaurant: str
    inspection_date: date
    health_department: str
    violations: tuple[Violation, ...]


class DraftResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan: CorrectivePlan
    coverage: CoverageReport
    template_html: str


class ExportRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan: CorrectivePlan
    violations: tuple[Violation, ...]
    decisions: dict[str, Decision]
    format: str = "html"


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant Corrective Plan")

    @app.get("/api/sample")
    def sample() -> dict:
        return _sample_payload()

    @app.post("/api/draft", response_model=DraftResponse)
    def draft(request: DraftRequest) -> DraftResponse:
        plan = generate_offline_plan(
            restaurant=request.restaurant,
            inspection_date=request.inspection_date,
            health_department=request.health_department,
            violations=request.violations,
        )
        coverage = verify_coverage(request.violations, plan)
        template_html = build_plan_template_html(
            restaurant=request.restaurant,
            inspection_date=request.inspection_date,
            health_department=request.health_department,
            violations=request.violations,
        )
        return DraftResponse(plan=plan, coverage=coverage, template_html=template_html)

    @app.post("/api/export")
    def export(request: ExportRequest) -> Response:
        if request.format not in VALID_EXPORT_FORMATS:
            valid = ", ".join(f"'{value}'" for value in sorted(VALID_EXPORT_FORMATS))
            raise HTTPException(
                status_code=400,
                detail=f"export failed: format '{request.format}' is not valid. Use {valid}.",
            )
        review_items = tuple(
            ReviewItem(item=item, decision=request.decisions.get(item.code, "pending"))
            for item in request.plan.items
        )
        pending = undecided_codes(review_items)
        if pending:
            raise HTTPException(
                status_code=409,
                detail=(
                    "export refused: these violation codes are undecided: "
                    f"{', '.join(pending)}. Approve or reject each item before exporting."
                ),
            )
        coverage = verify_coverage(request.violations, request.plan)
        if not coverage.is_complete:
            problems = list(coverage.missing_codes) + list(coverage.uninvited_codes)
            named = ", ".join(problems) if problems else "see coverage report"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"export refused: coverage is incomplete for {named}. "
                    "Fix the cited items before exporting."
                ),
            )
        html = _plan_to_html(request.plan)
        return Response(content=html, media_type="text/html")

    static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()


def _sample_payload() -> dict:
    path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "violations.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_to_html(plan: CorrectivePlan) -> str:
    sections = "\n".join(
        f"""<section>
  <h2>Violation {item.code}</h2>
  <p><strong>Finding:</strong> {item.finding}</p>
  <p><strong>Corrective action:</strong> {item.corrective_action}</p>
  <p><strong>Responsible party:</strong> {item.responsible_party}</p>
  <p><strong>Completion target:</strong> {item.completion_target or "Not specified"}</p>
  <p><strong>Evidence:</strong> {item.evidence or "Not specified"}</p>
</section>"""
        for item in plan.items
    )
    return f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>{plan.restaurant} corrective plan</title></head>
  <body>
    <h1>Corrective Action Plan</h1>
    <p><strong>Restaurant:</strong> {plan.restaurant}</p>
    <p><strong>Inspection date:</strong> {plan.inspection_date.isoformat()}</p>
    <p><strong>Health department:</strong> {plan.health_department}</p>
{sections}
  </body>
</html>
"""
