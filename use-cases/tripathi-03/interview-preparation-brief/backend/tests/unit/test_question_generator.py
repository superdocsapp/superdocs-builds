"""Unit tests for interview question evidence grounding."""

from app.schemas.questions import (
    NO_EVIDENCE,
    Difficulty,
    InterviewQuestionItem,
    InterviewQuestionRequest,
)
from app.services.questions.generator import InterviewQuestionGenerator


def test_grounds_evidence_or_returns_no_evidence():
    service = InterviewQuestionGenerator()
    resume = "Built payment APIs with FastAPI at Acme."
    ok = service._ground_evidence("Built payment APIs with FastAPI at Acme.", resume)
    bad = service._ground_evidence("Led quantum research at NASA", resume)
    assert ok.startswith("Built payment")
    assert bad == NO_EVIDENCE


def test_normalize_adds_revision_placeholders_for_gaps():
    service = InterviewQuestionGenerator()
    resume = "Python developer."
    items = service._normalize_items(
        [
            InterviewQuestionItem(
                question="Explain Kubernetes networking.",
                difficulty=Difficulty.HARD,
                expected_answer="Discuss CNI and services.",
                resume_evidence="Invented Kubernetes at Google",
                missing_knowledge=["Kubernetes", "CNI"],
                revision_links=[],
            )
        ],
        resume,
        "technical",
    )
    assert len(items) == 1
    assert items[0].resume_evidence == NO_EVIDENCE
    assert items[0].missing_knowledge == ["Kubernetes", "CNI"]
    assert len(items[0].revision_links) == 2
    assert items[0].revision_links[0].url.startswith("https://revise.local/topic/technical/")


def test_request_validation_requires_core_inputs():
    req = InterviewQuestionRequest(
        resume_text="Resume body with enough content",
        jd_text="JD body with enough content",
        company_name="Acme",
        company_data={"industry": "Unknown"},
    )
    assert req.company_name == "Acme"
