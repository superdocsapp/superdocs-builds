"""One event, end to end.

upload → per-section chat → human gate → curve → lessons → export → verify.

The traceability pass runs last and reads the *exported* document, not the
instructions that were sent. Verifying what you sent proves only that you can echo
yourself; verifying the exported deliverable is the only check that means anything,
and it is the number this build is graded on.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import sections as S
from .client import Approver, SuperDocsError, approve_all
from .corpus import load_corpus, load_lessons_opened, load_resolutions
from .curve import render_complaints, render_curve
from .facts import SECTION_TITLES, FactSet, build_facts
from .lessons import apply_event, inherited, load_store, raised_here, save_store, summarise
from .models import Lesson
from .surgical import SurgicalReport, fingerprints
from .trace import TraceReport, structural_drift, unfilled, verify

TITLE_TO_KEY = {title: key for key, title in SECTION_TITLES.items()}
HEADING = re.compile(r"^##\s+\d+\.\s+(.*)$")


class Backend(Protocol):
    def upload_document(self, session_id: str, filename: str, content: str) -> dict[str, Any]: ...
    def upload_image(self, session_id: str, filename: str, image: Path | bytes) -> str: ...
    def chat(self, session_id: str, message: str, approver: Approver = ..., model_tier: str = ..., on_event: Callable[[str, str], None] | None = ...) -> dict[str, Any]: ...
    def export(self, session_id: str, out_path: Path, fmt: str = ...) -> Path: ...
    def operations_used(self) -> int | None: ...


@dataclass
class RunResult:
    event_id: str
    session_id: str
    facts: FactSet
    store: list[Lesson]
    exports: dict[str, Path] = field(default_factory=dict)
    trace: TraceReport | None = None
    drift: list[str] = field(default_factory=list)
    carry: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    surgical: SurgicalReport | None = None
    seconds: float = 0.0
    operations: int | None = None
    edits: int = 0

    @property
    def ok(self) -> bool:
        """Clean citations are not enough. A document carrying a heading nobody asked
        for, a placeholder an edit failed to replace, or a section moved by an edit that
        was aimed somewhere else has not been produced correctly however well its claims
        trace."""
        return (
            self.trace is not None
            and self.trace.clean
            and not self.drift
            and (self.surgical is None or self.surgical.clean)
        )


def _watch(approver: Approver) -> tuple[Approver, list[str]]:
    """The same gate, plus a record of what it turned down.

    Needed to tell an edit that failed from an edit a person refused. Both leave the
    section holding its placeholder, and only the first should ever be retried.
    """
    rejected: list[str] = []

    def gate(change):  # type: ignore[no-untyped-def]
        ok, why = approver(change)
        if not ok:
            rejected.append(change.change_id)
        return ok, why

    return gate, rejected


def expected_headings(carried: list[Lesson], facts: FactSet | None = None) -> list[str]:
    """Every heading the skeleton put in the document, and no others.

    The skeleton decides the document's shape, so this list is derivable from it. A
    heading in the export that is not here was written by the model.
    """
    titles = ["Storm Restoration After-Action Report", "Executive Summary"]
    for n, title in enumerate(SECTION_TITLES.values(), start=1):
        titles.append(f"{n}. {title}")
    titles.append(S.heading_for("curve"))
    # The contacts chart only exists when consumers actually contacted the utility, so
    # its heading is only expected when the records carry one.
    if facts is not None and facts.complaints:
        titles.append(S.heading_for("complaints"))
    titles.append(S.heading_for("lessons", facts))
    titles += ["Observed", "Assessed", "What the records do not show", "Raised by this event"]
    if carried:
        titles.append("Carried forward from previous events")
    return titles


def markdown_sections(markdown: str) -> dict[str, str]:
    """Split an exported report into `{section_key: text}` by its numbered headings."""
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        heading = HEADING.match(line.strip())
        if heading:
            current = TITLE_TO_KEY.get(heading.group(1).strip())
            if current:
                found.setdefault(current, [])
            continue
        if current and current in found:
            found[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in found.items()}


def run_event(
    event_id: str,
    backend: Backend,
    *,
    data_root: Path | None = None,
    store_path: Path | None = None,
    out_dir: Path | None = None,
    approver: Approver = approve_all,
    sections_limit: int | None = None,
    model_tier: str = "core",
    on_event: Callable[[str, str], None] | None = None,
) -> RunResult:
    """Build one event's report inside a SuperDocs document.

    `sections_limit` is the small-sample mode the brief asks for: cap the number of
    billable edit turns so a first run costs a handful of operations rather than a
    budget.
    """
    note = on_event or (lambda stage, detail: None)
    started = time.monotonic()
    out_dir = out_dir or Path("out") / event_id
    session_id = f"afteraction-{event_id}-{int(time.time())}"

    corpus = load_corpus(event_id, data_root)
    facts = build_facts(corpus)
    note("parse", f"{len(corpus.log)} records, {len(facts.claims)} claims, {len(facts.gaps)} gaps")

    # --- carry-forward, before drafting: this event's report opens with what it inherits
    store = load_store(store_path)
    store = apply_event(
        store,
        corpus,
        load_lessons_opened(event_id, data_root),
        load_resolutions(event_id, data_root),
    )
    carried = inherited(store, event_id)
    mine = raised_here(store, event_id)
    counts = summarise(store, event_id)
    note(
        "carry",
        f"{counts['inherited']} inherited "
        f"({counts['inherited_open']} open, {counts['inherited_closed']} closed), "
        f"{counts['raised_here']} raised here",
    )

    operations_before = backend.operations_used()

    # --- upload the skeleton (not billable)
    skeleton = S.skeleton_html(facts, carried, mine)
    backend.upload_document(session_id, f"{event_id}-after-action.html", skeleton)
    note("upload", f"skeleton uploaded, {len(skeleton):,} bytes")

    # --- every chat turn goes through here, so the promise each instruction makes —
    # "change nothing outside this section" — is measured rather than asserted. The
    # document is fingerprinted per section between turns; exports cost no operations,
    # so the evidence is free.
    numbered = {key: f"{n}. {title}" for n, (key, title) in enumerate(SECTION_TITLES.items(), 1)}
    scratch = out_dir / f"{event_id}-snapshot.md"
    surgical = SurgicalReport()

    def snapshot() -> dict[str, str]:
        path = backend.export(session_id, scratch, "markdown")
        text = path.read_text(encoding="utf-8")
        path.unlink(missing_ok=True)
        return fingerprints(text)

    # --- the document as it currently stands, rewritten after every turn
    #
    # A live run takes several minutes, and until it ends the only thing a person can
    # watch is a progress line claiming a section was drafted. This writes the whole
    # document to one HTML file after every turn and overwrites it in place, so anyone
    # can open it three or five sections in and read what the document actually says
    # now. Exports cost no operations, so the only price is a moment of latency.
    #
    # It refreshes whether the change was approved, rejected, or landed as nothing at
    # all — a rejected turn leaving the page unchanged is itself worth being able to
    # see, and a view that only appeared on success would hide exactly the runs worth
    # watching.
    progress_page = out_dir / f"{event_id}-in-progress.html"

    def publish() -> None:
        try:
            backend.export(session_id, progress_page, "html")
        except SuperDocsError as exc:
            # A convenience view must never fail a run that is otherwise sound. If the
            # format is refused, say so once and carry on drafting.
            note("progress", f"cannot refresh {progress_page.name}: {exc}")

    current = snapshot()
    publish()

    def turn(instruction: str, aimed_at: str, gate: Approver | None = None) -> None:
        nonlocal current
        # The instruction goes out before the change comes back, so it is announced
        # first. SuperDocs writes the prose; what this tool controls is the brief, and a
        # reviewer who sees only the diff is reviewing the answer without the question.
        note("prompt", instruction)
        backend.chat(
            session_id,
            instruction,
            approver=gate or approver,
            model_tier=model_tier,
            on_event=on_event,
        )
        after = snapshot()
        for stray in surgical.record(aimed_at, current, after):
            note("surgical", f"editing “{aimed_at}” also changed “{stray}”")
        current = after
        publish()

    # --- one instruction per section
    edits = 0
    drafted: list[str] = []
    skipped: list[str] = []
    refused: set[str] = set()
    for key in SECTION_TITLES:
        if sections_limit is not None and edits >= sections_limit:
            skipped.append(key)
            continue
        instruction = S.instruction_for(facts, key)
        if not instruction:
            continue
        note("draft", f"{SECTION_TITLES[key]} ({len(facts.sources_for(key))} records supplied)")
        gate, rejected = _watch(approver)
        turn(instruction, numbered[key], gate)
        if rejected:
            refused.add(key)
        drafted.append(key)
        edits += 1
    if skipped:
        note("budget", f"stopped at {edits} edits; {len(skipped)} sections left undrafted")

    # --- the charts, rendered here and placed by SuperDocs
    #
    # A chart turn is an edit like any other, and one that is approved but does not land
    # leaves the placeholder sitting where the chart should be. These two sections are
    # not in SECTION_TITLES, so they were outside the placeholder check and outside the
    # retry — a live run put the curve edit into the neighbouring section and exported a
    # report with "Placeholder for the restoration curve" still in it. They are tracked
    # here so they are checked and re-issued alongside everything else.
    image_turns: list[tuple[str, str]] = []

    curve_title = S.heading_for("curve")
    if sections_limit is None or edits < sections_limit:
        curve_path = render_curve(facts, out_dir / "restoration-curve.png")
        url = backend.upload_image(session_id, f"{event_id}-restoration-curve.png", curve_path)
        note("curve", f"rendered and uploaded: {url[:60]}")
        curve_brief = S.curve_instruction(url, facts)
        turn(curve_brief, curve_title)
        image_turns.append((curve_title, curve_brief))
        edits += 1

    # The contacts chart exists only when consumers contacted the utility. An event
    # nobody called about gets no chart rather than an empty pair of axes.
    complaints_title = S.heading_for("complaints")
    if facts.complaints and (sections_limit is None or edits < sections_limit):
        chart = render_complaints(facts, out_dir / "consumer-contacts.png")
        instruction = S.complaints_instruction("", facts)
        if chart and instruction:
            url = backend.upload_image(session_id, f"{event_id}-consumer-contacts.png", chart)
            note("chart", f"contacts chart rendered and uploaded: {url[:60]}")
            chart_brief = S.complaints_instruction(url, facts)
            turn(chart_brief, complaints_title)
            image_turns.append((complaints_title, chart_brief))
            edits += 1

    # --- lessons raised by this event
    lessons_title = S.heading_for("lessons", facts)
    lessons_instruction = S.lessons_instruction(facts, mine, carried)
    # An event that raised nothing needs no turn: the skeleton already states the absence,
    # so the section is complete on upload rather than waiting for an edit.
    lessons_done = not mine
    if lessons_instruction and (sections_limit is None or edits < sections_limit):
        turn(lessons_instruction, lessons_title)
        lessons_done = True
        edits += 1

    # --- an edit that was approved but did not land leaves the section untouched, and
    # the run reads as clean until someone opens the file. The document is already in
    # hand from the last snapshot, so each unwritten section is re-issued once. Bounded
    # at one pass: a second failure is reported, not retried forever.
    check = backend.export(session_id, scratch, "markdown")
    still_empty = unfilled(
        check.read_text(encoding="utf-8"),
        [numbered[k] for k in drafted]
        + [title for title, _ in image_turns]
        + ([lessons_title] if lessons_done else []),
    )
    check.unlink(missing_ok=True)
    # A section whose change a person rejected is empty *because they said so*. Re-issuing
    # it would quietly overturn the decision the gate exists to record, so a refusal ends
    # the matter and only an unexplained empty section is retried.
    stalled = [k for k in drafted if numbered[k] in still_empty and k not in refused]
    retried_sections: list[str] = []
    for key in stalled:
        if sections_limit is not None and edits >= sections_limit:
            break
        note("retry", f"{SECTION_TITLES[key]} still holds its placeholder; re-issuing")
        turn(S.instruction_for(facts, key), numbered[key])
        retried_sections.append(SECTION_TITLES[key])
        edits += 1

    # A chart carries no citations to reject, so there is no refusal to respect here —
    # an empty chart section only ever means the image did not land.
    for title, brief in image_turns:
        if title not in still_empty:
            continue
        if sections_limit is not None and edits >= sections_limit:
            break
        note("retry", f"{title} still holds its placeholder; re-issuing")
        turn(brief, title)
        # reported without its number, so the retry list reads the same way for every
        # section whether it came from SECTION_TITLES or from a chart
        retried_sections.append(title.split(". ", 1)[-1])
        edits += 1

    # The lessons section gets the same treatment. It was left out of the first version of
    # this and a live run promptly wrote the items *above* the heading rather than over the
    # placeholder, leaving the placeholder in a report that traced 28 of 28 claims.
    if lessons_done and lessons_instruction and lessons_title in still_empty:
        if sections_limit is None or edits < sections_limit:
            note("retry", "Lessons Learned still holds its placeholder; re-issuing")
            turn(lessons_instruction, lessons_title)
            stalled_lessons = True
            edits += 1
        else:
            stalled_lessons = False
    else:
        stalled_lessons = False

    # --- the executive summary, written last from the finished document
    #
    # Last because a summary written before the sections would be a summary of what the
    # sections were going to say. By this point every section is drafted and every
    # stalled one has been re-issued, so SuperDocs is summarising the report a reader
    # will actually get. It is the one instruction that asks the model to read the
    # document rather than a list of facts — the document is already there, so handing
    # over a second copy of the facts would only give the two a chance to disagree.
    summary_title = "Executive Summary"
    summary_done = False
    if sections_limit is None or edits < sections_limit:
        note("summary", f"summarising the finished report in {S.SUMMARY_SENTENCES} sentences")
        turn(S.summary_instruction(facts), summary_title)
        summary_done = True
        edits += 1

        # The same one-pass retry the sections get. A summary that quietly failed to
        # land leaves the word "Placeholder" at the top of the document, which is the
        # first thing a reader sees.
        check = backend.export(session_id, scratch, "markdown")
        empty_summary = unfilled(check.read_text(encoding="utf-8"), [summary_title])
        check.unlink(missing_ok=True)
        if empty_summary and (sections_limit is None or edits < sections_limit):
            note("retry", "the executive summary still holds its placeholder; re-issuing")
            turn(S.summary_instruction(facts), summary_title)
            edits += 1

    # --- export (free) then verify what was actually produced
    exports = {
        "markdown": backend.export(session_id, out_dir / f"{event_id}-after-action.md", "markdown"),
        "docx": backend.export(session_id, out_dir / f"{event_id}-after-action.docx", "docx"),
    }
    note("export", f"{', '.join(p.name for p in exports.values())}")

    # Verify only what was actually drafted. A section left untouched still holds its
    # placeholder, and scoring that as an unsourced claim would report a failure that
    # says nothing about drafting quality — the undrafted sections are named instead,
    # so nothing goes quiet.
    report = TraceReport()
    markdown = exports["markdown"].read_text(encoding="utf-8")
    written = markdown_sections(markdown)
    for key, text in written.items():
        if key in drafted:
            report.results.extend(verify(text, facts, key).results)
    note(
        "verify",
        report.summary()
        + (f"; {len(skipped)} sections not drafted" if skipped else ""),
    )

    # Citations inside known sections say nothing about content invented outside them.
    # The lessons section is checked alongside the numbered ones. It is the only section
    # whose content can be legitimately absent — an event may raise nothing — and that is
    # exactly why a placeholder surviving there once shipped unnoticed.
    checked_sections = (
        [numbered[k] for k in drafted]
        + [title for title, _ in image_turns]
        + ([lessons_title] if lessons_done else [])
    )
    if summary_done:
        checked_sections.append(summary_title)
    drift = structural_drift(markdown, expected_headings(carried, facts), checked_sections)
    for problem in drift:
        note("drift", problem)

    save_store(store, store_path)

    operations_after = backend.operations_used()
    return RunResult(
        event_id=event_id,
        session_id=session_id,
        facts=facts,
        store=store,
        exports=exports,
        trace=report,
        drift=drift,
        carry=counts,
        skipped=skipped,
        retried=retried_sections + (["Lessons Learned"] if stalled_lessons else []),
        surgical=surgical,
        seconds=time.monotonic() - started,
        operations=(
            operations_after - operations_before
            if operations_before is not None and operations_after is not None
            else None
        ),
        edits=edits,
    )
