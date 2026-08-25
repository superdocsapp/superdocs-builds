"""Close readiness and the close gate.

Fixes from the audit:
  * every ratio is guarded, so a close with an empty section no longer raises
    ZeroDivisionError and 500s the endpoint;
  * documents are measured against the template's *required* types rather than
    against the list of whatever was uploaded, which could never fail;
  * a close with nothing generated yet is not "ready" by virtue of having no reviews.
"""

from typing import Any


def _ratio(numerator: int, denominator: int) -> float:
    """0 of 0 counts as satisfied; it is a requirement that does not apply."""
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def calculate_readiness(close: dict[str, Any]) -> dict[str, Any]:
    documents = close.get("documents") or []
    checklist = close.get("checklist") or []
    reviews = close.get("reviews") or []
    signoffs = close.get("signoffs") or []
    required_types: list[str] = close.get("required_document_types") or []

    ready_types = {
        document.get("document_type")
        for document in documents
        if document.get("status") == "READY" and document.get("document_type")
    }
    documents_present = sum(1 for required in required_types if required in ready_types)
    missing_types = [required for required in required_types if required not in ready_types]
    unmapped = [document for document in documents if document.get("status") != "READY"]

    checklist_complete = sum(1 for item in checklist if item.get("status") == "COMPLETE")
    reviews_resolved = sum(1 for item in reviews if item.get("status") in {"APPROVED", "REJECTED"})
    signoffs_approved = sum(1 for item in signoffs if item.get("status") == "APPROVED")
    exported = bool(close.get("exported"))
    generated = bool(close.get("superdocs_document_ids"))

    blockers: list[str] = []
    if missing_types:
        count = len(missing_types)
        blockers.append(f"{count} required {_plural(count, 'document', 'documents')} needs attention")
    if unmapped:
        count = len(unmapped)
        blockers.append(f"{count} uploaded {_plural(count, 'document', 'documents')} awaiting classification")
    if checklist_complete < len(checklist):
        count = len(checklist) - checklist_complete
        blockers.append(f"{count} checklist {_plural(count, 'item', 'items')} pending")
    if not generated:
        blockers.append("Close pack not generated yet")
    if reviews_resolved < len(reviews):
        count = len(reviews) - reviews_resolved
        blockers.append(f"{count} review {_plural(count, 'decision', 'decisions')} pending")
    if signoffs_approved < len(signoffs):
        count = len(signoffs) - signoffs_approved
        blockers.append(f"{count} {_plural(count, 'sign-off', 'sign-offs')} pending")
    if not exported:
        blockers.append("Final pack export pending")

    readiness = round(
        (
            _ratio(documents_present, len(required_types))
            + _ratio(checklist_complete, len(checklist))
            + (1.0 if generated else 0.0)
            + _ratio(reviews_resolved, len(reviews))
            + _ratio(signoffs_approved, len(signoffs))
            + (1.0 if exported else 0.0)
        )
        / 6
        * 100
    )

    return {
        "ready_for_generation": not missing_types and not unmapped and checklist_complete == len(checklist),
        "ready_for_close": not blockers,
        "readiness": readiness,
        "documents": {
            "required": len(required_types),
            "present": documents_present,
            "missing_types": missing_types,
            "unclassified": len(unmapped),
        },
        "checklist": {"required": len(checklist), "complete": checklist_complete},
        "generation": {"generated": generated},
        "reviews": {"total": len(reviews), "resolved": reviews_resolved},
        "signoffs": {"required": len(signoffs), "approved": signoffs_approved},
        "export": {"exported": exported},
        "blockers": blockers,
    }
