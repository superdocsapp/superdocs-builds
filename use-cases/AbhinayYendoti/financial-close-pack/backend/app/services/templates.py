"""Close templates.

A template defines what a close *requires*. Readiness is measured against this, rather
than against "whatever happened to be uploaded", which is what made the old
`docs_ready == len(documents)` check vacuous.
"""

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "standard-monthly-close": {
        "id": "standard-monthly-close",
        "name": "Standard Monthly Close",
        "required_document_types": [
            "Trial Balance",
            "Bank Reconciliation",
            "AR Memo",
            "Revenue",
            "Accruals",
            "AP Reconciliation",
            "Payroll",
            "Fixed Assets",
        ],
        "checklist": [
            {"title": "Trial balance reviewed", "document_type": "Trial Balance"},
            {"title": "Bank reconciliation complete", "document_type": "Bank Reconciliation"},
            {"title": "AR reconciliation complete", "document_type": "AR Memo"},
            {"title": "Revenue recognition", "document_type": "Revenue"},
            {"title": "Accrual review", "document_type": "Accruals"},
            {"title": "Payroll reconciliation", "document_type": "Payroll"},
            {"title": "Fixed asset roll-forward", "document_type": "Fixed Assets"},
        ],
        "signoffs": [
            {"role": "Prepared by"},
            {"role": "Reviewed by"},
            {"role": "Controller"},
        ],
    }
}

DEFAULT_TEMPLATE_ID = "standard-monthly-close"


def get_template(template_id: str) -> dict[str, Any]:
    if template_id not in TEMPLATES:
        raise KeyError(template_id)
    return TEMPLATES[template_id]


_STOPWORDS = {"pdf", "docx", "xlsx", "csv", "memo", "report", "final", "signed", "v1", "v2"}


def _stem(token: str) -> str:
    # Crude singular/plural folding so "Accrual Support.pdf" matches the "Accruals" type.
    return token[:-1] if len(token) > 4 and token.endswith("s") else token


def _tokens(value: str) -> set[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in value)
    return {_stem(token) for token in cleaned.split() if token and token not in _STOPWORDS}


def suggest_document_type(filename: str, required_types: list[str]) -> str | None:
    """Best-effort classification from the filename.

    Returns None when nothing matches, in which case the caller must supply a type
    explicitly. The old endpoint silently stamped every document "Supporting Memo".
    """
    name_tokens = _tokens(filename)
    if not name_tokens:
        return None

    best: tuple[int, str] | None = None
    for candidate in required_types:
        overlap = len(name_tokens & _tokens(candidate))
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, candidate)
    return best[1] if best else None
