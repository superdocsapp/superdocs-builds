import re
from typing import Tuple

ANNOTATION_PATTERN = re.compile(
    r"\s*(?:[-–—]+\s*|\s*[\(\[\{]\s*|\s*(?:\/\*|\/\/|#)\s*)(?:no\s+parens?|missing\s+parens?(?:\s+here)?|missing\s+parenthetical|add\s+parens?|no\s+parentheses|missing\s+parens|missing\s+parenthesis)\s*[\)\]\}]?",
    re.IGNORECASE,
)


def format_element(element_type: str, content: str) -> Tuple[str, str, str]:
    """
    Apply deterministic formatting rules to one screenplay element.

    Returns:
        (formatted_text, change_type, reason)
        change_type: capitalization | spacing | indentation | no_change
    """
    if element_type == "scene_heading":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        formatted = cleaned.upper()
        if formatted != content.strip():
            return formatted, "capitalization", "Scene headings must be uppercase"
        return formatted, "no_change", ""

    if element_type == "character":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        formatted = cleaned.upper()
        if formatted != content.strip():
            return formatted, "capitalization", "Character names must be uppercase"
        return formatted, "no_change", ""

    if element_type == "transition":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        formatted = cleaned.upper()
        if not formatted.endswith(":") and not formatted.endswith("."):
            formatted = formatted + ":"
        if formatted != content.strip():
            return formatted, "capitalization", "Transitions must be uppercase"
        return formatted, "no_change", ""

    if element_type == "parenthetical":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        # Extract inner text without outer parentheses if present
        if cleaned.startswith("(") and cleaned.endswith(")"):
            inner = cleaned[1:-1].strip()
        elif cleaned.startswith("("):
            inner = cleaned[1:].strip()
        elif cleaned.endswith(")"):
            inner = cleaned[:-1].strip()
        else:
            inner = cleaned

        inner = ANNOTATION_PATTERN.sub("", inner).strip()
        formatted = f"({inner})"
        if formatted != content.strip():
            reason = "Parentheticals must be enclosed in parentheses with clean spacing"
            return formatted, "spacing", reason
        return formatted, "no_change", ""

    if element_type == "end":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        formatted = cleaned.upper()
        if formatted != content.strip():
            return formatted, "capitalization", "END marker must be uppercase"
        return formatted, "no_change", ""

    if element_type == "shot":
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        formatted = cleaned.upper()
        if formatted != content.strip():
            return formatted, "capitalization", "Shots must be uppercase"
        return formatted, "no_change", ""

    if element_type in ("title", "author", "author_credit", "credit", "page_number"):
        cleaned = ANNOTATION_PATTERN.sub("", content).strip()
        if cleaned != content.strip():
            return cleaned, "spacing", "Removed formatting annotation"
        return content.strip(), "no_change", ""

    # action, dialogue, uncertain, other: clean annotations, preserve content
    cleaned = ANNOTATION_PATTERN.sub("", content).strip()
    if cleaned != content.strip():
        return cleaned, "spacing", "Removed formatting annotation"
    return content.strip(), "no_change", ""

