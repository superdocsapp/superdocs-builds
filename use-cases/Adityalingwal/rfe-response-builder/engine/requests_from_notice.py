import re

from engine.model import Request

# Style A: "### 1. Title" headings under an "## Evidence requested" section
REQUEST_HEADING = re.compile(r"^### (\d+)\.\s*(.+?)\s*$", re.MULTILINE)
EVIDENCE_SECTION = re.compile(r"^## Evidence requested\s*$", re.MULTILINE)
NEXT_TOP_SECTION = re.compile(r"^## ", re.MULTILINE)

# Style B: lines starting "1. ..." / "1) ...", possibly bold ("**1. ...**")
NUMBERED_ITEM = re.compile(r"^\*{0,2}(\d+)[.)]\s+", re.MULTILINE)
# Style C: lines starting "Request 1: ..."
LABELLED_ITEM = re.compile(r"^Request\s+(\d+)\s*:\s*", re.MULTILINE | re.IGNORECASE)
# Style D: headings like "## ITEM 3 — Title", with or without hash marks —
# a PDF's text layer keeps no markdown, its headings are just lines
ITEM_HEADING = re.compile(
    r"^#{0,4}\s*ITEM\s+(\d+)\s*[—–\-:.]*\s*(.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# "REQUEST 3 — TITLE" is a heading; the dash separates it from the inline
# "Request 3: content..." style, which carries its content on the same line
REQUEST_DASH_HEADING = re.compile(
    r"^#{0,4}\s*REQUEST\s+(\d+)\s*[—–-]\s*(.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Style E: headings like "## 3. Title"
NUMBERED_HEADING = re.compile(r"^#{1,4}\s*(\d+)[.)]\s+(.+?)\s*$", re.MULTILINE)
# A section boundary is a markdown heading or an all-caps line (how PDF
# section headers usually read)
ANY_HEADING = re.compile(
    r"^(?:#{1,3}\s|[A-Z][A-Z0-9 ,.'()\-—–:;/&]{4,}$)", re.MULTILINE
)
CAPS_LINE = re.compile(r"^[A-Z][A-Z0-9 ,.'()\-—–:;/&]{4,}\s*$")

TITLE_WORD_LIMIT = 8
MIN_REQUESTS = 2  # one lone numbered line is a date or an address, not a request list

# an attorney reads this, not a developer: it shows the layouts side by side
# instead of describing them in a sentence
UNRECOGNIZED_LAYOUT = """\
Could not find the officer's requests in {source_name}.

The tool looks for requests written in one of these ways:

    numbered list:       1.  Evidence that ...
    numbered headings:   ITEM 1 — Evidence that ...
                         REQUEST 1 — Evidence that ...
                         Request 1: Evidence that ...
                         ## 1. Evidence that ...
                         ### 1. Evidence that ...

What to do: open the notice and check that each request starts
with its number. If the notice uses bullets or another layout,
save a copy with the requests numbered 1, 2, 3 and run again."""


def _title_from(text: str) -> str:
    words = text.split()
    title = " ".join(words[:TITLE_WORD_LIMIT])
    return title + ("…" if len(words) > TITLE_WORD_LIMIT else "")


def _parse_heading_style(notice_text: str) -> list[Request] | None:
    section_start = EVIDENCE_SECTION.search(notice_text)
    if section_start is None:
        return None
    rest = notice_text[section_start.end():]
    next_section = NEXT_TOP_SECTION.search(rest)
    evidence_block = rest[: next_section.start()] if next_section else rest
    headings = list(REQUEST_HEADING.finditer(evidence_block))
    if not headings:
        # the section exists but its items use another style — let the
        # other parsers try before anything is refused
        return None
    requests = []
    for i, m in enumerate(headings):
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(evidence_block)
        body = evidence_block[m.end():body_end].strip()
        requests.append(Request(id=f"R{m.group(1)}", title=m.group(2), text=body))
    return requests


def _parse_heading_items(notice_text: str, pattern: re.Pattern) -> list[Request] | None:
    # A request heading's body runs to the next request heading. The last one
    # has no such bound, so it stops at the next heading of any kind — that is
    # the only place a closing "How to respond" section could be swallowed.
    anchors = list(pattern.finditer(notice_text))
    if len(anchors) < MIN_REQUESTS:
        return None
    requests = []
    for i, m in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(notice_text)
        body_start = m.end()
        # a long heading printed to paper wraps onto further capitalized
        # lines; those continue the title and must not read as the next
        # section's boundary
        title_extra = []
        while True:
            line_break = notice_text.find("\n", body_start, end)
            if line_break == -1:
                break
            line_end = notice_text.find("\n", line_break + 1, end)
            line = notice_text[line_break + 1: line_end if line_end != -1 else end]
            if CAPS_LINE.match(line):
                title_extra.append(line.strip())
                body_start = line_break + 1 + len(line)
            else:
                break
        if i + 1 == len(anchors):
            next_heading = ANY_HEADING.search(notice_text, body_start, end)
            if next_heading:
                end = next_heading.start()
        body = notice_text[body_start:end].strip()
        title = " ".join([m.group(2).strip(), *title_extra]).strip() or _title_from(body)
        requests.append(Request(id=f"R{m.group(1)}", title=title, text=body))
    return requests


def _parse_item_style(notice_text: str, pattern: re.Pattern) -> list[Request] | None:
    # Anchoring on line starts, not blank lines: PDF extraction often loses
    # paragraph gaps, and a numbered item must still be found. An item runs
    # to the next item, or to the next blank line for the last one, so a
    # closing boilerplate paragraph does not glue itself onto the final
    # request.
    anchors = list(pattern.finditer(notice_text))
    if len(anchors) < MIN_REQUESTS:
        return None
    requests = []
    for i, m in enumerate(anchors):
        if i + 1 < len(anchors):
            body = notice_text[m.end():anchors[i + 1].start()]
        else:
            # the last item ends at the next section heading when one
            # exists (a closing "how to respond" block must not be
            # swallowed); with no heading, at the next blank line
            rest = notice_text[m.end():]
            boundary = ANY_HEADING.search(rest)
            if boundary is None:
                boundary = re.search(r"\n\s*\n", rest)
            body = rest[: boundary.start()] if boundary else rest
        body = body.strip()
        requests.append(
            Request(
                id=f"R{m.group(1)}",
                title=_title_from(body).replace("**", ""),
                text=body,
            )
        )
    return requests


def parse_notice(notice_text: str, source_name: str = "the notice") -> list[Request]:
    """Split the officer's notice into its individual numbered requests.

    The granularity comes from the notice itself — one request per numbered
    item, in whichever supported style the notice uses. Nothing is merged,
    nothing is invented; a layout outside the supported styles is refused
    with the file's name and the layouts that would work, never guessed at.
    """
    # Heading styles first: a notice with request headings often ALSO has a
    # numbered "how to respond" list, and the line-item fallback would
    # otherwise mistake those instructions for the requests themselves.
    requests = _parse_heading_style(notice_text)
    if requests is None:
        requests = _parse_heading_items(notice_text, ITEM_HEADING)
    if requests is None:
        requests = _parse_heading_items(notice_text, REQUEST_DASH_HEADING)
    if requests is None:
        requests = _parse_heading_items(notice_text, NUMBERED_HEADING)
    if requests is None:
        requests = _parse_item_style(notice_text, LABELLED_ITEM)
    if requests is None:
        requests = _parse_item_style(notice_text, NUMBERED_ITEM)
    if requests is None:
        raise ValueError(UNRECOGNIZED_LAYOUT.format(source_name=source_name))
    # a notice that restarts its numbering per group prints "1." twice, and two
    # requests sharing an id would make retrieve() overwrite one with the other
    return [
        Request(id=f"R{n}", title=request.title, text=request.text)
        for n, request in enumerate(requests, start=1)
    ]
