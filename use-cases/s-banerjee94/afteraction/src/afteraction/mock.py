"""An offline stand-in for SuperDocs.

Everything except the four API calls runs against this: parsing, facts, the curve, the
gate, the traceability pass and the carry-forward. That is what lets a stranger clone
the repository and run the whole pipeline, tests included, with no key and no network —
and it is what kept the operation budget for work rather than for debugging.

The mock is deliberately *not* a rubber stamp. It drafts prose the way a well-behaved
model would — stitching the supplied statements together and preserving their citations
— and it can be told to misbehave in the specific ways that matter:

    MockSuperDocs(misbehave="phantom")   invents a citation to an entry that does not exist
    MockSuperDocs(misbehave="foreign")   cites a real entry this section was never given
    MockSuperDocs(misbehave="unsourced") drops citations entirely

Those modes exist so the traceability pass can be proven to catch each failure, rather
than being tested only against a mock that always behaves. A test that only proves the
mock works is worth nothing.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Callable

from .client import Approver, ProposedChange, Usage, approve_all
from .sections import SUMMARY_PLACEHOLDER

BULLET = re.compile(r"^-\s+(.*)$")
SECTION_NAME = re.compile(r"section\s+[“\"]([^”\"]+)[”\"]")
IMG_TAG = re.compile(r"<img[^>]+>")
# The instruction hands over the caption already marked up, so it is lifted rather than
# extracted from prose. An earlier version matched a quoted run of text, which also
# matched the `"` closing alt="..." and swallowed the instruction into the document.
CAPTION = re.compile(r"<p><em>(.*?)</em></p>", re.S)
# One time window in a timeline instruction: "WINDOW 3 - 24 April, 20:00-22:00",
# followed by its records indented two spaces as "  TEL-0006  note text".
WINDOW = re.compile(r"^WINDOW\s+\d+\s+\S\s+(?P<label>.+)$", re.M)
RECORD = re.compile(r"^  (?P<rid>(?:WEA|TEL|DMG|CRW|COM|FLD)-\d{4})  (?P<note>.+)$")


class MockSuperDocs:
    """Same surface as SuperDocsClient, no network."""

    def __init__(
        self,
        misbehave: str | None = None,
        reject_first: bool = False,
        stall: str | None = None,
        sleep: Callable[[float], None] = lambda _: None,
    ) -> None:
        self.documents: dict[str, str] = {}
        self.images: list[str] = []
        self.instructions: list[str] = []
        self.misbehave = misbehave
        self.reject_first = reject_first
        # `stall` names a section whose first edit reports success and changes nothing —
        # the live failure that left a section holding its placeholder while the run
        # reported clean. The second attempt lands, so a retry can be shown to fix it.
        self.stall = stall
        self.stalled: set[str] = set()
        self.rejections: list[str] = []
        self.usage = Usage(operations_before=0, operations_after=0)
        self._sleep = sleep
        self._rejected_once = False

    # ------------------------------------------------------------------ contract

    def close(self) -> None:  # parity with the real client
        pass

    def __enter__(self) -> MockSuperDocs:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def whoami(self) -> dict[str, Any]:
        return {"tier": "mock", "quota": {"used": self.usage.operations_after, "monthly_limit": 0}}

    def operations_used(self) -> int:
        return self.usage.operations_after or 0

    def upload_document(self, session_id: str, filename: str, content: str) -> dict[str, Any]:
        self.documents[session_id] = content
        self.usage.calls += 1
        return {"filename": filename, "chunks_count": content.count("<"), "session_id": session_id}

    def upload_image(self, session_id: str, filename: str, image: Path | bytes) -> str:
        """Return a data URI carrying the real image bytes.

        The live endpoint returns a hosted URL. A mock that invented a fake one would
        put an `<img>` in the document pointing at nothing, so the offline export would
        show an empty box — and "the diagram is inside the document" is precisely what
        this build has to demonstrate. Embedding the actual bytes makes the offline
        document show the real curve.
        """
        self.usage.calls += 1
        raw = image.read_bytes() if isinstance(image, Path) else image
        url = f"data:image/png;base64,{base64.b64encode(raw).decode('ascii')}"
        self.images.append(url)
        return url

    def chat(
        self,
        session_id: str,
        message: str,
        approver: Approver = approve_all,
        model_tier: str = "core",
        on_event: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        note = on_event or (lambda stage, detail: None)
        self.instructions.append(message)
        self.usage.calls += 1
        self.usage.operations_after = (self.usage.operations_after or 0) + 1

        changes = self._propose(message)
        approved: list[ProposedChange] = []
        for change in changes:
            ok, why = approver(change)
            if not ok and why:
                self.rejections.append(why)
            if ok:
                approved.append(change)
        note("gate", f"{len(approved)} approved, {len(changes) - len(approved)} rejected")

        html = self.documents.get(session_id, "")
        for change in approved:
            section = change.chunk_id.partition("|")[0]
            if self.stall and section == self.stall and section not in self.stalled:
                # reported as applied, changed nothing — exactly how the live failure looked
                self.stalled.add(section)
                continue
            html = _apply(html, change)
        self.documents[session_id] = html

        return {
            "response": f"Updated {len(approved)} of {len(changes)} proposed changes.",
            "document_changes": {"updated_html": html},
        }

    def export(self, session_id: str, out_path: Path, fmt: str = "docx") -> Path:
        """Write the document out.

        The live service renders real Open XML. This mock cannot, and writing HTML into
        a file named `.docx` would be a small lie that Word would expose the moment
        anyone opened it — so the offline export is named `.html` and is genuinely
        viewable, curve included.
        """
        html = self.documents.get(session_id, "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if fmt in ("markdown", "md", "txt"):
            out_path.write_text(html_to_markdown(html), encoding="utf-8")
            return out_path
        page = out_path.with_suffix(".html")
        page.write_text(_standalone(html), encoding="utf-8")
        return page

    # -------------------------------------------------------------------- drafting

    def _propose(self, message: str) -> list[ProposedChange]:
        """Turn one instruction into the changes a cooperative model would propose."""
        image = IMG_TAG.search(message)
        if image:
            # look for the caption only after the tag, never inside its attributes
            caption = CAPTION.search(message, image.end())
            body = image.group(0) + (f"<p><em>{caption.group(1)}</em></p>" if caption else "")
            named = SECTION_NAME.search(message)
            section = named.group(1) if named else ""
            # Two charts now, two placeholders. Picking by section name rather than
            # assuming the curve keeps the contacts chart from overwriting it.
            which = "contacts" if "Consumer Contacts" in section else "curve"
            target = {
                "curve": "Placeholder for the restoration curve.",
                "contacts": "Placeholder for the consumer contacts chart.",
            }[which]
            return [
                ProposedChange(
                    change_id=f"mock-{which}",
                    operation="edit",
                    chunk_id=f"{section}|{which}",
                    old_html=target,
                    new_html=body,
                    explanation=f"Inserted the {which} chart and its caption.",
                )
            ]

        if SUMMARY_PLACEHOLDER in message:
            return [self._summary(message)]

        if WINDOW.search(message):
            return self._timeline(message)

        named = SECTION_NAME.search(message)
        section = named.group(1) if named else ""

        buckets = _buckets(message)
        # The skeleton's placeholders name their own section, so each is unique in the
        # document and an edit has exactly one place it can land.
        placeholders = {
            "observed": f"Placeholder for observed statements in {section}.",
            "assessed": f"Placeholder for assessed statements in {section}.",
            "gaps": f"Placeholder for gaps in {section}.",
            "raised": "Placeholder for items raised by this event.",
        }

        shapes = _shapes(message)

        changes: list[ProposedChange] = []
        for n, (bucket, statements) in enumerate(buckets.items(), start=1):
            if not statements:
                continue
            written = [self._sentence(s, bucket) for s in statements]
            if shapes.get(bucket) == "list":
                body = "<ul>" + "".join(f"<li>{s}</li>" for s in written) + "</ul>"
            else:
                body = f"<p>{' '.join(written)}</p>"
            changes.append(
                ProposedChange(
                    change_id=f"mock-{bucket}-{n}",
                    operation="edit",
                    chunk_id=f"{section}|{bucket}-{n}",
                    old_html=placeholders[bucket],
                    new_html=body,
                    explanation=f"Drafted {len(statements)} {bucket} statement(s).",
                )
            )
        return changes

    def _timeline(self, message: str) -> list[ProposedChange]:
        """One bullet per time window, the way a cooperative model would write them.

        The instruction hands over every record in every window and asks for two
        sentences and all the citations. The mock does exactly that — it compresses by
        taking the window's first two notes — so the offline document has the same shape
        as the live one and the traceability pass reads the same citations on both paths.

        Gaps travel with the timeline instruction but land under a different sub-heading,
        so they are a second change against a second placeholder rather than more list
        items appended to the first.
        """
        named = SECTION_NAME.search(message)
        section = named.group(1) if named else ""

        bullets: list[str] = []
        for label, records in _windows(message):
            # "AT MOST TWO SENTENCES" is a rule the instruction states, so the mock obeys
            # it — one sentence from each of the first two records, not both records
            # whole. A mock that ignored the limit would write four sentences behind one
            # trailing citation, and the traceability pass would correctly report the
            # first two as unsourced. That is the check working, not a false alarm.
            notes = [_first_sentence(note) for _, note in records][:2]
            ids = ", ".join(rid for rid, _ in records)
            bullets.append(f"<li><strong>{label}</strong> — {' '.join(notes)} [{ids}]</li>")

        changes = [
            ProposedChange(
                change_id="mock-timeline",
                operation="edit",
                chunk_id=f"{section}|observed",
                old_html=f"Placeholder for observed statements in {section}.",
                new_html="<ul>" + "".join(bullets) + "</ul>",
                explanation=f"Drafted {len(bullets)} timeline windows.",
            )
        ]

        gaps = _buckets(message)["gaps"]
        if gaps:
            written = [self._sentence(g, "gaps") for g in gaps]
            changes.append(
                ProposedChange(
                    change_id="mock-timeline-gaps",
                    operation="edit",
                    chunk_id=f"{section}|gaps",
                    old_html=f"Placeholder for gaps in {section}.",
                    new_html=f"<p>{' '.join(written)}</p>",
                    explanation=f"Drafted {len(gaps)} declared gap(s).",
                )
            )
        return changes

    def _summary(self, message: str) -> ProposedChange:
        """The executive summary, written from the document rather than from facts.

        A mock cannot summarise a document it only pretends to hold, so it writes the
        one honest thing it can: a short paragraph naming the event. What matters for the
        offline path is that the placeholder is replaced and no citation is invented —
        the summary is the one part of the report that deliberately carries none.
        """
        named = re.search(r"The event is [“\"]([^”\"]+)[”\"]", message)
        event = named.group(1) if named else "the event"
        body = (
            f"<p>This report covers {event} and the restoration that followed it. "
            "It sets out what the records show, what the response team concluded, and "
            "where the records do not answer the question.</p>"
        )
        return ProposedChange(
            change_id="mock-summary",
            operation="edit",
            chunk_id="Executive Summary|summary",
            old_html=SUMMARY_PLACEHOLDER,
            new_html=body,
            explanation="Drafted the executive summary.",
        )

    def _sentence(self, statement: str, bucket: str) -> str:
        """One drafted sentence, with the citation kept where the instruction put it."""
        text = statement.strip()
        if bucket == "observed" and self.misbehave:
            if self.misbehave == "phantom":
                text = re.sub(r"\[(?:WEA|TEL|DMG|CRW|COM|FLD)-\d{4}[^\]]*\]", "[TEL-9999]", text, count=1)
            elif self.misbehave == "foreign":
                text = re.sub(r"\[(?:WEA|TEL|DMG|CRW|COM|FLD)-\d{4}[^\]]*\]", "[FLD-0001]", text, count=1)
            elif self.misbehave == "unsourced":
                text = re.sub(r"\s*\[(?:WEA|TEL|DMG|CRW|COM|FLD)-\d{4}[^\]]*\]", "", text)
        if not text.endswith((".", "!", "?")):
            text += "."
        return text[0].upper() + text[1:]


def _apply(html: str, change: ProposedChange) -> str:
    """Replace the placeholder paragraph the change targets, keeping how it is styled.

    Two things this has to get right, both learned from defects.

    The live service edits chunks, so a paragraph's own formatting survives the edit and
    the drafted prose inherits it. Matching a literal `<p>...</p>` string would not: it
    would miss any styled paragraph and silently leave the placeholder in place. So the
    placeholder is found by its text and the opening tag it was wearing is reused.

    And every section carries the *same* placeholder wording, so a document-wide "replace
    the first match" writes each section's prose into whichever section is still empty
    highest up the page. One rejected change was enough to shift every later section by
    one and leave the last one blank. The live service has chunk ids and no such problem;
    here the edit is scoped to the section the instruction named.
    """
    target = (change.old_html or "").strip()
    if not target:
        return html
    section, _, _bucket = change.chunk_id.partition("|")
    start, end = _section_bounds(html, section)
    head, body, tail = html[:start], html[start:end], html[end:]

    # A placeholder may live in a paragraph or, for the executive summary, in a shaded
    # table cell. Either keeps its own tag and styling through the edit, the same way the
    # live service edits a chunk without restyling it.
    para = re.compile(r"<(p|td)\b([^>]*)>\s*" + re.escape(target) + r"\s*</\1>")

    def swap(match: re.Match[str]) -> str:
        tag, attrs = match.group(1), match.group(2)
        new = change.new_html or ""
        inner = re.fullmatch(r"<p\b[^>]*>(.*)</p>", new, re.S)
        # prose keeps its own tag; a block replacement, such as a chart, takes over
        return f"<{tag}{attrs}>{inner.group(1)}</{tag}>" if inner else new

    return head + para.sub(swap, body, count=1) + tail


def _section_bounds(html: str, title: str) -> tuple[int, int]:
    """Where one section starts and ends, by its `<h2>` heading. Whole document if unnamed."""
    if not title:
        return 0, len(html)
    opening = re.search(r"<h2\b[^>]*>[^<]*" + re.escape(title) + r"[^<]*</h2>", html)
    if not opening:
        return 0, len(html)
    following = re.search(r"<h2\b", html[opening.end() :])
    return opening.end(), (opening.end() + following.start() if following else len(html))


# The line that opens each bucket in an instruction, upper-cased for matching. One
# definition, so the splitter and the shape detector below cannot drift apart.
# Deliberately *not* the words used as headings in the document. When the label and the
# heading were the same string — "WHAT THE RECORDS DO NOT SHOW" was the heading, verbatim —
# the model copied the label into the document underneath the heading it already had. A
# label that shares no wording with a heading gives it nothing to copy.
_HEADERS = {
    "observed": "STATEMENTS WITH A RECORD",
    "assessed": "TEAM JUDGEMENTS",
    "gaps": "DECLARED GAPS",
    "raised": "NEW ITEMS FROM",
}


def _shapes(message: str) -> dict[str, str]:
    """What shape the instruction asked each bucket to take: a list, or prose.

    The live service is an AI editor and is told the form each section should take, not
    only its content. A mock that always produced one paragraph would hide the
    difference, and a timeline of eighteen entries reads very differently as a table than
    as a single paragraph. So the mock obeys the same directive it sends.
    """
    shapes: dict[str, str] = {}
    for bucket, header in _HEADERS.items():
        for line in message.splitlines():
            if not line.strip().upper().startswith(header):
                continue
            low = line.lower()
            shapes[bucket] = "list" if "bulleted list" in low else "prose"
    return shapes



def _first_sentence(note: str) -> str:
    """The first sentence of a record's note, ending in a full stop."""
    head = re.split(r"(?<=[.!?])\s+", note.strip(), maxsplit=1)[0].strip()
    return head if head.endswith((".", "!", "?")) else head + "."


def _windows(message: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Read the time windows back out of a timeline instruction.

    Returns `[(label, [(record_id, note), ...]), ...]` in the order the instruction
    listed them. Parsing the instruction rather than reaching into `FactSet` keeps the
    mock honest: it sees exactly what the live service sees, and nothing else.
    """
    found: list[tuple[str, list[tuple[str, str]]]] = []
    for line in message.splitlines():
        header = WINDOW.match(line)
        if header:
            found.append((header.group("label").strip(), []))
            continue
        record = RECORD.match(line)
        if record and found:
            found[-1][1].append((record.group("rid"), record.group("note").strip()))
    return [(label, records) for label, records in found if records]


def _buckets(message: str) -> dict[str, list[str]]:
    """Split an instruction's bullets by the heading they were listed under."""
    buckets: dict[str, list[str]] = {"observed": [], "assessed": [], "gaps": [], "raised": []}
    current = "observed"
    for line in message.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        opened = next((b for b, h in _HEADERS.items() if upper.startswith(h)), None)
        if opened:
            current = opened
        elif match := BULLET.match(stripped):
            value = match.group(1).strip()
            if value and value != "(none)":
                buckets[current].append(value)
    return buckets


def _standalone(body: str) -> str:
    """Wrap the document body in page chrome so it reads like a filed report in a browser.

    Chrome only. The document carries its own styling inline, from `templates/report.html`,
    and the live HTML export ships that styling with it — so a stylesheet here would be a
    second opinion about the design, overriding whatever the document did not happen to
    set. It sets the page, and nothing that belongs to the report.
    """
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Storm Restoration After-Action Report</title><style>"
        "body{margin:0;background:#eef1f4}"
        "img{max-width:100%;height:auto}"
        "@media print{body{background:#fff}}</style>\n"
        "<div style='max-width:52rem;margin:0 auto;padding:2.5rem 3rem;background:#fff'>\n"
        + body
        + "\n</div>"
    )


def html_to_markdown(html: str) -> str:
    """Flatten the mock's HTML to the shape the real export produces.

    Only the constructs the skeleton actually uses, so the traceability pass reads the
    same document text on both paths.
    """
    text = re.sub(r"<tr\b[^>]*>.*?</tr>", _markdown_row, html, flags=re.S)
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.S)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.S)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.S)
    text = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", r"\n![\1]\n", text)
    text = re.sub(r"<li[^>]*>", "\n- ", text)
    text = re.sub(r"</(p|li|ul|ol|table|tbody|thead)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip().strip() for line in text.splitlines()).strip() + "\n"


def _markdown_row(match: re.Match[str]) -> str:
    """One `<tr>` as a markdown table row, with the rule line under a header row.

    The live export renders tables as real markdown tables, so the offline one does too —
    otherwise the traceability pass reads a different document on each path, and the
    table-header rule it relies on would never fire offline.
    """
    row = match.group(0)
    cells = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell)).strip()
        for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S)
    ]
    if not cells:
        return "\n"
    line = "| " + " | ".join(cells) + " |"
    if "<th" in row:
        line += "\n| " + " | ".join("---" for _ in cells) + " |"
    return f"\n{line}\n"
