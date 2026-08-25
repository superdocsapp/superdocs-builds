import re
from typing import Set

ANNOTATION_PATTERN = re.compile(
    r"\s*(?:[-–—]+\s*|\s*[\(\[\{]\s*|\s*(?:\/\*|\/\/|#)\s*)(?:no\s+parens?|missing\s+parens?(?:\s+here)?|missing\s+parenthetical|add\s+parens?|no\s+parentheses|missing\s+parens|missing\s+parenthesis)\s*[\)\]\}]?",
    re.IGNORECASE,
)

PROTECTED_TYPES = {
    "dialogue", "action", "parenthetical", "title", "author", "author_credit", "credit",
    "end", "shot", "page_number", "uncertain", "other"
}


def _word_tokens(text: str) -> Set[str]:
    cleaned = ANNOTATION_PATTERN.sub("", text)
    return set(re.sub(r"[^\w\s]", "", cleaned.lower()).split())


class ContentDriftValidator:
    """Checks that formatting did not change the words in protected element types."""

    def has_drift(self, original: str, formatted: str, element_type: str) -> bool:
        if element_type not in PROTECTED_TYPES:
            return False
        original_words = _word_tokens(original)
        formatted_words = _word_tokens(formatted)
        return original_words != formatted_words

