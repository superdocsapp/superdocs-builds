"""Chat-driven drafting and amendment assistant for numbered, cross-referencing patent claims."""

from .core import (
    Claim,
    ClaimSet,
    ClaimValidationError,
    Patent,
    amend_claim,
    build_claim_set,
    claims_from_list,
    delete_claim,
    diff_claim_sets,
    extract_references,
    patent_from_payload,
)
from .exporters import export_bytes, patent_docx, patent_html, patent_pdf
from .mcp import handle_mcp
from .store import ClaimStore
from .workflow import ClaimManager, ExportBlocked

__all__ = [
    "Claim",
    "ClaimManager",
    "ClaimSet",
    "ClaimStore",
    "ClaimValidationError",
    "ExportBlocked",
    "Patent",
    "amend_claim",
    "build_claim_set",
    "claims_from_list",
    "delete_claim",
    "diff_claim_sets",
    "export_bytes",
    "extract_references",
    "handle_mcp",
    "patent_docx",
    "patent_from_payload",
    "patent_html",
    "patent_pdf",
]
