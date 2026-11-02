"""Build the response document's skeleton in code.

Structure, quotes, citations, and the coverage table are deterministic:
the model only ever writes prose into the placeholder lines. Citations
start accurate because code places them from real excerpts — but an edit
round can still alter or remove one, which is why the export is verified
against the petition before anything is called filed-ready.
"""
import re

from engine.model import ChecklistRow, Coverage, Request

DRAFT_PLACEHOLDER_PREFIX = "[DRAFT RESPONSE FOR"
EXCERPT_LIMIT_CHARS = 700


def draft_placeholder(request_id: str) -> str:
    # unique per request, so an edit can be told to target exactly one
    # paragraph and a misdirected edit is visible by name
    return f"{DRAFT_PLACEHOLDER_PREFIX} {request_id} — TO BE WRITTEN]"

COVERAGE_LABEL = {
    Coverage.ANSWERED: "Answered",
    Coverage.PARTIAL: "Partially — new evidence needed",
    Coverage.NOT_PROVIDED: "Not provided — needs attorney confirmation",
}


def _trimmed(text: str) -> str:
    # petition excerpts only — the officer's request is never cut.
    # a blockquote marker at a line start is formatting; flattened
    # mid-sentence it would read as content the source never had, and the
    # citation check could then only pass it by ignoring ">" everywhere —
    # which would also hide a ">" the model slipped into a quote
    text = re.sub(r"^\s*(?:>\s?)+", "", text, flags=re.MULTILINE)
    flat = " ".join(text.split())
    if len(flat) <= EXCERPT_LIMIT_CHARS:
        return flat
    return flat[:EXCERPT_LIMIT_CHARS].rsplit(" ", 1)[0] + " [...]"


def build_skeleton(requests: list[Request], checklist: list[ChecklistRow]) -> str:
    rows_by_id = {row.request_id: row for row in checklist}
    lines = [
        "# Draft response to Request for Evidence (fictional sample)",
        "",
        "> FICTIONAL SAMPLE — created for the SuperDocs engineering task.",
        "> Attorney-support draft. Not legal advice. Every section requires",
        "> attorney review and approval before filing.",
        "",
        "## Coverage checklist",
        "",
        "| Request | Topic | Coverage |",
        "|---|---|---|",
    ]
    for request in requests:
        row = rows_by_id[request.id]
        lines.append(
            f"| {request.id} | {request.title} | {COVERAGE_LABEL[row.coverage]} |"
        )
    lines.append("")

    for request in requests:
        row = rows_by_id[request.id]
        lines.append(f"## Response to Request {request.id[1:]} — {request.title}")
        lines.append("")
        # the officer's own words go in whole: SuperDocs only ever sees the
        # skeleton, so a cut here is a cut in what the model drafts against.
        # They go in as a blockquote so a "## ..." line inside the notice
        # text cannot start a new section of our document
        lines.append("**Officer's request (quoted from the notice):**")
        lines.append("")
        lines.extend(f"> {line}" if line else ">" for line in request.text.splitlines())
        lines.append("")
        if row.matches:
            lines.append("**Petition material relied on:**")
            lines.append("")
            for match in row.matches:
                lines.append(f"- From `{match.file}`, section \"{match.heading}\":")
                lines.append(f"  \"{_trimmed(match.excerpt)}\"")
            lines.append("")
        if row.coverage == Coverage.PARTIAL:
            lines.append(
                "**Evidence gap:** the petition only touches this point in "
                "general terms. New evidence is needed — needs attorney "
                "confirmation."
            )
            lines.append("")
        if row.coverage == Coverage.NOT_PROVIDED:
            lines.append(
                "**Evidence gap:** the petition contains no material addressing "
                "this request. The required evidence is not provided — needs "
                "attorney confirmation before this section can be completed."
            )
            lines.append("")
        lines.append("**Response:**")
        lines.append("")
        lines.append(draft_placeholder(request.id))
        lines.append("")

    lines.append("## Exhibit set for this response")
    lines.append("")
    cited_files = []
    for request in requests:
        for match in rows_by_id[request.id].matches:
            if match.file not in cited_files:
                cited_files.append(match.file)
    for i, file in enumerate(cited_files, 1):
        lines.append(f"- Exhibit R-{i}: `{file}` (from the original petition)")
    lines.append(
        "- Further exhibits pending: new evidence for the requests marked "
        "'new evidence needed' or 'not provided', upon attorney confirmation."
    )
    lines.append("")
    return "\n".join(lines)
