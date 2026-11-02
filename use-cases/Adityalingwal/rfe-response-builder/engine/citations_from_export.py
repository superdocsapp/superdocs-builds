"""Read the citations back out of the exported document.

The skeleton places every "Petition material relied on" quote in code, so
the export is the only place to check whether an edit round changed one.
This module recovers each quote with the file and section it names;
comparing the quotes against the real sources is `verify_citations`' job,
and checking that every source the checklist placed is still cited is
`missing_citation_failures`' job — an edit that deletes or mangles a
citation must be named, not slip out of the comparison.
"""
import re

from engine.model import Match, Request

TRUNCATION_MARKER = "[...]"
SECTION_HEADING = re.compile(r"^#{1,6}\s+(Response to Request\s+\d+.*)$")
CITATION_LINE = re.compile(r"^\s*[-*]\s+From\s+`([^`]+)`,\s+section\s+\"(.*)\":\s*$")


def _comparable(quote: str) -> str:
    """Undo what building the skeleton did to the source excerpt.

    Only the truncation marker is ours to remove: the skeleton cuts a long
    excerpt off with it, and the source never contained it. Everything
    else must survive untouched — the comparison is word-for-word, and a
    character the model slipped into a quote has to mismatch.
    """
    quote = quote.strip()
    if quote.startswith('"'):
        quote = quote[1:]
    if quote.endswith('"'):
        quote = quote[:-1]
    quote = quote.strip()
    if quote.endswith(TRUNCATION_MARKER):
        quote = quote[: -len(TRUNCATION_MARKER)].rstrip()
    return quote


def _quote_below(lines: list[str], start: int) -> str:
    # an edit round may rewrap a quote across lines; every line of it is
    # part of the citation, so all of them are gathered for comparison
    gathered: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            if gathered:
                break
            continue
        if line.lstrip().startswith("#") or CITATION_LINE.match(line):
            break
        gathered.append(line.strip())
    return _comparable(" ".join(gathered)) if gathered else ""


def cited_sections_from_export(export_text: str) -> list[dict]:
    """Pull every cited quote out of the export as
    [{"section", "file", "heading", "quote"}, ...] — the shape
    find_citation_failures and missing_citation_failures read."""
    lines = export_text.splitlines()
    cited = []
    section = ""
    for i, line in enumerate(lines):
        heading = SECTION_HEADING.match(line)
        if heading:
            section = heading.group(1).strip()
            continue
        citation = CITATION_LINE.match(line)
        if not citation:
            continue
        quote = _quote_below(lines, i + 1)
        if quote:
            cited.append(
                {
                    "section": section,
                    "file": citation.group(1),
                    "heading": citation.group(2),
                    "quote": quote,
                }
            )
    return cited


SECTION_NUMBER = re.compile(r"^response to request (\d+)\b", re.IGNORECASE)


def missing_citation_failures(
    cited_sections: list[dict],
    requests: list[Request],
    matches: dict[str, list[Match]],
) -> list[str]:
    """Name every petition source the skeleton cited that the export no
    longer cites. A deleted or unparsable citation never reaches
    `find_citation_failures`, and matching by (file, section) rather than
    by count also catches one citation replaced by a copy of another."""
    found: dict[str, set[tuple[str, str]]] = {}
    for cited in cited_sections:
        numbered = SECTION_NUMBER.match(cited["section"].strip())
        if numbered:
            request_id = f"R{numbered.group(1)}"
            found.setdefault(request_id, set()).add(
                (cited["file"], cited["heading"])
            )
    failures = []
    for request in requests:
        expected = {(m.file, m.heading) for m in matches.get(request.id, [])}
        for file, heading in sorted(expected - found.get(request.id, set())):
            failures.append(
                f"{request.id}'s section lost its citation to {file}, section "
                f"\"{heading}\" — a citation was removed or replaced during "
                f"editing"
            )
    return failures
