from __future__ import annotations
from src.models import Paper, SectionStatus, PaperStatus
from src.mcp_client import MCPClient


def export_paper(paper: Paper, mcp_client: MCPClient, format: str = "docx") -> str:
    """Gate: refuses to export until every section is VERIFIED.
    This is what makes 'submission-ready' actually mean something —
    a paper with an unresolved flagged section should never reach export.
    Note: export_document is keyed on session_id, not document_id — the
    real tool exports the SESSION's current document state."""
    unverified = [s.title for s in paper.sections if s.status != SectionStatus.VERIFIED]
    if unverified:
        raise ValueError(
            f"Cannot export: the following sections are not verified: {unverified}"
        )

    export_path = mcp_client.export_document(session_id=paper.session_id, format=format)

    paper.status = PaperStatus.EXPORTED
    return export_path