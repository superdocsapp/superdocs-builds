from __future__ import annotations
import uuid
from src.models import Paper, Section
from src.mcp_client import MCPClient


FIXED_SECTION_TITLES = [
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Results",
    "Discussion",
    "Conclusion",
    "References",
]


def generate_outline() -> list[str]:
    return list(FIXED_SECTION_TITLES)


def build_initial_html(section_titles: list[str]) -> str:
    """Builds the empty skeleton document as HTML. Each section gets a
    non-empty placeholder paragraph — a truly empty <p></p> gets silently
    stripped by SuperDocs' initial parse (confirmed via a real call:
    the heading survives, the empty paragraph vanishes), leaving no
    addressable chunk for edit_section to later target."""
    parts = []
    for title in section_titles:
        parts.append(f"<h2>{title}</h2>")
        parts.append(f"<p>[Placeholder: content for the {title} section will be added here.]</p>")
    return "".join(parts)


def create_paper_with_outline(topic: str, mcp_client: MCPClient) -> Paper:
    """Builds the Paper object and loads the empty skeleton into a new
    SuperDocs session in ONE call. document_id is not tracked — SuperDocs
    defaults every single-document session to its one focused document,
    confirmed via a real call (focused_document_id is always doc_primary)."""
    paper_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    section_titles = generate_outline()
    initial_html = build_initial_html(section_titles)
    mcp_client.create_session_with_document(session_id, initial_html)

    sections = [
        Section(id=str(uuid.uuid4()), paper_id=paper_id, title=title, order=order)
        for order, title in enumerate(section_titles, start=1)
    ]

    return Paper(id=paper_id, topic=topic, session_id=session_id, sections=sections)