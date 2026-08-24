from typing import Any, Dict


DEFAULT_PAGE_LIMITS = {
    "research_narrative": 5,
    "data_management_plan": 2,
    "facilities_statement": 2,
    "budget_justification": 2,
    "investigator_cv": 3,
}


def estimate_pages(
    text: str,
    chars_per_page: int = 3000,
) -> int:
    """
    Estimate page count from text length.

    This is intentionally conservative and deterministic for the
    local validation/demo pipeline. Actual exported pagination can
    vary by font, margins, spacing, and template.
    """

    normalized = " ".join(
        str(text).split()
    ).strip()

    if not normalized:
        return 0

    return max(
        1,
        (len(normalized) + chars_per_page - 1)
        // chars_per_page,
    )


def check_page_limit(
    document_type: str,
    text: str,
    page_limit: int | None = None,
) -> Dict[str, Any]:
    """Check whether a document fits its configured page limit."""

    limit = page_limit

    if limit is None:
        limit = DEFAULT_PAGE_LIMITS.get(
            document_type
        )

    if limit is None:
        return {
            "checked": False,
            "document_type": document_type,
            "page_limit": None,
            "estimated_pages": None,
            "within_limit": True,
            "status": "not_configured",
        }

    estimated_pages = estimate_pages(text)

    return {
        "checked": True,
        "document_type": document_type,
        "page_limit": limit,
        "estimated_pages": estimated_pages,
        "within_limit": estimated_pages <= limit,
        "status": (
            "met"
            if estimated_pages <= limit
            else "exceeded"
        ),
    }


def build_tightening_instruction(
    document_type: str,
    page_limit: int,
    estimated_pages: int,
) -> str:
    """
    Build the SuperDocs instruction used when a document exceeds
    its page limit.
    """

    return (
        f"Tighten the {document_type.replace('_', ' ')} "
        f"so that it fits within a maximum of {page_limit} pages. "
        f"The current estimated length is {estimated_pages} pages. "
        "Reduce unnecessary repetition, wordiness, and redundant "
        "phrasing while preserving the argument, factual claims, "
        "specific aims, methodology, named investigators, numbers, "
        "citations, expected outcomes, and significance. "
        "Do not invent facts. Do not remove substantive evidence. "
        "Do not truncate the document mechanically. "
        "Rewrite sentences and paragraphs for concision instead."
    )


def enforce_page_limit_locally(
    document_type: str,
    text: str,
    page_limit: int,
) -> Dict[str, Any]:
    """
    Perform deterministic page-limit validation without deleting
    content.

    Actual prose tightening is delegated to SuperDocs.
    """

    check = check_page_limit(
        document_type,
        text,
        page_limit,
    )

    return {
        **check,
        "requires_superdocs_edit": not check["within_limit"],
        "instruction": (
            build_tightening_instruction(
                document_type,
                page_limit,
                check["estimated_pages"],
            )
            if not check["within_limit"]
            else None
        ),
    }