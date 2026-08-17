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
from .client import Approver, approve_all
from .corpus import load_corpus, load_lessons_opened, load_resolutions
from .curve import render_curve
from .facts import SECTION_TITLES, FactSet, build_facts
from .lessons import apply_event, inherited, load_store, raised_here, save_store, summarise
from .models import Lesson
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
    seconds: float = 0.0
    operations: int | None = None
    edits: int = 0

    @property
    def ok(self) -> bool:
        """Clean citations are not enough. A document carrying a heading nobody asked
        for, or a placeholder an edit failed to replace, has not been produced correctly
        however well its claims trace."""
        return self.trace is not None and self.trace.clean and not self.drift


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


def expected_headings(carried: list[Lesson]) -> list[str]:
    """Every heading the skeleton put in the document, and no others.

    The skeleton decides the document's shape, so this list is derivable from it. A
    heading in the export that is not here was written by the model.
    """
    titles = ["Storm Restoration After-Action Report"]
    for n, title in enumerate(SECTION_TITLES.values(), start=1):
        titles.append(f"{n}. {title}")
    titles.append(f"{len(SECTION_TITLES) + 1}. Restoration Curve")
    titles.append(f"{len(SECTION_TITLES) + 2}. Lessons Learned")
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
    note("parse", f"{len(corpus.log)} log entries, {len(facts.claims)} claims, {len(facts.gaps)} gaps")

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
    skeleton = S.skeleton_html(facts, carried)
    backend.upload_document(session_id, f"{event_id}-after-action.html", skeleton)
    note("upload", f"skeleton uploaded, {len(skeleton):,} bytes")

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
        note("draft", f"{SECTION_TITLES[key]} ({len(facts.sources_for(key))} log lines supplied)")
        gate, rejected = _watch(approver)
        backend.chat(session_id, instruction, approver=gate, model_tier=model_tier, on_event=on_event)
        if rejected:
            refused.add(key)
        drafted.append(key)
        edits += 1
    if skipped:
        note("budget", f"stopped at {edits} edits; {len(skipped)} sections left undrafted")

    # --- the curve, rendered here and placed by SuperDocs
    if sections_limit is None or edits < sections_limit:
        curve_path = render_curve(facts, out_dir / "restoration-curve.png")
        url = backend.upload_image(session_id, f"{event_id}-restoration-curve.png", curve_path)
        note("curve", f"rendered and uploaded: {url[:60]}")
        backend.chat(
            session_id,
            S.curve_instruction(url, facts),
            approver=approver,
            model_tier=model_tier,
            on_event=on_event,
        )
        edits += 1

    # --- lessons raised by this event
    lessons_instruction = S.lessons_instruction(facts, mine, carried)
    if lessons_instruction and (sections_limit is None or edits < sections_limit):
        backend.chat(
            session_id, lessons_instruction, approver=approver, model_tier=model_tier, on_event=on_event
        )
        edits += 1

    # --- an edit that was approved but did not land leaves the section untouched, and
    # the run reads as clean until someone opens the file. Exports are free, so the
    # document is checked before it is called finished, and each unwritten section is
    # re-issued once. Bounded at one pass: a second failure is reported, not retried
    # forever.
    numbered = {key: f"{n}. {title}" for n, (key, title) in enumerate(SECTION_TITLES.items(), 1)}
    check = backend.export(session_id, out_dir / f"{event_id}-check.md", "markdown")
    still_empty = unfilled(check.read_text(encoding="utf-8"), [numbered[k] for k in drafted])
    check.unlink(missing_ok=True)
    # A section whose change a person rejected is empty *because they said so*. Re-issuing
    # it would quietly overturn the decision the gate exists to record, so a refusal ends
    # the matter and only an unexplained empty section is retried.
    stalled = [k for k in drafted if numbered[k] in still_empty and k not in refused]
    for key in stalled:
        if sections_limit is not None and edits >= sections_limit:
            break
        note("retry", f"{SECTION_TITLES[key]} still holds its placeholder; re-issuing")
        backend.chat(
            session_id,
            S.instruction_for(facts, key),
            approver=approver,
            model_tier=model_tier,
            on_event=on_event,
        )
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
    drift = structural_drift(markdown, expected_headings(carried), [numbered[k] for k in drafted])
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
        retried=[SECTION_TITLES[k] for k in stalled],
        seconds=time.monotonic() - started,
        operations=(
            operations_after - operations_before
            if operations_before is not None and operations_after is not None
            else None
        ),
        edits=edits,
    )
