"""Post-edit verification: recompute what the export must still prove.

Runs after every SuperDocs edit round. The checks mirror the never-do list:
no placeholder survives, no officer quote was altered, no request lost its
section, and the honest evidence-gap language was not drafted away.
"""
import re

from engine.model import ChecklistRow, Coverage, Request
from engine.response_skeleton import DRAFT_PLACEHOLDER_PREFIX
from engine.verify_citations import _normalize, contains_verbatim

RESPONSE_HEADING = re.compile(r"^#{1,6}\s+Response to Request\s+(\d+)\b")
SECTION_BOUNDARY = re.compile(r"^#{1,2}\s+")

# Each coverage bucket needs its own wording: a PARTIAL section says new
# evidence is needed and never says "not provided", so demanding that
# phrase everywhere would fail an honest document.
GAP_PHRASES = {
    Coverage.PARTIAL: ("attorney confirmation",),
    Coverage.NOT_PROVIDED: ("not provided", "attorney confirmation"),
}


def response_slices(export_text: str) -> dict[str, str]:
    """Split the export into one text slice per request's own section.

    The coverage table and the exhibit list spell out the gap phrases
    unconditionally; both stay outside every slice, so a section that lost
    its warning can no longer be covered by their wording.
    """
    slices: dict[str, str] = {}
    request_id = None
    body: list[str] = []
    for line in export_text.splitlines():
        heading = RESPONSE_HEADING.match(line)
        if heading:
            if request_id:
                slices[request_id] = "\n".join(body)
            request_id, body = f"R{heading.group(1)}", []
        elif request_id and SECTION_BOUNDARY.match(line):
            slices[request_id] = "\n".join(body)
            request_id, body = None, []
        elif request_id:
            body.append(line)
    if request_id:
        slices[request_id] = "\n".join(body)
    return slices


def verify_export(
    export_text: str,
    requests: list[Request],
    checklist: list[ChecklistRow],
) -> list[str]:
    failures = []
    normalized = _normalize(export_text)

    if DRAFT_PLACEHOLDER_PREFIX.lower() in normalized:
        failures.append(
            "a draft placeholder survived into the export — a section was "
            "never written; do not file this document"
        )

    slices = response_slices(export_text)

    for request in requests:
        if request.id not in slices:
            failures.append(
                f"{request.id}'s response section is missing from the export — "
                f"every request in the notice must keep its section"
            )
        if not contains_verbatim(request.text, slices.get(request.id, "")):
            failures.append(
                f"{request.id}'s officer quote was altered by editing — the "
                f"notice text is read-only input and must survive verbatim"
            )

    rows_by_id = {row.request_id: row for row in checklist}
    for request in requests:
        needed = GAP_PHRASES.get(rows_by_id[request.id].coverage)
        if not needed:
            continue
        section = _normalize(slices.get(request.id, ""))
        missing = [phrase for phrase in needed if phrase not in section]
        if missing:
            failures.append(
                f"{request.id}'s section lost its evidence-gap language "
                f"({', '.join(missing)}) — the checklist records a gap here, "
                f"so the section itself must say so; restore the warning "
                f"before filing"
            )
    return failures
