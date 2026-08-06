"""Interview question generation API."""

from fastapi import APIRouter, Depends

from app.api.deps import get_question_generator
from app.core.logging import get_logger
from app.schemas.questions import InterviewQuestionRequest, InterviewQuestionResponse
from app.services.questions.generator import InterviewQuestionGenerator

router = APIRouter()
logger = get_logger(__name__)


@router.post("/generate", response_model=InterviewQuestionResponse)
async def generate_interview_questions(
    payload: InterviewQuestionRequest,
    service: InterviewQuestionGenerator = Depends(get_question_generator),
) -> InterviewQuestionResponse:
    """
    Generate categorized interview questions from resume, JD, and company data.

    Each question includes difficulty, expected answer, resume evidence,
    missing knowledge, and revision link placeholders.
    """
    result = await service.generate(payload)
    logger.info(
        "API question generation company=%s total=%s",
        result.company_name,
        result.totals.get("all", 0),
    )
    return result
