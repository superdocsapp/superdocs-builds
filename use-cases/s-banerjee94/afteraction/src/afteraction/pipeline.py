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
from .trace import TraceReport, verify

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
    carry: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    seconds: float = 0.0
    operations: int | None = None
    edits: int = 0

    @property
    def ok(self) -> bool:
        return self.trace is not None and self.trace.clean


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
    for key in SECTION_TITLES:
        if sections_limit is not None and edits >= sections_limit:
            skipped.append(key)
            continue
        instruction = S.instruction_for(facts, key)
        if not instruction:
            continue
        note("draft", f"{SECTION_TITLES[key]} ({len(facts.sources_for(key))} log lines supplied)")
        backend.chat(session_id, instruction, approver=approver, model_tier=model_tier, on_event=on_event)
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
    written = markdown_sections(exports["markdown"].read_text(encoding="utf-8"))
    for key, text in written.items():
        if key in drafted:
            report.results.extend(verify(text, facts, key).results)
    note(
        "verify",
        report.summary()
        + (f"; {len(skipped)} sections not drafted" if skipped else ""),
    )

    save_store(store, store_path)

    operations_after = backend.operations_used()
    return RunResult(
        event_id=event_id,
        session_id=session_id,
        facts=facts,
        store=store,
        exports=exports,
        trace=report,
        carry=counts,
        skipped=skipped,
        seconds=time.monotonic() - started,
        operations=(
            operations_after - operations_before
            if operations_before is not None and operations_after is not None
            else None
        ),
        edits=edits,
    )
