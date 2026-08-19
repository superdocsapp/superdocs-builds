"""The traceability pass.

The card's definition of strong is "every timeline claim in the narrative is traceable
to a log entry". That is a testable property, so it is tested here rather than
promised in a README.

The pass runs over the narrative *as it came back from SuperDocs* — not over the
instructions that were sent. Checking what you sent proves nothing; checking what the
document actually says is the only version of this that means anything.

Four verdicts, and the distinction between the last two is the point:

* ``traced``    — the citation resolves to a log entry the section was given.
* ``unsourced`` — a sentence that reads as fact and carries no citation at all.
* ``foreign``   — cites a real log entry the section was never given. The model reached
                  for evidence outside its brief.
* ``phantom``   — cites an entry id that does not exist in the event log at all.

A phantom is the failure this whole design exists to prevent, and it is reported
loudly rather than being allowed to ship inside a plausible sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .facts import FactSet
from .models import Corpus

CITATION = re.compile(r"\bEL-\d{4}\b")
ASSESSED_MARK = re.compile(r"\[assessed\]", re.IGNORECASE)

# A statement about what the records do NOT contain. It is not an unsourced assertion
# — it is the report doing the thing this build exists to do — so it is exempt from
# needing a citation, while any citation it *does* carry is still checked.
NO_RECORD_MARK = re.compile(r"\[no record\]", re.IGNORECASE)

# Sentences that are structure rather than assertion, and are not expected to cite.
_STRUCTURAL = re.compile(
    r"^\s*(?:#+\s|\d+[\.\)]\s*$|[-*]\s*$|$)|^\s*(?:the records do not|this section|source:)",
    re.IGNORECASE,
)

# The sub-headings the skeleton writes inside a section. A model that repeats one as body
# text below the real heading has added a label, not made a claim — scoring it would report
# "Observed" as an unsourced assertion, which tells a reader nothing. It is still content
# nobody asked for, so `structural_drift` reports it by name.
#
# Emphasis is optional on purpose. A live run repeated the same label twice in one
# document, once as "**What the records do not show**" and once as a bare "Assessed", and
# a pattern that insisted on the asterisks caught the first and scored the second as a
# claim. A line whose entire content is one of four fixed label strings is structure
# however it happens to be styled.
_LABELS = ("Observed", "Assessed", "What the records do not show", "Raised by this event")
_ECHOED_LABEL = re.compile(
    r"^\s*[*_]{0,2}\s*(" + "|".join(re.escape(x) for x in _LABELS) + r")\s*:?\s*[*_]{0,2}\s*$",
    re.IGNORECASE,
)


class Verdict(StrEnum):
    TRACED = "traced"
    UNSOURCED = "unsourced"
    FOREIGN = "foreign"
    PHANTOM = "phantom"


@dataclass
class SentenceResult:
    section: str
    sentence: str
    verdict: Verdict
    citations: list[str] = field(default_factory=list)
    offending: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.TRACED


@dataclass
class TraceReport:
    """What the pass found, in numbers a reviewer can check."""

    results: list[SentenceResult] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.results)

    @property
    def traced(self) -> int:
        return sum(1 for r in self.results if r.verdict is Verdict.TRACED)

    @property
    def flagged(self) -> list[SentenceResult]:
        return [r for r in self.results if not r.ok]

    @property
    def phantoms(self) -> list[SentenceResult]:
        return [r for r in self.results if r.verdict is Verdict.PHANTOM]

    @property
    def clean(self) -> bool:
        return not self.flagged

    def rate(self) -> float:
        return (self.traced / self.checked * 100) if self.checked else 100.0

    def summary(self) -> str:
        return (
            f"{self.traced}/{self.checked} claims traced ({self.rate():.0f}%), "
            f"{len(self.flagged)} flagged"
            + (f", {len(self.phantoms)} citing entries that do not exist" if self.phantoms else "")
        )


def split_sentences(text: str) -> list[str]:
    """Good enough for report prose: split on sentence enders and hard line breaks.

    Deliberately not a full sentence tokeniser — the citations are bracketed and the
    prose is short. A cleverer splitter would add a dependency and a failure mode
    without changing a single verdict.
    """
    parts: list[str] = []
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        for chunk in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", line):
            chunk = chunk.strip()
            if chunk:
                parts.append(chunk)
    return parts


# How many sentences one trailing citation is allowed to cover. A deliberate hard
# limit sitting alongside the paragraph rule below: without it, a paragraph of ten
# uncited assertions ending in one bracketed reference would pass as fully traced.
MAX_SPAN = 3


def citation_spans(sentences: list[str]) -> list[str]:
    """Group sentences into the units a citation actually covers.

    A bracketed reference at the end of a passage covers that passage — that is how
    citation works in prose, and how a commission reads a report. So sentences
    accumulate until one carries a citation or a marker, and that closes the unit.

    Two bounds keep this from becoming a loophole. Callers apply it per paragraph, so
    a citation never reaches back across a paragraph break; and a single citation
    covers at most ``MAX_SPAN`` sentences, so a long uncited passage cannot be
    absolved by one reference tacked on the end. Anything left over forms its own
    uncited unit — text asserted after the evidence ran out.
    """
    units: list[str] = []
    pending: list[str] = []
    for sentence in sentences:
        pending.append(sentence)
        closes = (
            CITATION.search(sentence)
            or ASSESSED_MARK.search(sentence)
            or NO_RECORD_MARK.search(sentence)
        )
        if closes:
            covered = pending[-MAX_SPAN:]
            overflow = pending[:-MAX_SPAN]
            if overflow:
                units.append(" ".join(overflow))
            units.append(" ".join(covered))
            pending = []
    if pending:
        units.append(" ".join(pending))
    return units


# The `| --- | --- |` rule under a markdown table's header row.
_TABLE_RULE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def strip_table_headers(text: str) -> str:
    """Drop a markdown table's header row and the rule beneath it.

    A header row names the columns; it asserts nothing and cites nothing, so scoring it
    would report `| Time | Event |` as an unsourced claim. The rule line is what
    identifies it — the row above a `| --- | --- |` is a header by definition — which is
    narrower than exempting anything that merely looks structural.
    """
    lines = text.replace("\r", "").split("\n")
    drop: set[int] = set()
    for i, line in enumerate(lines):
        if _TABLE_RULE.match(line) and "-" in line:
            drop.add(i)
            if i and lines[i - 1].lstrip().startswith("|"):
                drop.add(i - 1)
    return "\n".join(line for i, line in enumerate(lines) if i not in drop)


def verify(narrative: str, facts: FactSet, section: str, allowed: list[str] | None = None) -> TraceReport:
    """Check one drafted section against the log entries it was permitted to use."""
    corpus: Corpus = facts.corpus
    permitted = set(allowed if allowed is not None else facts.sources_for(section))
    known = corpus.entry_ids
    report = TraceReport()

    # Grouped per paragraph: a citation belongs to the paragraph it sits in and cannot
    # vouch for assertions made in a different one.
    units: list[str] = []
    for paragraph in strip_table_headers(narrative).split("\n"):
        sentences = [
            s
            for s in split_sentences(paragraph)
            if not _STRUCTURAL.match(s) and not _ECHOED_LABEL.match(s)
        ]
        units.extend(citation_spans(sentences))

    for sentence in units:
        if ASSESSED_MARK.search(sentence):
            # Judgement, correctly marked as judgement. Not a traceability failure —
            # the report is required to contain these, clearly labelled.
            continue

        citations = CITATION.findall(sentence)
        if not citations:
            if NO_RECORD_MARK.search(sentence):
                # A declared absence. Nothing to cite, by definition.
                continue
            report.results.append(
                SentenceResult(section=section, sentence=sentence, verdict=Verdict.UNSOURCED)
            )
            continue

        phantom = [c for c in citations if c not in known]
        if phantom:
            report.results.append(
                SentenceResult(
                    section=section,
                    sentence=sentence,
                    verdict=Verdict.PHANTOM,
                    citations=citations,
                    offending=phantom,
                )
            )
            continue

        foreign = [c for c in citations if c not in permitted]
        if foreign:
            report.results.append(
                SentenceResult(
                    section=section,
                    sentence=sentence,
                    verdict=Verdict.FOREIGN,
                    citations=citations,
                    offending=foreign,
                )
            )
            continue

        report.results.append(
            SentenceResult(
                section=section, sentence=sentence, verdict=Verdict.TRACED, citations=citations
            )
        )

    return report


def verify_document(sections: dict[str, str], facts: FactSet) -> TraceReport:
    """Run the pass across every drafted section of one report."""
    whole = TraceReport()
    for section, narrative in sections.items():
        whole.results.extend(verify(narrative, facts, section).results)
    return whole


# A heading in the exported document. The skeleton's own headings are numbered.
_ANY_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
_LEFTOVER = re.compile(r"placeholder\s+for\b|please fill", re.IGNORECASE)


def structural_drift(markdown: str, expected: list[str], drafted: list[str]) -> list[str]:
    """Headings and leftovers that should not be in the finished document.

    Checking citations inside the sections we know about leaves a hole: a model that
    invents a *new* heading can write whatever it likes underneath, and the traceability
    pass never looks there, because it only reads the sections it recognises. A run that
    scored full marks did exactly that once — it added a duplicate section heading and a
    line reading "Please fill", and every claim still traced.

    So the document's shape is checked as well as its contents. Every heading must be one
    the skeleton put there, and no section that was drafted may still be carrying its
    placeholder — an edit that silently failed to land looks identical to one that was
    never asked for.
    """
    allowed = {h.strip().casefold() for h in expected}
    drift = [
        f"unexpected heading: {found.strip()}"
        for found in _ANY_HEADING.findall(markdown)
        if found.strip().casefold() not in allowed
    ]
    drift += [f"placeholder text survived in: {s}" for s in unfilled(markdown, drafted)]
    drift += [
        f"section label repeated as body text: {found.group(1)}"
        for line in markdown.splitlines()
        if (found := _ECHOED_LABEL.match(line))
    ]
    return drift


def unfilled(markdown: str, sections: list[str]) -> list[str]:
    """Sections that were drafted but still hold their placeholder.

    An edit that is proposed, approved and then does not land leaves the document exactly
    as it was, and the run reads as successful right up until someone opens the file. So
    the document is asked rather than the API: whatever the service reported, a section
    still carrying "Placeholder for…" was not written.
    """
    return [s for s in sections if _LEFTOVER.search(markdown_after(markdown, s) or "")]


def markdown_after(markdown: str, heading: str) -> str:
    """The text under one heading, up to the next heading of the same or higher level."""
    lines = markdown.replace("\r", "").split("\n")
    wanted = heading.strip().casefold()
    for i, line in enumerate(lines):
        found = _ANY_HEADING.match(line)
        if not found or found.group(1).strip().casefold() != wanted:
            continue
        level = len(line) - len(line.lstrip("#"))
        body: list[str] = []
        for rest in lines[i + 1 :]:
            nxt = _ANY_HEADING.match(rest)
            if nxt and (len(rest) - len(rest.lstrip("#"))) <= level:
                break
            body.append(rest)
        return "\n".join(body).strip()
    return ""
