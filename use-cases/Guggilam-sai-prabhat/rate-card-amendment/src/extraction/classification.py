"""Step 1: document classification.

Classification is a deterministic rule over file path/name and a small set of
content markers — no model reasoning is involved, so this stays fully
separate from anything model-driven (see rules-vs-model separation goal).
"""

from __future__ import annotations

import os

from src.domain.models import DocumentType


def classify_document(file_path: str, text: str) -> DocumentType:
    """Classify a corpus document from its path and content, deterministically."""

    normalized_path = file_path.replace("\\", "/").lower()
    base_name = os.path.basename(normalized_path)

    if "/playbooks/" in normalized_path or "playbook" in base_name:
        return DocumentType.PLAYBOOK
    if "amendment_letter_template" in base_name:
        return DocumentType.AMENDMENT_LETTER_TEMPLATE
    if "/contracts/" in normalized_path or base_name.startswith("contract_"):
        return DocumentType.CONTRACT
    if "/rate-cards/" in normalized_path or "rate_card" in base_name:
        return DocumentType.RATE_CARD

    lowered = text.lower()
    if "rate_card_id" in lowered and "," in text.splitlines()[0]:
        return DocumentType.RATE_CARD
    if "amendment notice" in lowered and "template" in lowered:
        return DocumentType.AMENDMENT_LETTER_TEMPLATE
    if "playbook" in lowered:
        return DocumentType.PLAYBOOK
    if "agreement" in lowered and ("parties" in lowered or "party" in lowered):
        return DocumentType.CONTRACT

    return DocumentType.UNKNOWN
