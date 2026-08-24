from pathlib import Path


DOCUMENT_TYPES = {
    "research_narrative",
    "data_management_plan",
    "investigator_cv",
    "facilities_statement",
    "budget_justification",
    "unknown",
}


def classify_document(filename: str, content: str = "") -> str:
    """Classify a grant document using filename first, then content."""

    name = Path(filename).stem.lower().replace("-", "_").replace(" ", "_")
    text = content.lower()

    # Filename is the strongest signal.
    if "budget" in name:
        return "budget_justification"

    if "data_management" in name:
        return "data_management_plan"

    if "research_narrative" in name:
        return "research_narrative"

    if "facilities" in name:
        return "facilities_statement"

    if "investigator" in name or name.endswith("_cv") or "_cv_" in name:
        return "investigator_cv"

    # Content-based fallback.
    if "budget justification" in text:
        return "budget_justification"

    if "data management plan" in text:
        return "data_management_plan"

    if "research narrative" in text:
        return "research_narrative"

    if "facilities statement" in text:
        return "facilities_statement"

    if "curriculum vitae" in text or "professional experience" in text:
        return "investigator_cv"

    return "unknown"