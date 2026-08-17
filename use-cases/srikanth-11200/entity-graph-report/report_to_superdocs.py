"""
Pure, network-free, database-free transformation from an already-approved
report's sections into the data SuperDocs needs - an outline document and
one evidence-grounded edit instruction per approved section.

Adapted from the private DocTask (Task 1) repository's
app/integrations/report_to_superdocs.py for this standalone, public
Task 2 package. The private version's `load_approved_sections` (the one
method that queried DocTask's own ReportSection/ReviewItem SQLAlchemy
models) has been removed entirely - this module now operates purely on
already-loaded `ApprovedSection` values, exactly as the private module's
own pure functions already did. In this package, those values come from
fixtures/approved_sections.json (a real, already-approved snapshot
generated from DocTask - see demo.py), not a live database query.

Everything in this module is pure data transformation: given
`ApprovedSection` values, produce strings. No database access, no network
call, no LLM call, no additional reasoning or extraction.

insufficient_evidence sections are never turned into an edit instruction:
build_section_instruction returns None for them (and for any section with
an empty/whitespace body), so no fabricated claim can ever reach
SuperDocs. build_instructions_for_report silently excludes such sections
from its output rather than raising - an empty result is the honest
"nothing to send" outcome the caller (demo.py) is expected to check for
before ever calling SuperDocs.
"""

from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

# Same escaping precedent as the private repo's diagram_service.py's
# _escape_svg_text: the stdlib default only covers & < >, extended here
# to quotes too, since section titles are ultimately LLM-extracted,
# untrusted document content being interpolated into HTML sent to a
# third-party API.
_HTML_EXTRA_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def _escape_html(value: str) -> str:
    return _xml_escape(value, _HTML_EXTRA_ENTITIES)


@dataclass(frozen=True)
class ApprovedSection:
    """
    One approved report section's data. citations is the list[dict]
    already produced by DocTask (evidence_chunk_id/evidence_text/
    document_id/filename/chunk_index/entity_id/relationship_id), passed
    through unchanged - see fixtures/approved_sections.json.
    """

    section_index: int
    title: str
    body: str | None
    citations: list[dict[str, Any]]
    insufficient_evidence: bool


@dataclass(frozen=True)
class SectionInstruction:
    """One section's SuperDocs chat/edit instruction, ready to send."""

    section_index: int
    title: str
    instruction: str


class ReportToSuperDocs:
    """Pure transformation entry point - no database, no network, no reasoning."""

    @staticmethod
    def build_outline_html(
        sections: list[ApprovedSection],
        diagram_image_url: str | None = None,
    ) -> str:
        """
        One heading per approved section, in section_index order, each
        followed by an empty paragraph for SuperDocs' chat to write into
        - gives SuperDocs real section anchors to edit, rather than
        uploading a single opaque final document. A report with no
        sections still produces a minimal, valid outline document (never
        an empty upload payload).

        diagram_image_url (Task 2's "images" surface): when given, an
        embedded `<img>` block referencing the real relationship diagram
        is appended at the end of the outline, pointing at a stable
        public URL SuperDocs itself hosts (from
        SuperDocsClient.upload_image) - never an inline/data-URI image
        and never a fabricated URL. Omitted (None) when no diagram image
        was uploaded - the outline stays valid and complete either way,
        this is purely additive.
        """

        if not sections:
            body = "<h1>Report</h1><p></p>"
        else:
            ordered = sorted(sections, key=lambda s: s.section_index)
            body = "".join(
                f"<h1>{_escape_html(section.title)}</h1><p></p>" for section in ordered
            )

        if diagram_image_url:
            body += (
                "<h1>Relationship Diagram</h1>"
                f'<img src="{_escape_html(diagram_image_url)}" '
                'alt="Entity relationship diagram" />'
            )

        return body

    @staticmethod
    def resolve_uploaded_image_url(upload_response: dict[str, Any]) -> str | None:
        """
        Pure lookup over SuperDocsClient.upload_image's raw response dict.
        The exact response field name holding the hosted image URL was
        not independently confirmed (see upload_image's own docstring) -
        this checks every plausible field name in order rather than
        assuming one, and returns None (never a guessed/fabricated URL)
        if none of them are present, so a caller can honestly skip
        embedding the image rather than emit a broken <img> tag.
        """

        for key in ("url", "image_url", "public_url", "src", "asset_url"):
            value = upload_response.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def build_section_instruction(section: ApprovedSection) -> str | None:
        """
        Returns None - never a fabricated instruction - for a section
        with no writable claim: insufficient_evidence sections and any
        section whose body is empty/whitespace-only.

        Otherwise returns one natural-language edit instruction combining
        the section's already-written, evidence-backed body with its
        citations: "In the section titled '<title>', write a paragraph
        stating <claim>, grounded in <citation>." Pure string formatting
        only.
        """

        if section.insufficient_evidence:
            return None
        if not section.body or not section.body.strip():
            return None

        if section.citations:
            citation_lines = "\n".join(
                f"- {citation.get('filename', 'unknown source')} "
                f"(chunk {citation.get('chunk_index', '?')}): "
                f"\"{citation.get('evidence_text', '')}\""
                for citation in section.citations
            )
        else:
            citation_lines = "(no cited source passages)"

        return (
            f'In the section titled "{section.title}", write a paragraph '
            f"stating the following, grounded in the source evidence "
            f"listed below. Do not add any fact that is not present in "
            f"this evidence.\n\n"
            f"STATEMENT TO WRITE:\n{section.body}\n\n"
            f"SOURCE EVIDENCE:\n{citation_lines}"
        )

    @staticmethod
    def build_instructions_for_report(
        sections: list[ApprovedSection],
    ) -> list[SectionInstruction]:
        """
        One SectionInstruction per approved section that actually has a
        writable claim, in section_index order. Sections excluded by
        build_section_instruction (insufficient evidence / empty body)
        are silently absent from the result, not represented as an error
        or a placeholder entry.

        An empty result means "nothing to send" - callers (demo.py) must
        treat that as the honest zero-approved-writable-sections outcome
        and skip calling SuperDocs entirely, spending no SuperDocs
        operation when there is nothing evidence-backed to push.
        """

        ordered = sorted(sections, key=lambda s: s.section_index)
        instructions: list[SectionInstruction] = []

        for section in ordered:
            instruction_text = ReportToSuperDocs.build_section_instruction(section)
            if instruction_text is not None:
                instructions.append(
                    SectionInstruction(
                        section_index=section.section_index,
                        title=section.title,
                        instruction=instruction_text,
                    )
                )

        return instructions
