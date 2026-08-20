from pathlib import Path

from app.services.agreement_parser import (
    extract_docx_sections,
)
from app.services.deviation_analyzer import (
    analyze_deviations,
)
from app.services.playbook_classifier import (
    classify_deviation,
)

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.redline_review import (
    RedlineFinding,
    RedlineReview,
)


def analyze_agreements(
    master_path: str | Path,
    dealer_path: str | Path,
    playbook_path: str | Path,
) -> dict:

    master_sections = extract_docx_sections(
        master_path
    )

    dealer_sections = extract_docx_sections(
        dealer_path
    )

    playbook_sections = extract_docx_sections(
        playbook_path
    )

    deviations = analyze_deviations(
        master_sections=master_sections,
        dealer_sections=dealer_sections,
    )

    classified = [
        classify_deviation(deviation)
        for deviation in deviations
    ]

    return {
        "master_sections": master_sections,
        "dealer_sections": dealer_sections,
        "playbook_sections": playbook_sections,
        "deviations": classified,
        "summary": {
            "total": len(classified),
            "pre_approved": sum(
                1
                for item in classified
                if item["classification"]
                == "PRE-APPROVED"
            ),
            "escalate": sum(
                1
                for item in classified
                if item["classification"]
                == "ESCALATE"
            ),
            "refuse": sum(
                1
                for item in classified
                if item["classification"]
                == "REFUSE"
            ),
        },
    }

async def create_redline_review(
    db: AsyncSession,
    session_id: str,
    analysis: dict,
) -> RedlineReview:

    review = RedlineReview(
        session_id=session_id,
        status="pending",
    )

    db.add(review)

    await db.flush()

    for deviation in analysis["deviations"]:
        finding = RedlineFinding(
            review_id=review.id,
            section=deviation["section"],
            master_text=deviation.get("master_text"),
            dealer_text=deviation.get("dealer_text"),
            deviation_type=deviation["deviation_type"],
            similarity=deviation.get("similarity"),
            classification=deviation["classification"],
            reason=deviation["reason"],
            counter_position=deviation["counter_position"],
            decision="pending",
        )

        db.add(finding)

    await db.commit()

    await db.refresh(review)

    return review

