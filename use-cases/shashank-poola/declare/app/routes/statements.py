from fastapi import APIRouter

from routes.errors import failure
from schemas.declare import StatementRequest
from utils.review import review_issues
from utils.statements import render_statements

router = APIRouter()


@router.post("/statements")
async def statements(facts: StatementRequest):
    issues = review_issues(facts)
    if issues:
        return failure(422, "REVIEW_REQUIRED", issues)
    try:
        return {"success": True, "data": render_statements(facts), "error": None}
    except Exception:
        return failure(500, "STATEMENTS_RENDER_FAILED")
